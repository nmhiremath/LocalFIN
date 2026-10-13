import json
import pytest
from src.mcp.server import (
    mcp_server,
    reconcile_statement_balances,
    check_merchant_memory,
    save_merchant_memory,
    insert_transactions_batch,
)


@pytest.mark.asyncio
async def test_mcp_tool_registration():
    tools = await mcp_server.list_tools()
    tool_names = [t.name for t in tools]
    assert "check_merchant_memory" in tool_names
    assert "save_merchant_memory" in tool_names
    assert "reconcile_statement_balances" in tool_names
    assert "insert_transactions_batch" in tool_names
    assert "query_spending_summary" in tool_names


def test_deterministic_reconciliation_tool_success():
    # Starting $1,000 + Credits $2,500 - Debits $1,200 = Stated Ending $2,300
    # Net line items: +$1,300 (Deposits minus withdrawals)
    result = reconcile_statement_balances(
        starting_balance=1000.00,
        stated_ending_balance=2300.00,
        total_credits=2500.00,
        total_debits=1200.00,
        line_items_net=1300.00,
    )
    assert result["is_reconciled"] is True
    assert result["delta"] == 0.0
    assert result["status"] == "reconciled"


def test_deterministic_reconciliation_tool_discrepancy():
    # Stated Ending is $2,300, but line items net sum only accounts for $1,270 ($30 missing)
    result = reconcile_statement_balances(
        starting_balance=1000.00,
        stated_ending_balance=2300.00,
        total_credits=2500.00,
        total_debits=1200.00,
        line_items_net=1270.00,
    )
    assert result["is_reconciled"] is False
    assert result["delta"] == 30.00
    assert result["status"] == "unreconciled_delta"


def test_mcp_memory_and_batch_insert():
    # 1. Save pattern
    save_res = save_merchant_memory(
        pattern="INDIAN GROCERY",
        clean_merchant="Patel Brothers",
        category="Food & Dining",
        subcategory="Groceries",
        leaf_label="Indian Grocery",
        entities_json=json.dumps({"specialty": "Spices & Produce"}),
    )
    assert save_res["success"] is True

    # 2. Check pattern
    check_res = check_merchant_memory("INDIAN GROCERY AUSTIN TX")
    assert check_res["found"] is True
    assert check_res["data"]["clean_merchant"] == "Patel Brothers"

    # 3. Insert transaction batch via tool
    sample_batch = [
        {
            "date": "2026-05-10",
            "raw_description": "INDIAN GROCERY AUSTIN TX",
            "clean_merchant": "Patel Brothers",
            "amount": -65.40,
            "category": "Food & Dining",
            "institution": "Chase",
            "account_type": "checking",
        }
    ]
    batch_res = insert_transactions_batch(json.dumps(sample_batch))
    assert batch_res["total_processed"] == 1
