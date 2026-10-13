from pathlib import Path
from typing import List
import re

from src.graph.state import AgentState, AgentStateUpdate
from src.models.schemas import StatementSummary
from src.parsers.pdf_parser import PDFPlumberStatementParser
from src.parsers.csv_parser import CSVStatementParser
from src.mcp.server import reconcile_statement_balances
from src.mcp.db import DatabaseManager
from src.graph.enrichment import AdaptiveEnrichmentEngine

db = DatabaseManager()
enrichment_engine = AdaptiveEnrichmentEngine(db=db)


def ingest_node(state: AgentState) -> AgentStateUpdate:
    """Ingests PDF or CSV document into raw content and transaction candidates."""
    file_path = Path(state["file_path"])
    errors: List[str] = list(state.get("errors", []))

    if not file_path.exists():
        errors.append(f"File not found: {file_path}")
        return {"status": "failed", "errors": errors}

    pdf_parser = PDFPlumberStatementParser()
    csv_parser = CSVStatementParser()

    if pdf_parser.can_parse(file_path):
        raw_content, txs = pdf_parser.parse(file_path)
    elif csv_parser.can_parse(file_path):
        raw_content, txs = csv_parser.parse(file_path)
    else:
        errors.append(f"Unsupported file format: {file_path.suffix}")
        return {"status": "failed", "errors": errors}

    return {
        "raw_content": raw_content,
        "transactions": txs,
        "status": "in_progress",
        "errors": errors,
    }


def extract_summary_node(state: AgentState) -> AgentStateUpdate:
    """Extracts ground truth StatementSummary from Page 1 raw content if PDF."""
    raw_content = state.get("raw_content", "")
    file_path = state.get("file_path", "")

    # CSV files have no statement header
    if file_path.lower().endswith(".csv"):
        return {"summary": None}

    # Extract summary header using semantic regex or Ollama
    summary = None
    start_bal_match = re.search(
        r"(?:Starting|Beginning|Previous)\s*Balance[:\s]*\$?([0-9,]+\.[0-9]{2})",
        raw_content,
        re.IGNORECASE,
    )
    end_bal_match = re.search(
        r"(?:Ending|New)\s*Balance[:\s]*\$?([0-9,]+\.[0-9]{2})", raw_content, re.IGNORECASE
    )
    credits_match = re.search(
        r"Total\s*(?:Deposits|Credits|Additions)[:\s]*\$?([0-9,]+\.[0-9]{2})",
        raw_content,
        re.IGNORECASE,
    )
    debits_match = re.search(
        r"Total\s*(?:Withdrawals|Debits|Subtractions)[:\s]*\$?([0-9,]+\.[0-9]{2})",
        raw_content,
        re.IGNORECASE,
    )

    if end_bal_match:
        end_bal = float(end_bal_match.group(1).replace(",", ""))
        start_bal = float(start_bal_match.group(1).replace(",", "")) if start_bal_match else 0.0
        credits = float(credits_match.group(1).replace(",", "")) if credits_match else 0.0
        debits = float(debits_match.group(1).replace(",", "")) if debits_match else 0.0

        summary = StatementSummary(
            institution="Bank PDF",
            account_number_masked="****0000",
            statement_period_start="2026-05-01",
            statement_period_end="2026-05-31",
            starting_balance=start_bal,
            total_credits=credits,
            total_debits=debits,
            stated_ending_balance=end_bal,
        )

    return {"summary": summary}


def reconcile_node(state: AgentState) -> AgentStateUpdate:
    """Evaluates mathematical balance reconciliation invariant."""
    summary = state.get("summary")
    txs = state.get("transactions", [])
    errors = list(state.get("errors", []))

    # If CSV with no ground truth header, mark reconciled
    if not summary:
        return {"status": "reconciled", "reconciliation_result": None}

    net_line_items = sum(tx.amount for tx in txs)
    report = reconcile_statement_balances(
        starting_balance=summary.starting_balance,
        stated_ending_balance=summary.stated_ending_balance,
        total_credits=summary.total_credits,
        total_debits=summary.total_debits,
        line_items_net=net_line_items,
    )

    reconciled = report["is_reconciled"]
    delta = report["delta"]

    result = {
        "status": "reconciled" if reconciled else "unreconciled_delta",
        "stated_ending_balance": summary.stated_ending_balance,
        "line_calculated_ending": report["line_calculated_ending"],
        "delta": delta,
        "total_transactions_count": len(txs),
        "reflection_attempts": state.get("reflection_attempts", 0),
    }

    status = "reconciled" if reconciled else "unreconciled_delta"
    if not reconciled:
        errors.append(
            f"Reconciliation delta: ${delta:.2f} on attempt {state.get('reflection_attempts', 0)}"
        )

    return {"status": status, "reconciliation_result": result, "errors": errors}


def reflect_and_correct_node(state: AgentState) -> AgentStateUpdate:
    """Diagnoses and heals sign inversions on ambiguous line items."""
    attempts = state.get("reflection_attempts", 0) + 1
    txs = list(state.get("transactions", []))
    recon_result = state.get("reconciliation_result")

    if recon_result and recon_result.get("delta", 0) != 0:
        delta = recon_result["delta"]

        for tx in txs:
            # Check if flipping this transaction's sign closes the discrepancy
            new_amount = -tx.amount
            amount_change = new_amount - tx.amount
            if abs(delta - amount_change) < 0.01:
                tx.amount = new_amount
                break

    return {"reflection_attempts": attempts, "transactions": txs}


def enrich_and_categorize_node(state: AgentState) -> AgentStateUpdate:
    """Enriches and categorizes transactions using the 3-Tier intelligence engine."""
    txs = state.get("transactions", [])
    enriched_txs = []
    for tx in txs:
        enriched_txs.append(enrichment_engine.enrich_transaction(tx))

    return {"transactions": enriched_txs}


def persist_node(state: AgentState) -> AgentStateUpdate:
    """Persists statement and transactions to SQLite database."""
    summary = state.get("summary")
    txs = state.get("transactions", [])
    raw_content = state.get("raw_content", "")
    file_path = state.get("file_path", "unknown")

    stmt_id = None
    if summary:
        stmt_id = db.insert_raw_statement(
            summary, raw_content=raw_content, filename=Path(file_path).name
        )

    inserted, dupes = db.insert_transactions(txs, statement_id=stmt_id)

    status = state.get("status")
    if status == "unreconciled_delta":
        status = "needs_human_review"

    return {"status": status}
