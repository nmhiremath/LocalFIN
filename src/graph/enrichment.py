"""
Tiered Adaptive Enrichment Engine for localfin.

Implements the 3-Tier intelligence pattern:
- Tier 1: Sub-millisecond SQLite merchant_memory lookup (<1ms, 100% deterministic).
- Tier 2: Zero-egress local LLM (Qwen 2.5 7B via Ollama) structured entity extraction.
- Tier 3: Autonomous pattern learning into SQLite memory cache for subsequent statements.
"""

import re
import json
from typing import List, Optional
from pydantic import BaseModel, Field

from src.models.schemas import Transaction
from src.mcp.db import DatabaseManager
from src.config import OLLAMA_MODEL, OLLAMA_BASE_URL


class MerchantEnrichmentResult(BaseModel):
    """Structured extraction output from local LLM."""

    clean_merchant: str = Field(
        description="Normalized brand or merchant name, e.g. 'Whole Foods', 'Uber', 'Netflix'"
    )
    category: str = Field(
        description="High-level category, e.g. 'Groceries', 'Dining', 'Transportation', 'Subscriptions', 'Income'"
    )
    subcategory: str = Field(
        default="General",
        description="Detailed subcategory, e.g. 'Groceries', 'Rideshare', 'Streaming'",
    )
    tags: List[str] = Field(
        default_factory=list, description="Canonical lowercase tags, e.g. ['groceries', 'food']"
    )
    is_recurring: bool = Field(
        default=False,
        description="True if charge appears to be a recurring subscription or utility",
    )
    confidence: float = Field(default=0.9, description="Extraction confidence between 0.0 and 1.0")


def canonicalize_tags(tag_list: List[str]) -> List[str]:
    """Normalizes tags to lowercase, stripped, deduplicated format."""
    seen = set()
    canonical = []
    for t in tag_list:
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "", t.strip().lower())
        if clean and clean not in seen:
            seen.add(clean)
            canonical.append(clean)
    return canonical


def extract_pattern_prefix(raw_desc: str) -> str:
    """Generates a clean regex pattern for Tier 3 memory learning."""
    # Strip common noise prefixes
    cleaned = re.sub(
        r"^(?:POS\s+DEBIT|CHECKCARD|PURCHASE|RECURRING|DEBIT\s+CARD)\s*[-:]*\s*",
        "",
        raw_desc,
        flags=re.IGNORECASE,
    ).strip()
    # Extract first 2-3 prominent words
    words = re.findall(r"[A-Za-z0-9&]+", cleaned)
    if len(words) >= 2:
        return f"\\b{words[0]}\\s+{words[1]}\\b"
    elif len(words) == 1:
        return f"\\b{words[0]}\\b"
    return re.escape(raw_desc[:12])


