"""
Command Line Interface (CLI) for localfin.

Provides local-first terminal commands for statement ingestion,
reconciliation reporting, spending summaries, and tag queries.
"""

import argparse
import sys
from pathlib import Path

from src.config import APP_DISPLAY_NAME
from src.mcp.db import DatabaseManager
from src.graph.workflow import build_financial_statement_graph
from src.models.schemas import TransactionQuery


def format_currency(amount: float) -> str:
    """Formats float as clean currency string."""
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return f"${amount:,.2f}"


def handle_ingest(args):
    """Executes the LangGraph ingestion and reconciliation pipeline for a statement file."""
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File '{file_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"\n[{APP_DISPLAY_NAME}] Ingesting statement: {file_path.name}")
    print("=" * 60)

    graph = build_financial_statement_graph()
    initial_state = {
        "file_path": str(file_path),
        "raw_content": "",
        "summary": None,
        "transactions": [],
        "reconciliation_result": None,
        "reflection_attempts": 0,
        "status": "in_progress",
        "errors": [],
    }

    result = graph.invoke(initial_state)

    status = result.get("status", "unknown")
    txs = result.get("transactions", [])
    summary = result.get("summary")
    recon = result.get("reconciliation_result") or {}
    reflection_attempts = result.get("reflection_attempts", 0)

    print(f"Status:               {status.upper()}")
    print(f"Total Transactions:   {len(txs)}")
    print(f"Reflection Attempts:  {reflection_attempts}")

    if summary:
        stated = summary.stated_ending_balance
        calc = recon.get("calculated_ending_balance", 0.0)
        delta = recon.get("delta", 0.0)
        print(f"Stated Ending Bal:    {format_currency(stated)}")
        print(f"Calculated Ending:    {format_currency(calc)}")
        print(f"Discrepancy (Delta):  {format_currency(delta)}")

    if result.get("errors"):
        print("\nWarnings/Errors:")
        for err in result["errors"]:
            print(f" - {err}")

    print("\nSample Line Items:")
    print(f"{'Date':<12} | {'Merchant':<25} | {'Category':<15} | {'Amount':>10}")
    print("-" * 68)
    for tx in txs[:10]:
        print(
            f"{tx.date:<12} | {tx.clean_merchant[:25]:<25} | {tx.category[:15]:<15} | {format_currency(tx.amount):>10}"
        )

    if len(txs) > 10:
        print(f"... and {len(txs) - 10} more transactions.")
    print("=" * 60)


def handle_summary(args):
    """Prints categorized expense spending summary."""
    db = DatabaseManager()
    summary = db.get_spending_summary()

    print(f"\n[{APP_DISPLAY_NAME}] Spending by Category")
    print("=" * 40)
    if not summary:
        print("No transactions found in database.")
        return

    total = 0.0
    for cat, amt in sorted(summary.items(), key=lambda x: x[1], reverse=True):
        print(f"{cat:<25} : {format_currency(-amt):>12}")
        total += amt

    print("-" * 40)
    print(f"{'TOTAL EXPENSES':<25} : {format_currency(-total):>12}")
    print("=" * 40)


def handle_by_tag(args):
    """Prints total spending for a specific tag."""
    db = DatabaseManager()
    tag = args.tag.strip()
    total = db.get_spending_by_tag(tag)
    print(f"\n[{APP_DISPLAY_NAME}] Tag: '{tag.lower()}'")
    print(f"Total Spending: {format_currency(-total)}")


def handle_transactions(args):
    """Lists recent transactions with optional category filter."""
    db = DatabaseManager()
    query = TransactionQuery(category=args.category, limit=args.limit)
    txs = db.get_transactions(query)

    print(f"\n[{APP_DISPLAY_NAME}] Stored Transactions (Limit: {args.limit})")
    print("=" * 72)
    if not txs:
        print("No transactions match the query.")
        return

    print(f"{'Date':<12} | {'Merchant':<25} | {'Category':<15} | {'Amount':>12}")
    print("-" * 72)
    for tx in txs:
        print(
            f"{tx.date:<12} | {tx.clean_merchant[:25]:<25} | {tx.category[:15]:<15} | {format_currency(tx.amount):>12}"
        )
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(
        prog=APP_DISPLAY_NAME.lower(),
        description=f"{APP_DISPLAY_NAME}: Local-First Financial Statement & Transaction Intelligence Agent",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Ingest Command
    ingest_parser = subparsers.add_parser(
        "ingest", help="Ingest and reconcile a bank statement PDF or CSV"
    )
    ingest_parser.add_argument("file", help="Path to statement file (PDF or CSV)")
    ingest_parser.set_defaults(func=handle_ingest)

    # Summary Command
    summary_parser = subparsers.add_parser("summary", help="View category spending summary")
    summary_parser.set_defaults(func=handle_summary)

    # By-Tag Command
    tag_parser = subparsers.add_parser("by-tag", help="View spending by tag")
    tag_parser.add_argument("tag", help="Tag name to query")
    tag_parser.set_defaults(func=handle_by_tag)

    # Transactions Command
    tx_parser = subparsers.add_parser("transactions", help="List stored transactions")
    tx_parser.add_argument("--category", help="Optional category filter")
    tx_parser.add_argument(
        "--limit", type=int, default=20, help="Number of records to show (default: 20)"
    )
    tx_parser.set_defaults(func=handle_transactions)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
