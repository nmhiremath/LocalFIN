from pathlib import Path
from src.mcp.db import DatabaseManager
from src.models.schemas import Transaction


def test_enterprise_m2m_tagging_and_renaming(tmp_path: Path):
    db_file = tmp_path / "test_m2m_tags.db"
    db = DatabaseManager(db_path=db_file)

    # 1. Ingest transactions with initial tags
    t1 = Transaction(
        date="2026-06-12",
        raw_description="SHELL OIL SAN FRANCISCO CA",
        clean_merchant="Shell Oil",
        amount=-45.00,
        category="Auto & Transport",
        subcategory="Gas",
        institution="Chase",
        tags=["California Trip"],
    )
    t2 = Transaction(
        date="2026-06-13",
        raw_description="IN-N-OUT BURGER SF CA",
        clean_merchant="In-N-Out",
        amount=-18.50,
        category="Food & Dining",
        subcategory="Restaurants",
        institution="Chase",
        tags=[],
    )
    db.insert_transactions([t1, t2])

    # 2. Add multiple tags to t2 via junction table
    db.add_tag_to_transactions([t2.id], tag_name="California Trip")
    db.add_tag_to_transactions([t2.id], tag_name="Roadtrip Dining")

    # Verify t2 has both tags
    t2_tags = db.get_tags_for_transaction(t2.id)
    assert "California Trip" in t2_tags
    assert "Roadtrip Dining" in t2_tags

    # 3. Sum total spend on "California Trip"
    # $45.00 + $18.50 = $63.50
    trip_total = db.get_spending_by_tag("California Trip")
    assert trip_total == 63.50

    # 4. Atomic Renaming Test: Rename "California Trip" -> "West Coast Vacation"
    renamed = db.rename_tag(old_name="California Trip", new_name="West Coast Vacation")
    assert renamed is True

    # Old tag name now has $0
    assert db.get_spending_by_tag("California Trip") == 0.0

    # New tag name has the exact $63.50 spend instantly!
    assert db.get_spending_by_tag("West Coast Vacation") == 63.50
    assert "West Coast Vacation" in db.get_tags_for_transaction(t2.id)

    # 5. Case-insensitivity test (Zero tag pollution)
    id1 = db.get_or_create_tag("Streaming")
    id2 = db.get_or_create_tag("STREAMING")
    id3 = db.get_or_create_tag("streaming")
    # All 3 variations map to the exact same tag record!
    assert id1 == id2 == id3
