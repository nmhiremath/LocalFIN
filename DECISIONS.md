# Architecture Decision Records (ADR) & Design Log

## ADR-001: Privacy Boundary & Zero-Egress Statement Ingestion
- **Context**: The user needs to process real bank/credit card statements (Chase, Discover, Citi, RocketMoney) without exposing private financial data (account numbers, balances, home addresses) to cloud LLMs or public GitHub.
- **Decision**:
  1. Real statements are stored outside the repository (e.g. `~/Documents/MyPrivateStatements/`).
  2. Input paths are accepted via CLI runtime flags (`--file`) or `.env`.
  3. Processing runs 100% on-device via local Python, local SQLite, and local Ollama (`qwen2.5:7b`).
  4. Repository includes only synthetic fixtures for CI/CD and open-source demonstration.

---

## ADR-002: Dual-Track Ingestion Strategy (PDFs + Aggregator CSVs)
- **Context**: The user has individual institution statements (PDF/CSV) as well as a unified RocketMoney aggregator export.
- **Decision**:
  1. Implement `BaseStatementParser` using the **Strategy Pattern**.
  2. **PDF Parser (`pdfplumber`)**: Used for institution statements to extract header ground truth (Beginning Balance, Ending Balance) and drive the LangGraph reflection loop.
  3. **CSV Parser**: Used for RocketMoney exports for fast bulk imports across all accounts.

---

## ADR-003: Immutable Raw Lake & Forward Re-enrichment
- **Context**: New analytical features (e.g. Geolocation spend mapping, merchant categorizations) will be added in future versions.
- **Decision**:
  1. Statements are stored verbatim in an immutable `raw_statements` table in SQLite.
  2. Transactions preserve 100% untouched `raw_description` and all original file columns in `raw_metadata`.
  3. Extracted attributes are stored in a dynamic `extracted_entities` JSON dictionary.
  4. Future features can backfill/re-enrich existing transactions without re-uploading statements.

---

## ADR-004: Adaptive Hybrid Pipeline (Learned Merchant Memory Cache)
- **Context**: 85–90% of monthly transactions follow recurring power-law patterns (Costco, Indian grocery, local gas, Amazon, utility bills). Running Ollama on every line item wastes compute and battery.
- **Decision**:
  1. **Tier 1 (Memory Cache)**: Query SQLite `merchant_memory` table. If pattern matches, resolve in $<1$ms with 100% deterministic accuracy.
  2. **Tier 2 (Ollama LLM Node)**: If cache miss, invoke local LLM to extract brand, category, and dynamic entities.
  3. **Learning Loop**: Write newly classified patterns into `merchant_memory` so future months resolve instantly.

---

## ADR-005: SQLModel for Unified Pydantic & Relational Persistence
- **Context**: Raw `sqlite3` string queries caused model duplication between Pydantic validation and SQL schemas, lack of compile-time query safety, and manual schema alteration technical debt.
- **Decision**:
  1. Adopt **SQLModel** (built on SQLAlchemy 2.0 and Pydantic v2).
  2. A single class defines both the FastAPI API contract and the SQLite table.
  3. M2M Tagging implemented natively via `TransactionTagLink` relationship.
  4. Type-safe query building using `select()`.

---

## ADR-006: Internal Engine Naming (`localfin`) Decoupled from Product Branding
- **Context**: The initial placeholder name "MoneyRAG" was inaccurate because the architecture is a deterministic statement ingestion and reconciliation engine with MCP tool calling, rather than vector retrieval-augmented generation (RAG).
- **Decision**:
  1. Adopt **`localfin`** as the permanent internal engine identity (package, SQLite files, telemetry, and default directories).
  2. Centralize configuration in [`src/config.py`](file:///Users/nmh/MoneyRAG/src/config.py) with dynamic `APP_DISPLAY_NAME` defaulting to "LocalFin", overridable via environment variables.
  3. Decouple future product re-branding from codebase refactoring: CLI titles, FastAPI docs, and UI surfaces consume configuration rather than hardcoded strings.

---

## ADR-007: Python 3.12 Runtime & Docker Base Image Standardization
- **Context**: Evaluating Python 3.12 vs. 3.13 for deployment and Docker containerization.
- **Decision**: Standardize on **Python 3.12-slim** across both local development and the production Docker image.
- **Rationale**:
  1. **Dev-to-Prod Parity (12-Factor App Factor X)**: Local development and testing are pinned to Python 3.12.15; matching the container runtime avoids subtle bytecode or runtime drift.
  2. **Pre-compiled Binary Wheels**: PDF parsing engines (like `pdfminer.six` and `pypdfium2` underneath `pdfplumber`) provide stable, pre-compiled C-extension binary wheels for Python 3.12. Python 3.13 requires source compilation on several platforms, substantially increasing Docker build times and image sizes.

---

## Project Milestones & Progress Tracker
- [x] **Milestone 1: Spec & Project Foundations** (`SPEC.md`, `DECISIONS.md`, Python 3.12 environment, Pydantic data contracts, test suite).
- [x] **Milestone 2: Tier-1 Ingestion Strategy** (`BaseStatementParser`, `CSVStatementParser`, unit tests).
- [x] **Milestone 3: SQLite Storage & FastMCP Server** (`raw_statements`, `transactions`, `merchant_memory`, FastMCP tools).
- [x] **Milestone 4: PDF Extraction & LangGraph Reflection Loop** (`pdfplumber`, balance reconciliation, circuit breaker).
- [x] **Milestone 6: FastAPI REST API, CLI, Docker Packaging, & Documentation** (FastAPI routes, CLI runner, Dockerfile, docker-compose, README.md, ADR-007).
