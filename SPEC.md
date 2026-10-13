# MoneyRAG: Local-First Financial Statement & Transaction Intelligence Agent
## System Architecture Specification (SPEC-001)

### 1. Overview & Core Philosophy
MoneyRAG is a privacy-first, on-device financial intelligence system. It automates the extraction, schema validation, and balance reconciliation of digital bank/credit card PDF statements and CSV exports using a local LangGraph state machine, local LLMs via Ollama, and Model Context Protocol (MCP) conventions with zero external cloud egress.

---

### 2. High-Level Architecture Flow

```
[Statement PDF / CSV]
        │
        ▼
[pdfplumber / Tabular Extractor]
        │
        ▼ (Raw text & tables)
[LangGraph Extraction Node] ──(Ollama: Qwen 2.5 7B / Mock LLM)
        │
        ▼ (Structured Rows: Pydantic)
[LangGraph Reconciliation Node] ──(Deterministic Python Math)
        │
   ┌────┴──────────────────────────┐
   │                               │
[Balanced: Delta == 0]     [Discrepancy: Delta != 0]
   │                               │
   ▼                               ▼
[MCP Persistence Node]      [Reflection Loop (Max 2 Attempts)]
   │                               │
   ▼                               ▼
[SQLite Storage]           [Flag: Needs Human Review]
```

---

### 3. Data Contracts (Pydantic Schemas)

#### 3.1 Transaction Model
```python
class Transaction(BaseModel):
    id: str  # Deterministic hash: sha256(date + merchant + amount + account)
    date: str  # YYYY-MM-DD
    raw_description: str
    clean_merchant: str
    amount: float  # Negative for debits/expenses, positive for deposits/credits
    category: str  # e.g., "Food & Dining"
    subcategory: str  # e.g., "Groceries"
    leaf_label: str | None  # e.g., "Costco", "Trader Joe's"
    account_type: str  # "checking", "credit_card", "brokerage", "savings"
    institution: str  # "Chase", "Discover", "Citi", "RocketMoney"
    confidence: float  # 0.0 to 1.0
```

#### 3.2 Statement Summary (Header Ground Truth)
```python
class StatementSummary(BaseModel):
    institution: str
    account_number_masked: str
    statement_period_start: str
    statement_period_end: str
    starting_balance: float
    total_deposits_credits: float
    total_withdrawals_debits: float
    ending_balance: float
```

#### 3.3 Reconciliation Invariant
Deterministic formula evaluated in pure Python:
$$\Delta = \text{Ending Balance} - (\text{Starting Balance} + \text{Total Credits} - \text{Total Debits})$$

* If $|\Delta| < 0.01$: **STATUS = RECONCILED**
* If $|\Delta| \ge 0.01$: **STATUS = UNRECONCILED** $\to$ Route to Reflection Loop

---

### 4. LangGraph Multi-Stage State Graph

#### Graph State (`AgentState`)
```python
class AgentState(TypedDict):
    file_path: str
    raw_content: str
    extracted_summary: StatementSummary | None
    extracted_transactions: list[Transaction]
    reconciliation_delta: float
    reflection_attempts: int
    is_reconciled: bool
    review_reasons: list[str]
```

#### Graph Nodes:
1. `ingest_document`: Loads text and tables using `pdfplumber` or CSV parsers.
2. `extract_statement_summary`: Extracts starting balance, ending balance, totals.
3. `extract_transactions`: Parses tabular rows into structured `Transaction` objects.
4. `reconcile_balances`: Deterministically checks mathematical invariants.
5. `reflect_and_correct`: Re-evaluates ambiguous line items if delta exists (max 2 retries).
6. `persist_to_mcp`: Calls FastMCP SQLite tools to persist verified transactions.

---

### 5. Model Context Protocol (MCP) Interface
A standalone FastMCP server (`src/mcp/server.py`) exposing standard tools:
* `insert_transactions(batch: list[dict]) -> dict`
* `reconcile_statement(statement_id: str) -> dict`
* `query_spending_by_category(start_date: str, end_date: str) -> dict`
* `deduplicate_records() -> dict`

---

### 6. Verification & Evals
* **Unit Tests**: 100% offline tests using `MockLLM` fixture.
* **Deterministic Evals**: Benchmark against synthetic Chase, Discover, Citi, and RocketMoney statements to guarantee 0% math hallucination.

---

### 7. Runtime Environment & Container Packaging
* **Python Runtime**: Pinned to **Python 3.12** (`python:3.12-slim` base image) for strict dev-to-prod parity.
* **C-Extension Wheels**: Standardized on 3.12 to leverage stable pre-compiled wheels for binary PDF engines (`pypdfium2`, `pdfminer.six`).
* **Container Bridge**: Docker container bridges to host-level Ollama via `host.docker.internal:11434` for zero-egress LLM inference.
