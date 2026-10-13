import pytest
from pathlib import Path
from src.models.schemas import Transaction
from src.mcp.db import DatabaseManager
from src.graph.enrichment import AdaptiveEnrichmentEngine, canonicalize_tags, extract_pattern_prefix


def test_tag_canonicalization():
    raw_tags = [" Groceries ", "FOOD!", "groceries", "Special-Event_2026", ""]
    clean = canonicalize_tags(raw_tags)
    assert clean == ["groceries", "food", "special-event_2026"]


def test_extract_pattern_prefix():
    desc1 = "POS DEBIT WHOLEFDS MKT #1024 AUSTIN TX"
    assert extract_pattern_prefix(desc1) == "\\bWHOLEFDS\\s+MKT\\b"

    desc2 = "CHECKCARD NETFLIX.COM CA"
    assert extract_pattern_prefix(desc2) == "\\bNETFLIX\\s+COM\\b"


def test_tier_1_memory_cache_hit(tmp_path: Path):
    db_file = tmp_path / "test_memory.db"
    db = DatabaseManager(db_path=db_file)
    engine = AdaptiveEnrichmentEngine(db=db)

    # Seed merchant memory
    db.save_merchant_memory(
        raw_pattern="\\bWHOLEFDS\\s+MKT\\b",
        normalized_name="Whole Foods Market",
        category="Groceries",
        subcategory="Supermarket",
        default_tags=["groceries", "organic"],
    )

    tx = Transaction(
        date="2026-03-15",
        raw_description="POS DEBIT WHOLEFDS MKT #1024",
        clean_merchant="UNKNOWN",
        amount=-84.20,
    )

    enriched = engine.enrich_transaction(tx, enable_llm=False)
    assert enriched.clean_merchant == "Whole Foods Market"
    assert enriched.category == "Groceries"
    assert enriched.raw_metadata["enrichment_tier"] == "tier_1_cache"
    assert any(t.name == "groceries" for t in enriched.tags)
    assert any(t.name == "organic" for t in enriched.tags)


def test_tier_3_autonomous_learning_loop(tmp_path: Path):
    db_file = tmp_path / "test_learn.db"
    db = DatabaseManager(db_path=db_file)
    engine = AdaptiveEnrichmentEngine(db=db)

    # First transaction: Not in memory, enriched via heuristic or LLM
    tx1 = Transaction(
        date="2026-03-20",
        raw_description="CHECKCARD TRADER JOES #512",
        clean_merchant="TRADER JOES",
        amount=-42.50,
    )

    enriched1 = engine.enrich_transaction(tx1, enable_llm=False)
    assert enriched1.category == "Groceries"
    # Verify Tier 3 automatically saved pattern to SQLite
    learned = db.lookup_merchant_memory("CHECKCARD TRADER JOES #512")
    assert learned is not None
    assert learned["clean_merchant"] == enriched1.clean_merchant

    # Second transaction next month: Should now hit Tier 1 cache!
    tx2 = Transaction(
        date="2026-04-20",
        raw_description="CHECKCARD TRADER JOES #999",
        clean_merchant="UNKNOWN",
        amount=-65.10,
    )
    enriched2 = engine.enrich_transaction(tx2, enable_llm=False)
    assert enriched2.raw_metadata["enrichment_tier"] == "tier_1_cache"
    assert enriched2.clean_merchant == enriched1.clean_merchant


@pytest.mark.asyncio
async def test_tier_2_live_qwen_ollama_extraction(tmp_path: Path):
    """Live integration test against local Qwen 2.5 7B on Ollama."""
    db_file = tmp_path / "test_qwen.db"
    db = DatabaseManager(db_path=db_file)
    engine = AdaptiveEnrichmentEngine(db=db)

    tx = Transaction(
        date="2026-03-22",
        raw_description="STARBUCKS STORE #14929 SEATTLE WA",
        clean_merchant="RAW_STARBUCKS",
        amount=-6.75,
    )

    enriched = engine.enrich_transaction(tx, enable_llm=True)
    assert "starbucks" in enriched.clean_merchant.lower()
    assert enriched.raw_metadata["enrichment_tier"] in ["tier_2_llm", "tier_fallback_heuristic"]
