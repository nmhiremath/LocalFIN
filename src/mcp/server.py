import json
from typing import Dict, Any
from mcp.server.mcpserver import MCPServer
from src.config import APP_DISPLAY_NAME
from src.mcp.db import DatabaseManager
from src.models.schemas import Transaction, AccountType

# Initialize MCP Server instance
mcp_server = MCPServer(f"{APP_DISPLAY_NAME}-Intelligence")
db = DatabaseManager()


@mcp_server.tool()
def check_merchant_memory(raw_description: str) -> Dict[str, Any]:
    """
    Checks the local SQLite merchant memory cache for an existing categorization rule.
    Returns the learned merchant details or {"found": False}.
    """
    match = db.lookup_merchant_memory(raw_description)
    if match:
        return {"found": True, "data": match}
    return {"found": False, "data": None}


@mcp_server.tool()
def save_merchant_memory(
    pattern: str,
    clean_merchant: str,
    category: str,
    subcategory: str,
    leaf_label: str = "",
    entities_json: str = "{}",
) -> Dict[str, Any]:
    """
    Learns and saves a recurring merchant rule to SQLite memory for future <1ms matching.
    """
    entities = json.loads(entities_json) if entities_json else {}
    db.save_merchant_memory(
        pattern=pattern,
        clean_merchant=clean_merchant,
        category=category,
        subcategory=subcategory,
        leaf_label=leaf_label or None,
        entities=entities,
    )
    return {
        "success": True,
        "message": f"Learned merchant pattern '{pattern}' as '{clean_merchant}'",
    }


@mcp_server.tool()
def reconcile_statement_balances(
    starting_balance: float,
    stated_ending_balance: float,
    total_credits: float,
    total_debits: float,
    line_items_net: float,
) -> Dict[str, Any]:
    """
    Deterministic mathematical reconciliation tool.
    Validates starting_balance + credits - debits against stated_ending_balance and extracted line items.
    """
    header_calculated_ending = round(starting_balance + total_credits - total_debits, 2)
    line_calculated_ending = round(starting_balance + line_items_net, 2)

    header_delta = round(stated_ending_balance - header_calculated_ending, 2)
    line_delta = round(stated_ending_balance - line_calculated_ending, 2)

    is_reconciled = abs(line_delta) < 0.01

    return {
        "is_reconciled": is_reconciled,
        "stated_ending_balance": stated_ending_balance,
        "line_calculated_ending": line_calculated_ending,
        "delta": line_delta,
        "header_delta": header_delta,
        "status": "reconciled" if is_reconciled else "unreconciled_delta",
    }


@mcp_server.tool()
def insert_transactions_batch(transactions_json: str, statement_id: str = "") -> Dict[str, Any]:
    """
    Persists a batch of normalized transactions into SQLite with automatic deduplication.
    """
    raw_list = json.loads(transactions_json)
    tx_objects = []
    for item in raw_list:
        tx_objects.append(
            Transaction(
                date=item["date"],
                raw_description=item["raw_description"],
                clean_merchant=item.get("clean_merchant", item["raw_description"]),
                amount=item["amount"],
                category=item.get("category", "Uncategorized"),
                subcategory=item.get("subcategory", "General"),
                leaf_label=item.get("leaf_label"),
                account_type=AccountType(item.get("account_type", "checking")),
                institution=item.get("institution", "Unknown"),
                confidence=item.get("confidence", 1.0),
                extracted_entities=item.get("extracted_entities", {}),
                raw_metadata=item.get("raw_metadata", {}),
            )
        )

    inserted, dupes = db.insert_transactions(tx_objects, statement_id=statement_id or None)
    return {
        "success": True,
        "inserted_count": inserted,
        "duplicate_count": dupes,
        "total_processed": len(tx_objects),
    }


@mcp_server.tool()
def query_spending_summary() -> Dict[str, Any]:
    """
    Queries total spending by category from the local SQLite database.
    """
    summary = db.get_spending_summary()
    return {"success": True, "category_totals": summary}


@mcp_server.tool()
def tag_transactions(tx_ids_json: str, tag: str) -> Dict[str, Any]:
    """
    Applies a user tag (e.g. 'California Trip', 'Streaming') to a list of transaction IDs.
    """
    tx_ids = json.loads(tx_ids_json)
    db.add_tag_to_transactions(tx_ids, tag)
    return {"success": True, "tagged_count": len(tx_ids), "tag": tag}


@mcp_server.tool()
def query_spending_by_tag(tag: str) -> Dict[str, Any]:
    """
    Calculates total spending across all transactions carrying a specific tag.
    """
    total = db.get_spending_by_tag(tag)
    return {"success": True, "tag": tag, "total_spend": total}