class AdaptiveEnrichmentEngine:
    """Orchestrates Tier 1 memory lookup, Tier 2 Ollama extraction, and Tier 3 learning."""

    def __init__(
        self, db: DatabaseManager, model_name: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE_URL
    ):
        self.db = db
        self.model_name = model_name
        self.base_url = base_url
        self._llm = None

    def _get_llm(self):
        """Lazy initialization of LangChain Ollama model."""
        if self._llm is None:
            try:
                from langchain_ollama import ChatOllama

                self._llm = ChatOllama(
                    model=self.model_name, base_url=self.base_url, temperature=0.0
                )
            except Exception:
                self._llm = None
        return self._llm

    def enrich_transaction(self, tx: Transaction, enable_llm: bool = True) -> Transaction:
        """Enriches a single transaction through the 3-Tier intelligence pipeline."""
        raw_desc = tx.raw_description or ""

        # Tier 1: Instant Memory Cache (<1ms)
        memory = self.db.lookup_merchant_memory(raw_desc)
        if memory:
            clean_name = (
                memory.get("clean_merchant") if isinstance(memory, dict) else memory.clean_merchant
            )
            cat = memory.get("category") if isinstance(memory, dict) else memory.category
            subcat = (
                memory.get("subcategory", "General")
                if isinstance(memory, dict)
                else getattr(memory, "subcategory", "General")
            )
            tags = (
                (memory.get("tags") or memory.get("default_tags", []))
                if isinstance(memory, dict)
                else getattr(memory, "default_tags", [])
            )
            pat = memory.get("pattern") if isinstance(memory, dict) else memory.pattern

            tx.clean_merchant = clean_name
            tx.category = cat
            tx.subcategory = subcat
            tx.confidence = 1.0

            # Attach canonical memory tags
            for t in tags:
                tx.add_tag(t)

            raw_meta = dict(tx.raw_metadata or {})
            raw_meta["enrichment_tier"] = "tier_1_cache"
            raw_meta["memory_pattern"] = pat
            tx.raw_metadata = raw_meta
            return tx

        # Tier 2: Local Ollama LLM Extraction
        enrichment_data: Optional[MerchantEnrichmentResult] = None
        if enable_llm:
            enrichment_data = self._call_llm_extractor(tx)

        # Fallback heuristic if LLM disabled, unavailable, or failed
        if not enrichment_data:
            enrichment_data = self._heuristic_fallback(raw_desc)
            tier_used = "tier_fallback_heuristic"
        else:
            tier_used = "tier_2_llm"

        # Apply extracted attributes
        tx.clean_merchant = enrichment_data.clean_merchant
        tx.category = enrichment_data.category
        tx.subcategory = enrichment_data.subcategory
        tx.confidence = enrichment_data.confidence

        for t in canonicalize_tags(enrichment_data.tags):
            tx.add_tag(t)

        raw_meta = dict(tx.raw_metadata or {})
        raw_meta["enrichment_tier"] = tier_used
        raw_meta["is_recurring"] = enrichment_data.is_recurring
        tx.raw_metadata = raw_meta

        # Tier 3: Auto-Learning Loop
        # If successfully categorized with good confidence, save pattern into SQLite memory
        if enrichment_data.confidence >= 0.8 and raw_desc.strip():
            pattern = extract_pattern_prefix(raw_desc)
            try:
                self.db.save_merchant_memory(
                    raw_pattern=pattern,
                    normalized_name=enrichment_data.clean_merchant,
                    category=enrichment_data.category,
                    subcategory=enrichment_data.subcategory,
                    default_tags=canonicalize_tags(enrichment_data.tags),
                )
                raw_meta["learned_pattern"] = pattern
                tx.raw_metadata = raw_meta
            except Exception:
                pass  # Non-blocking if pattern already registered

        return tx

    def _call_llm_extractor(self, tx: Transaction) -> Optional[MerchantEnrichmentResult]:
        """Calls local Ollama with structured output prompt."""
        llm = self._get_llm()
        if not llm:
            return None

        prompt = (
            "You are a local financial transaction intelligence parser. "
            "Analyze this raw transaction line item and extract clean merchant brand, category, subcategory, and tags.\n\n"
            f"Raw Description: {tx.raw_description}\n"
            f"Amount: ${abs(tx.amount):.2f}\n"
            f"Date: {tx.date}\n\n"
            "Return a JSON object with keys: clean_merchant, category, subcategory, tags (list of strings), is_recurring (bool), confidence (float 0.0-1.0)."
        )

        try:
            structured_llm = llm.with_structured_output(MerchantEnrichmentResult)
            result = structured_llm.invoke(prompt)
            if isinstance(result, MerchantEnrichmentResult):
                return result
        except Exception:
            # Fallback to direct invoke and JSON parsing if with_structured_output unsupported
            try:
                response = llm.invoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                # Extract JSON block
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(0))
                    return MerchantEnrichmentResult(**data)
            except Exception:
                return None
        return None

    def _heuristic_fallback(self, raw_desc: str) -> MerchantEnrichmentResult:
        """Deterministic rule-based fallback when LLM is unavailable."""
        cleaned = re.sub(
            r"^(?:POS\s+DEBIT|CHECKCARD|PURCHASE|RECURRING|DEBIT\s+CARD)\s*[-:]*\s*",
            "",
            raw_desc,
            flags=re.IGNORECASE,
        )
        # Strip trailing store numbers / IDs (e.g. #1234, 12345, CA)
        cleaned = re.sub(r"#?\d{3,}.*$", "", cleaned).strip()
        cleaned = re.sub(r"\s+[A-Z]{2}\s*$", "", cleaned).strip()

        clean_name = cleaned.title() if cleaned else raw_desc[:20]

        # Basic keyword heuristics
        category = "Uncategorized"
        tags = []
        lower = raw_desc.lower()

        if any(w in lower for w in ["market", "grocery", "food", "trader", "whole"]):
            category = "Groceries"
            tags = ["groceries", "food"]
        elif any(w in lower for w in ["coffee", "starbucks", "cafe"]):
            category = "Dining"
            tags = ["coffee", "dining"]
        elif any(w in lower for w in ["uber", "lyft", "gas", "shell", "chevron"]):
            category = "Transportation"
            tags = ["transportation"]
        elif any(w in lower for w in ["netflix", "spotify", "hulu", "apple"]):
            category = "Subscriptions"
            tags = ["subscription", "entertainment"]

        conf = 0.85 if category != "Uncategorized" else 0.5

        return MerchantEnrichmentResult(
            clean_merchant=clean_name,
            category=category,
            subcategory="General",
            tags=tags,
            is_recurring=False,
            confidence=conf,
        )
