from pathlib import Path
from src.models.schemas import Transaction, StatementSummary, AccountType
from src.mcp.db import DatabaseManager


def test_database_deduplication_and_memory(tmp_path: Path):
    db_file = tmp_path / "test_moneyrag.db"
    db = DatabaseManager(db_path=db_file)

    # 1. Test Statement Insertion
    summary = StatementSummary(
        institution="Chase",
        account_number_masked="****1234",
        statement_period_start="2026-05-01",
        statement_period_end="2026-05-31",
        starting_balance=1000.0,
        total_credits=500.0,
        total_debits=200.0,
        stated_ending_balance=1300.0,
    )
    stmt_id = db.insert_raw_statement(
        summary, raw_content="Raw text dump here", filename="chase_may.pdf"
    )
    assert stmt_id == "Chase_2026-05-01_2026-05-31"

    # 2. Test Transaction Ingestion & Deduplication
    t1 = Transaction(
        date="2026-05-05",
        raw_description="COSTCO WHSE #1234 AUSTIN TX",
        clean_merchant="Costco Wholesale",
        amount=-150.00,
        category="Groceries",
        institution="Citi",
        account_type=AccountType.CREDIT_CARD,
    )
    t2 = Transaction(
        date="2026-05-06",
        raw_description="CHIPOTLE 1234 NYC",
        clean_merchant="Chipotle",
        amount=-15.50,
        category="Dining",
        institution="Citi",
        account_type=AccountType.CREDIT_CARD,
    )

    # First Insert: Both should be inserted
    inserted, dupes = db.insert_transactions([t1, t2], statement_id=stmt_id)
    assert inserted == 2
    assert dupes == 0

    # Second Insert (Exact same transactions): Should detect 2 duplicates and insert 0
    inserted_again, dupes_again = db.insert_transactions([t1, t2], statement_id=stmt_id)
    assert inserted_again == 0
    assert dupes_again == 2

    # 3. Test Merchant Memory Cache
    # Learn a pattern
    db.save_merchant_memory(
        pattern="COSTCO",
        clean_merchant="Costco Wholesale",
        category="Food & Dining",
        subcategory="Groceries",
        leaf_label="Costco",
        entities={"store_type": "Wholesale Club"},
    )

    # Lookup a raw string matching the pattern
    match = db.lookup_merchant_memory("COSTCO WHSE #5522 DALLAS TX")
    assert match is not None
    assert match["clean_merchant"] == "Costco Wholesale"
    assert match["category"] == "Food & Dining"
    assert match["entities"]["store_type"] == "Wholesale Club"

    # Unseen merchant should return None
    unseen = db.lookup_merchant_memory("UNKNOWN LOCAL BAKER")
    assert unseen is None

    # 4. Test Spending Summary
    summary = db.get_spending_summary()
    assert summary["Groceries"] == 150.00
    assert summary["Dining"] == 15.50

    # 5. Test Type-Safe Dynamic Querying (SQLModel)
    from src.models.schemas import TransactionQuery

    query = TransactionQuery(category="Groceries", min_amount=-200.0, max_amount=-100.0)
    filtered = db.get_transactions(query)
    assert len(filtered) == 1
    assert filtered[0].clean_merchant == "Costco Wholesale"
