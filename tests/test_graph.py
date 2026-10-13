from pathlib import Path
from src.graph.workflow import build_financial_statement_graph, route_reconciliation
from src.graph.state import AgentState
from src.models.schemas import StatementSummary, Transaction, AccountType


def test_graph_happy_path_csv(tmp_path: Path):
    csv_file = tmp_path / "test_rocket.csv"
    csv_file.write_text(
        "Date,Description,Amount\n2026-05-01,COSTCO WHSE,-142.50\n2026-05-02,STARBUCKS,-6.50\n"
    )

    app = build_financial_statement_graph()
    initial_state: AgentState = {
        "file_path": str(csv_file),
        "raw_content": "",
        "summary": None,
        "transactions": [],
        "reconciliation_result": None,
        "reflection_attempts": 0,
        "status": "in_progress",
        "errors": [],
    }

    final_state = app.invoke(initial_state)
    assert final_state["status"] == "reconciled"
    assert len(final_state["transactions"]) == 2
    assert len(final_state["raw_content"]) > 0


def test_graph_missing_file_error_surfaced():
    app = build_financial_statement_graph()
    initial_state: AgentState = {
        "file_path": "/non/existent/file.csv",
        "raw_content": "",
        "summary": None,
        "transactions": [],
        "reconciliation_result": None,
        "reflection_attempts": 0,
        "status": "in_progress",
        "errors": [],
    }

    final_state = app.invoke(initial_state)
    assert final_state["status"] == "failed"
    assert any("File not found" in err for err in final_state["errors"])


def test_graph_automated_reflection_loop_heals_discrepancy(tmp_path: Path):
    summary = StatementSummary(
        institution="Chase",
        account_number_masked="****1234",
        statement_period_start="2026-05-01",
        statement_period_end="2026-05-31",
        starting_balance=1000.0,
        total_credits=0.0,
        total_debits=15.0,
        stated_ending_balance=985.0,
    )
    # Flawed extraction: charge is +15.0 instead of -15.0 (causes $30.0 delta)
    flawed_tx = Transaction(
        date="2026-05-05",
        raw_description="CHIPOTLE 1234",
        clean_merchant="Chipotle",
        amount=15.0,
        institution="Chase",
        account_type=AccountType.CHECKING,
    )

    initial_state: AgentState = {
        "file_path": str(tmp_path / "dummy.pdf"),
        "raw_content": "",
        "summary": summary,
        "transactions": [flawed_tx],
        "reconciliation_result": None,
        "reflection_attempts": 0,
        "status": "in_progress",
        "errors": [],
    }

    from src.graph.nodes import reconcile_node, reflect_and_correct_node

    # Reconcile detects delta
    step1 = reconcile_node(initial_state)
    assert step1["status"] == "unreconciled_delta"

    # Reflection heals the sign error
    initial_state.update(step1)
    step2 = reflect_and_correct_node(initial_state)
    assert step2["reflection_attempts"] == 1
    assert step2["transactions"][0].amount == -15.0

    # Re-reconcile with healed state
    initial_state.update(step2)
    step3 = reconcile_node(initial_state)
    assert step3["status"] == "reconciled"
    assert step3["reconciliation_result"]["delta"] == 0.0


def test_graph_circuit_breaker_caps_retries():
    state: AgentState = {
        "file_path": "dummy.pdf",
        "raw_content": "",
        "summary": None,
        "transactions": [],
        "reconciliation_result": None,
        "reflection_attempts": 2,  # Max retries reached
        "status": "unreconciled_delta",
        "errors": [],
    }

    next_node = route_reconciliation(state)
    assert next_node == "enrich_and_categorize"
