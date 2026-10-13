from pathlib import Path
from src.parsers.csv_parser import CSVStatementParser


def test_csv_parser_preserves_raw_and_extra_columns(tmp_path: Path):
    # Create a realistic sample CSV with extra metadata
    csv_content = """Date,Description,Amount,Category,Account Name,Memo
2026-05-01,COSTCO WHSE #1234 AUSTIN TX,-142.50,Groceries,Chase Sapphire,Weekend bulk run
2026-05-02,PAYROLL ACME CORP,3200.00,Income,Chase Checking,Direct Deposit
"""
    test_file = tmp_path / "sample_rocket_export.csv"
    test_file.write_text(csv_content, encoding="utf-8")

    parser = CSVStatementParser()
    assert parser.can_parse(test_file) is True

    raw_content, txs = parser.parse(test_file)
    assert len(raw_content) > 0
    assert len(txs) == 2

    # Check 1: Raw description is 100% intact
    assert txs[0].raw_description == "COSTCO WHSE #1234 AUSTIN TX"
    assert txs[0].amount == -142.50

    # Check 2: All unparsed columns are preserved in raw_metadata
    assert txs[0].raw_metadata["Category"] == "Groceries"
    assert txs[0].raw_metadata["Account Name"] == "Chase Sapphire"
    assert txs[0].raw_metadata["Memo"] == "Weekend bulk run"

    # Check 3: Income amount is positive
    assert txs[1].raw_description == "PAYROLL ACME CORP"
    assert txs[1].amount == 3200.00
