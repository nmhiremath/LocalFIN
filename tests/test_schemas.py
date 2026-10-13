from src.models.schemas import Transaction, AccountType, StatementSummary


def test_transaction_deterministic_hash_deduplication():
    # Same transaction appearing from two different exports with same institution
    t1 = Transaction(
        date="2026-05-01",
        raw_description="COSTCO WHSE #1234 AUSTIN TX",
        clean_merchant="COSTCO WHOLESALE",
        amount=-142.50,
        institution="Citi",
        account_type=AccountType.CREDIT_CARD,
    )

    t2 = Transaction(
        date="2026-05-01",
        raw_description="COSTCO WHSE #1234",
        clean_merchant="COSTCO WHOLESALE",
        amount=-142.50,
        institution="Citi",
        account_type=AccountType.CREDIT_CARD,
    )

    # Hash ID must match deterministically
    assert t1.id == t2.id
    assert len(t1.id) == 16


def test_statement_summary_creation():
    summary = StatementSummary(
        institution="Chase",
        account_number_masked="****1234",
        statement_period_start="2026-04-01",
        statement_period_end="2026-04-30",
        starting_balance=1000.00,
        total_credits=2500.00,
        total_debits=1200.00,
        stated_ending_balance=2300.00,
    )
    assert summary.stated_ending_balance == 2300.00


def test_transaction_raw_preservation_and_metadata():
    raw_text = "COSTCO WHSE #1234 AUSTIN TX 05/01/26 998811"
    tx = Transaction(
        date="2026-05-01",
        raw_description=raw_text,
        clean_merchant="Costco Wholesale",
        extracted_entities={"store_id": "#1234", "location": "Austin, TX", "terminal": "998811"},
        amount=-142.50,
        institution="Citi",
        account_type=AccountType.CREDIT_CARD,
        raw_metadata={"original_category": "Merchandise"},
    )
    # Ensure raw text is 100% preserved
    assert tx.raw_description == raw_text
    assert tx.extracted_entities["store_id"] == "#1234"
    assert tx.extracted_entities["location"] == "Austin, TX"
    assert tx.raw_metadata["original_category"] == "Merchandise"
