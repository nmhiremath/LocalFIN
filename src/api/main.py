"""
FastAPI Application for localfin.

Provides REST API endpoints for statement ingestion via LangGraph,
transaction queries, spending analytics, and tag management.
"""

from pathlib import Path
import shutil
import tempfile
import uuid
from typing import List, Optional, Dict, Any, Tuple
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, status, BackgroundTasks
from pydantic import BaseModel

from src.config import APP_DISPLAY_NAME, APP_DESCRIPTION
from src.mcp.db import DatabaseManager
from src.graph.workflow import build_financial_statement_graph
from src.models.schemas import Transaction, TransactionQuery

# Initialize FastAPI app with decoupled branding
app = FastAPI(title=APP_DISPLAY_NAME, description=APP_DESCRIPTION, version="1.0.0")

db = DatabaseManager()
graph = build_financial_statement_graph()

# In-memory job registry for asynchronous batch tasks
jobs_db: Dict[str, Dict[str, Any]] = {}


class IngestResponse(BaseModel):
    filename: str
    status: str
    total_transactions: int
    stated_ending_balance: Optional[float] = None
    calculated_ending_balance: Optional[float] = None
    delta: Optional[float] = None
    reflection_attempts: int
    errors: List[str] = []


class BatchIngestResponse(BaseModel):
    total_files: int
    reconciled_files: int
    flagged_files: int
    total_transactions: int
    results: List[IngestResponse]


class BatchJobCreatedResponse(BaseModel):
    job_id: str
    status: str
    total_files: int
    message: str


class BatchJobStatusResponse(BaseModel):
    job_id: str
    status: str
    total_files: int
    processed_files: int
    result: Optional[BatchIngestResponse] = None
    error: Optional[str] = None


class RenameTagRequest(BaseModel):
    old_tag: str
    new_tag: str


def _process_single_statement(file: UploadFile) -> IngestResponse:
    """Helper to execute the LangGraph pipeline for a single statement upload."""
    if not file.filename:
        return IngestResponse(
            filename="unknown",
            status="error",
            total_transactions=0,
            reflection_attempts=0,
            errors=["No filename provided."],
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".pdf", ".csv"]:
        return IngestResponse(
            filename=file.filename,
            status="error",
            total_transactions=0,
            reflection_attempts=0,
            errors=[f"Unsupported format '{suffix}'. Only .pdf and .csv are supported."],
        )

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
        if tmp_path.exists():
            tmp_path.unlink()


def _run_batch_ingest_job(job_id: str, file_records: List[Tuple[str, Path]]) -> None:
    """
    Background worker task executing LangGraph pipeline across batch files.
    file_records contains tuples of (original_filename, temp_path).
    """
    jobs_db[job_id]["status"] = "in_progress"
    results: List[IngestResponse] = []
    reconciled_count = 0
    flagged_count = 0
    total_txs = 0

    try:
        for filename, tmp_path in file_records:
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
                res_graph = graph.invoke(initial_state)
                summary = res_graph.get("summary")
                recon = res_graph.get("reconciliation_result") or {}
                txs = res_graph.get("transactions", [])
                st = res_graph.get("status", "unknown")

                ingest_res = IngestResponse(
                    filename=filename,
                    status=st,
                    total_transactions=len(txs),
                    stated_ending_balance=summary.stated_ending_balance if summary else None,
                    calculated_ending_balance=recon.get("calculated_ending_balance"),
                    delta=recon.get("delta"),
                    reflection_attempts=res_graph.get("reflection_attempts", 0),
                    errors=res_graph.get("errors", []),
                )
            except Exception as e:
                ingest_res = IngestResponse(
                    filename=filename,
                    status="error",
                    total_transactions=0,
                    reflection_attempts=0,
                    errors=[str(e)],
                )

            results.append(ingest_res)
            if ingest_res.status in ["reconciled", "completed"]:
                reconciled_count += 1
            elif ingest_res.status in ["needs_human_review", "flagged", "error", "failed"]:
                flagged_count += 1
            total_txs += ingest_res.total_transactions
            jobs_db[job_id]["processed_files"] += 1

        batch_res = BatchIngestResponse(
            total_files=len(file_records),
            reconciled_files=reconciled_count,
            flagged_files=flagged_count,
            total_transactions=total_txs,
            results=results,
        )
        jobs_db[job_id]["status"] = "completed"
        jobs_db[job_id]["result"] = batch_res
    except Exception as ex:
        jobs_db[job_id]["status"] = "failed"
        jobs_db[job_id]["error"] = str(ex)
    finally:
        for _, tmp_path in file_records:
            if tmp_path.exists():
                tmp_path.unlink()


@app.get("/health", tags=["System"])
def health_check() -> Dict[str, str]:
    """Liveness probe for health and container monitoring."""
    return {"status": "healthy", "app": APP_DISPLAY_NAME}


@app.post("/api/statements/ingest", response_model=IngestResponse, tags=["Statements"])
def ingest_statement(file: UploadFile = File(...)) -> IngestResponse:
    """
    Ingests a single bank/credit card PDF statement or CSV export.
    Executes the deterministic LangGraph pipeline: Ingest -> Extract -> Reconcile -> Enrich -> Persist.
    """
    res = _process_single_statement(file)
    if res.status == "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.errors[0] if res.errors else "Ingestion failed.",
        )
    return res


@app.post(
    "/api/statements/ingest-batch",
    response_model=BatchJobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Statements"],
)
def ingest_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
) -> BatchJobCreatedResponse:
    """
    Asynchronously ingests a batch of statements (PDF or CSV) in one multipart request.
    Returns HTTP 202 with a job_id for decoupled polling.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one statement file must be provided.",
        )

    job_id = str(uuid.uuid4())
    file_records: List[Tuple[str, Path]] = []

    # Persist uploads to temp files synchronously before returning HTTP 202
    for file in files:
        filename = file.filename or "unknown"
        suffix = Path(filename).suffix.lower() or ".tmp"
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        shutil.copyfileobj(file.file, tmp_file)
        tmp_file.close()
        file_records.append((filename, Path(tmp_file.name)))

    jobs_db[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "total_files": len(files),
        "processed_files": 0,
        "result": None,
        "error": None,
    }

    background_tasks.add_task(_run_batch_ingest_job, job_id, file_records)

    return BatchJobCreatedResponse(
        job_id=job_id,
        status="pending",
        total_files=len(files),
        message="Batch ingestion job scheduled. Poll /api/jobs/{job_id} for progress.",
    )


@app.get("/api/jobs/{job_id}", response_model=BatchJobStatusResponse, tags=["Jobs"])
def get_job_status(job_id: str) -> BatchJobStatusResponse:
    """Checks the progress and results of an asynchronous batch ingestion job."""
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    return BatchJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        total_files=job["total_files"],
        processed_files=job["processed_files"],
        result=job.get("result"),
        error=job.get("error"),
    )


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
