"""
FastAPI Application for localfin.

Provides REST API endpoints for statement ingestion via LangGraph,
transaction queries, spending analytics, and tag management.
"""

from pathlib import Path
import shutil
import tempfile
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, status
from pydantic import BaseModel

from src.config import APP_DISPLAY_NAME, APP_DESCRIPTION
from src.mcp.db import DatabaseManager
from src.graph.workflow import build_financial_statement_graph
from src.models.schemas import Transaction, TransactionQuery

# Initialize FastAPI app with decoupled branding
app = FastAPI(title=APP_DISPLAY_NAME, description=APP_DESCRIPTION, version="1.0.0")

db = DatabaseManager()
graph = build_financial_statement_graph()


class IngestResponse(BaseModel):
    filename: str
    status: str
    total_transactions: int
    stated_ending_balance: Optional[float] = None
    calculated_ending_balance: Optional[float] = None
    delta: Optional[float] = None
    reflection_attempts: int
    errors: List[str] = []


class RenameTagRequest(BaseModel):
    old_tag: str
    new_tag: str


@app.get("/health", tags=["System"])
def health_check() -> Dict[str, str]:
    """Liveness probe for health and container monitoring."""
    return {"status": "healthy", "app": APP_DISPLAY_NAME}


@app.post("/api/statements/ingest", response_model=IngestResponse, tags=["Statements"])
def ingest_statement(file: UploadFile = File(...)) -> IngestResponse:
    """
    Ingests a bank/credit card PDF statement or CSV export.
    Executes the deterministic LangGraph pipeline: Ingest -> Extract -> Reconcile -> Enrich -> Persist.
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided.")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".pdf", ".csv"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{suffix}'. Only .pdf and .csv are supported.",
        )

    # Save to a temporary file for zero-egress processing
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_path = Path(tmp_file.name)
        shutil.copyfileobj(file.file, tmp_file)

    try:
        initial_state = {
            "file_path": str(tmp_path),
            "raw_content": "",
            "summary": None,
            "transactions": [],
            "reconciliation_result": None,
            "reflection_attempts": 0,
            "status": "in_progress",
            "errors": [],
        }

        result = graph.invoke(initial_state)

        summary = result.get("summary")
        recon = result.get("reconciliation_result") or {}
        txs = result.get("transactions", [])

        return IngestResponse(
            filename=file.filename,
            status=result.get("status", "unknown"),
            total_transactions=len(txs),
            stated_ending_balance=summary.stated_ending_balance if summary else None,
            calculated_ending_balance=recon.get("calculated_ending_balance"),
            delta=recon.get("delta"),
            reflection_attempts=result.get("reflection_attempts", 0),
            errors=result.get("errors", []),
        )
    finally:
        # Cleanup temporary file
        if tmp_path.exists():
            tmp_path.unlink()


@app.get("/api/transactions", response_model=List[Transaction], tags=["Transactions"])
def list_transactions(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    category: Optional[str] = Query(None, description="Category filter"),
    tag: Optional[str] = Query(None, description="Tag filter"),
    limit: int = Query(100, ge=1, le=1000),
) -> List[Transaction]:
    """Queries stored transactions with date, category, and tag filtering."""
    query = TransactionQuery(
        start_date=start_date, end_date=end_date, category=category, tag=tag, limit=limit
    )
    return db.get_transactions(query)


@app.get("/api/spending/summary", tags=["Analytics"])
def spending_by_category() -> Dict[str, float]:
    """Returns aggregated expenses grouped by financial category."""
    return db.get_spending_summary()


@app.get("/api/spending/by-tag", tags=["Analytics"])
def spending_by_tag(tag: str = Query(..., description="Tag name")) -> Dict[str, Any]:
    """Returns total expense spend for a specific tag."""
    total = db.get_spending_by_tag(tag)
    return {"tag": tag.lower(), "total_spend": total}


@app.post("/api/tags/rename", tags=["Tags"])
def rename_tag(request: RenameTagRequest) -> Dict[str, Any]:
    """Atomically renames a tag across all associated transactions."""
    success = db.rename_tag(old_name=request.old_tag, new_name=request.new_tag)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Tag '{request.old_tag}' not found."
        )
    return {"renamed": True, "old_tag": request.old_tag, "new_tag": request.new_tag}
