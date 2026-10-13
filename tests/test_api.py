import io
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "app" in data


def test_ingest_invalid_file_type():
    file_bytes = b"not a statement"
    response = client.post(
        "/api/statements/ingest",
        files={"file": ("malicious.exe", io.BytesIO(file_bytes), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Unsupported format" in response.json()["detail"]


def test_ingest_csv_and_query_endpoints():
    csv_content = (
        "Date,Description,Amount,Category\n"
        "2026-03-01,DIRECT DEP PAYROLL,3500.00,Income\n"
        "2026-03-05,WHOLEFDS MKT,-120.50,Groceries\n"
        "2026-03-10,NETFLIX.COM,-19.99,Subscriptions\n"
    ).encode("utf-8")

    # Ingest statement via API
    response = client.post(
        "/api/statements/ingest",
        files={"file": ("march_statement.csv", io.BytesIO(csv_content), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "march_statement.csv"
    assert data["total_transactions"] == 3
    assert data["status"] in ["reconciled", "needs_human_review", "in_progress"]

    # Query transactions endpoint
    tx_resp = client.get("/api/transactions?limit=10")
    assert tx_resp.status_code == 200
    txs = tx_resp.json()
    assert len(txs) >= 3

    # Query spending category summary endpoint
    summary_resp = client.get("/api/spending/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert isinstance(summary, dict)

    # Query spending by tag endpoint
    tag_resp = client.get("/api/spending/by-tag?tag=groceries")
    assert tag_resp.status_code == 200
    tag_data = tag_resp.json()
    assert tag_data["tag"] == "groceries"
    assert "total_spend" in tag_data


def test_rename_tag_endpoint():
    # Attempt to rename a nonexistent tag -> 404
    resp_404 = client.post(
        "/api/tags/rename", json={"old_tag": "nonexistent_tag_xyz", "new_tag": "some_other_tag"}
    )
    assert resp_404.status_code == 404
