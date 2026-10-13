# LocalFin — Agent & Developer Context

This document is the single source of truth for AI assistants and engineers working on this repository.

---

## 0. Streamlined Pair Programming & Tutoring Protocol
1. **Human 1-on-1 Tutor Style:** Keep explanations bite-sized (2–4 sentences max), conversational, and back-and-forth. Never dump unguided walls of code.
2. **One File at a Time:** Never create or edit more than ONE file in a single turn.
3. **Direct Action with Transparent Rationale:** Apply file edits directly in the turn while clearly explaining "the why" and the architectural rationale.
4. **Question Isolation:** If the user asks a question, answer the question ONLY. Do not write, modify, or run code in the same turn.
5. **Interview Coaching:** Highlight key trade-offs (e.g. `def` vs `async def` in FastAPI, Docker layer caching, 12-factor dev-to-prod parity).

---

## 1. Project Overview & Resume Item
- **Title:** Local-First Financial Statement & Transaction Intelligence Agent
- **Core Architecture:**
  - **Zero-Egress Privacy Boundary:** 100% on-device processing. No credentials, tokens, or financial line items ever leave the local machine.
  - **Deterministic Reconciliation Invariant:** Eliminates LLM math hallucinations. Mathematical checks ($Ending = Starting + Credits + Debits$) verify line items against statement headers with Python floating-point precision.
  - **Self-Healing LangGraph Reflection Loop:** Evaluates line items if a discrepancy is detected (e.g., flipping sign-inverted transactions) with a max-2 retry circuit breaker before flagging for human review.
  - **3-Tier Adaptive Intelligence Engine:**
    - Tier 1: Sub-millisecond (`<1ms`) SQLite regex memory cache lookup.
    - Tier 2: Local Ollama Qwen 2.5 7B structured entity extraction.
    - Tier 3: Autonomous self-learning loop auto-persisting new merchant patterns to SQLite.
  - **Modern Relational Ledger:** SQLModel (SQLAlchemy 2.0 + Pydantic v2) with Many-to-Many tagging and atomic renaming.
  - **Surface Layers:** Model Context Protocol (FastMCP) tools, FastAPI REST API, and terminal CLI.

---

## 2. Tech Stack & Environment
- **Python:** 3.12 (`localfin` conda environment)
- **Local LLM:** `qwen2.5:7b` via Ollama (`http://localhost:11434`)
- **Web API:** FastAPI & Uvicorn
- **Orchestration:** LangGraph & LangChain Core
- **Database / ORM:** SQLModel (SQLite)
- **PDF Extraction:** pdfplumber
- **Testing & Quality:** Pytest, Ruff, Pre-commit

---

## 3. Directory Layout
```
localfin/
├── AGENTS.md                  # LLM developer guide & invariants (this file)
├── SPEC.md                    # Formal system architecture specification
├── DECISIONS.md               # Architecture Decision Records (ADRs 001-007)
├── README.md                  # Portfolio project documentation
├── pyproject.toml             # Pytest & Ruff configurations
├── requirements.txt           # Lean production runtime dependencies
├── requirements-dev.txt       # Development & test tooling
├── .pre-commit-config.yaml    # Automated Git hooks (Ruff, Pytest, YAML)
├── Dockerfile                 # Production Python 3.12-slim image
├── docker-compose.yml         # Container service orchestration
├── src/
│   ├── config.py              # Centralized configuration & decoupled branding
│   ├── cli.py                 # Command line runner
│   ├── api/
│   │   └── main.py            # FastAPI REST routes
│   ├── graph/
│   │   ├── state.py           # LangGraph AgentState TypedDicts
│   │   ├── nodes.py           # State machine node implementations
│   │   ├── workflow.py        # Graph compilation & routing
│   │   └── enrichment.py      # 3-Tier Adaptive Intelligence Engine
│   ├── parsers/
│   │   ├── base.py            # BaseStatementParser strategy interface
│   │   ├── csv_parser.py      # Non-destructive CSV parser
│   │   └── pdf_parser.py      # Tabular & text extractor via pdfplumber
│   ├── models/
│   │   └── schemas.py         # Unified SQLModel classes & Pydantic contracts
│   └── mcp/
│       ├── db.py              # SQLModel database manager with M2M tagging
│       └── server.py          # FastMCP server exposing tools
└── tests/
    ├── test_api.py            # FastAPI REST integration tests
    ├── test_csv_parser.py     # Parser tests
    ├── test_db.py             # Database tests
    ├── test_enrichment.py     # 3-Tier engine & Ollama tests
    ├── test_graph.py          # LangGraph reflection tests
    ├── test_mcp_server.py     # FastMCP execution tests
    ├── test_schemas.py        # Schema contracts & fingerprint tests
    └── test_tags.py           # M2M tagging & atomic rename tests
```

---

## 4. Key Engineering Invariants
1. **Zero Cloud Egress:** Never send financial data or transaction text to third-party cloud APIs.
2. **Defensive Endpoint Threading:** Use standard `def` for synchronous endpoints (like heavy file ingestion and SQLite queries) so FastAPI executes them in an offloaded threadpool, preventing event loop blocking.
3. **Deterministic Balance Invariant:** Never trust an LLM to sum numbers. Line items must mathematically balance against statement headers.
4. **Tag Canonicalization:** All tags are stored lowercase, stripped of special characters, and deduplicated via junction tables.

---

## 5. Developer Quick Commands
```bash
# Run full test suite (23 tests)
pytest tests/ -v

# Run pre-commit linting & formatting checks across all files
pre-commit run --all-files

# Start FastAPI server
uvicorn src.api.main:app --reload --port 8000

# Run CLI ingest
python -m src.cli ingest <path-to-statement>

# Run Docker container
docker compose up --build
```
