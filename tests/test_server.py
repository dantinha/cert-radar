"""Tests for CertRadar HTTP server and API endpoints."""

import json
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Generator
from unittest.mock import patch

import httpx
import pytest

from cert_radar.db import Database
from cert_radar.models import CandidateProfile, Certification
from cert_radar.server import CertRadarRequestHandler, create_server, run_server


@pytest.fixture
def test_static_dir(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!DOCTYPE html><html><body>CertRadar SPA</body></html>", encoding="utf-8")
    (static / "style.css").write_text("body { background: #090A0F; }", encoding="utf-8")
    (static / "app.js").write_text("console.log('CertRadar');", encoding="utf-8")
    return static


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    db_file = tmp_path / "test_server.db"
    database = Database(db_path=db_file)
    database.init_db()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def sample_cert() -> Certification:
    return Certification(
        id="azure-ai-102",
        title="Azure AI Engineer Associate",
        provider="Microsoft",
        track="official_voucher",
        cost_type="voucher_100",
        discount_pct=100,
        normal_price_usd=165.0,
        exam_code="AI-102",
        target_roles=["AI Product Manager", "Context Engineer"],
        skills_covered=["Azure OpenAI", "Prompt Flow", "Cognitive Services"],
        level="associate",
        effort_hours=25,
        recruiter_signal=4,
        url="https://learn.microsoft.com/certifications/azure-ai-engineer/",
        voucher_program_url="https://learn.microsoft.com/challenges",
        is_voucher_active=True,
        activation_epoch=1,
        deadline_at="2026-12-31",
        liveness_status="live",
        source_kind="seed",
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        notes="Official challenge voucher",
    )


@pytest.fixture
def mock_candidate_profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Gabriel Dantas",
        email="gabriel@example.com",
        target_roles=["AI Product Manager", "Context Engineer"],
        primary_archetypes=["Context Engineer", "AI Product Manager"],
        known_skills=["Python", "FastAPI", "dbt", "Power BI", "SQL"],
        gaps=["Azure OpenAI", "Prompt Flow", "Vector Search"],
        existing_certifications=["CAPM"],
    )


@pytest.fixture
def live_server(
    db: Database, test_static_dir: Path, mock_candidate_profile: CandidateProfile
) -> Generator[str, None, None]:
    with patch("cert_radar.server.load_profile", return_value=mock_candidate_profile):
        server = create_server(db=db, host="127.0.0.1", port=0, static_dir=test_static_dir)
        assigned_port = server.server_address[1]
        base_url = f"http://127.0.0.1:{assigned_port}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        yield base_url

        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_get_profile(live_server: str):
    with httpx.Client(base_url=live_server) as client:
        res = client.get("/api/profile")
        assert res.status_code == 200
        data = res.json()
        assert data["full_name"] == "Gabriel Dantas"
        assert "AI Product Manager" in data["target_roles"]
        assert "Azure OpenAI" in data["gaps"]
        assert data["skills_count"] == 5
        assert data["gaps_count"] == 3


def test_get_certs_empty(live_server: str):
    with httpx.Client(base_url=live_server) as client:
        res = client.get("/api/certs")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) == 0


def test_get_certs_with_data_and_progress(live_server: str, db: Database, sample_cert: Certification):
    db.upsert_certification(sample_cert)
    db.set_user_progress(sample_cert.id, "saved", "Planejando estudo para dezembro")

    with httpx.Client(base_url=live_server) as client:
        res = client.get("/api/certs")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert item["id"] == "azure-ai-102"
        assert item["title"] == "Azure AI Engineer Associate"
        assert item["score"] > 0
        assert "score_breakdown" in item
        assert "role_score" in item["score_breakdown"]
        assert "gap_score" in item["score_breakdown"]
        assert item["user_progress"]["status"] == "saved"
        assert item["user_progress"]["user_notes"] == "Planejando estudo para dezembro"


def test_post_progress_success(live_server: str, db: Database, sample_cert: Certification):
    db.upsert_certification(sample_cert)

    with httpx.Client(base_url=live_server) as client:
        payload = {"cert_id": sample_cert.id, "status": "studying", "notes": "Capítulo 1 concluído"}
        res = client.post("/api/progress", json=payload)
        assert res.status_code == 200
        assert res.json() == {"success": True}

        progress = db.get_user_progress(sample_cert.id)
        assert progress is not None
        assert progress.status == "studying"
        assert progress.user_notes == "Capítulo 1 concluído"


def test_post_progress_validation_errors(live_server: str):
    with httpx.Client(base_url=live_server) as client:
        # Invalid JSON / bad content type
        res = client.post("/api/progress", content=b"invalid json", headers={"Content-Type": "application/json"})
        assert res.status_code == 400

        # Missing cert_id
        res = client.post("/api/progress", json={"status": "studying"})
        assert res.status_code == 400

        # Missing status
        res = client.post("/api/progress", json={"cert_id": "azure-ai-102"})
        assert res.status_code == 400

        # Invalid status value
        res = client.post("/api/progress", json={"cert_id": "azure-ai-102", "status": "invalid_status"})
        assert res.status_code == 400


def test_post_add_url_success(live_server: str, db: Database):
    with patch("cert_radar.server.check_liveness", return_value=("live", 200)):
        with httpx.Client(base_url=live_server) as client:
            payload = {
                "url": "https://learn.microsoft.com/credentials/applied-skills",
                "title": "Microsoft Applied Skills: Document Intelligence",
                "provider": "Microsoft",
                "track": "free_continuous",
                "cost_type": "free",
                "skills_covered": ["Azure AI Search", "Document OCR"],
            }
            res = client.post("/api/add-url", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["id"] == "microsoft-applied-skills-document-intelligence"
            assert data["title"] == "Microsoft Applied Skills: Document Intelligence"
            assert data["liveness_status"] == "live"

            # Check persistence in database
            cert_in_db = db.get_certification("microsoft-applied-skills-document-intelligence")
            assert cert_in_db is not None
            assert cert_in_db.provider == "Microsoft"


def test_post_add_url_validation_errors(live_server: str):
    with httpx.Client(base_url=live_server) as client:
        # Malformed JSON
        res = client.post("/api/add-url", content=b"{malformed", headers={"Content-Type": "application/json"})
        assert res.status_code == 400

        # Missing url
        res = client.post("/api/add-url", json={"title": "Some Cert"})
        assert res.status_code == 400

        # Missing title
        res = client.post("/api/add-url", json={"url": "https://example.com"})
        assert res.status_code == 400


def test_post_generate_snippet_success(live_server: str, db: Database, sample_cert: Certification):
    db.upsert_certification(sample_cert)

    with httpx.Client(base_url=live_server) as client:
        res = client.post("/api/generate-snippet", json={"cert_id": sample_cert.id})
        assert res.status_code == 200
        data = res.json()
        assert "cv_snippet" in data
        assert "obsidian_snippet" in data
        assert "Azure AI Engineer Associate" in data["cv_snippet"]
        assert "AI-102" in data["cv_snippet"]
        assert "Microsoft" in data["cv_snippet"]
        assert "[[CertRadar]]" in data["obsidian_snippet"]
        assert "Azure AI Engineer Associate" in data["obsidian_snippet"]


def test_post_generate_snippet_not_found_and_errors(live_server: str):
    with httpx.Client(base_url=live_server) as client:
        # Not found cert_id
        res = client.post("/api/generate-snippet", json={"cert_id": "nonexistent-cert-123"})
        assert res.status_code == 404

        # Missing cert_id
        res = client.post("/api/generate-snippet", json={})
        assert res.status_code == 400

        # Malformed JSON
        res = client.post("/api/generate-snippet", content=b"bad", headers={"Content-Type": "application/json"})
        assert res.status_code == 400


def test_static_files_serving(live_server: str):
    with httpx.Client(base_url=live_server) as client:
        # Root index.html
        res_root = client.get("/")
        assert res_root.status_code == 200
        assert "text/html" in res_root.headers.get("content-type", "")
        assert "CertRadar SPA" in res_root.text

        # Explicit /index.html
        res_idx = client.get("/index.html")
        assert res_idx.status_code == 200
        assert "CertRadar SPA" in res_idx.text

        # CSS
        res_css = client.get("/style.css")
        assert res_css.status_code == 200
        assert "text/css" in res_css.headers.get("content-type", "")
        assert "#090A0F" in res_css.text

        # JavaScript
        res_js = client.get("/app.js")
        assert res_js.status_code == 200
        assert any(ct in res_js.headers.get("content-type", "") for ct in ["javascript", "text/plain"])
        assert "CertRadar" in res_js.text

        # 404 static file
        res_404 = client.get("/not-found-asset.png")
        assert res_404.status_code == 404


def test_method_not_allowed_and_unknown_api(live_server: str):
    with httpx.Client(base_url=live_server) as client:
        # POST to GET-only /api/profile
        res = client.post("/api/profile", json={})
        assert res.status_code == 405

        # GET to POST-only /api/progress
        res = client.get("/api/progress")
        assert res.status_code == 405

        # Unknown /api route
        res = client.get("/api/unknown-endpoint")
        assert res.status_code == 404

        # PUT and DELETE
        res_put = client.put("/api/certs")
        assert res_put.status_code == 405
        res_del = client.delete("/api/certs")
        assert res_del.status_code == 405


def test_get_certs_hide_redundant_flag(live_server: str, db: Database, sample_cert: Certification):
    db.upsert_certification(sample_cert)
    with httpx.Client(base_url=live_server) as client:
        res = client.get("/api/certs?hide_redundant=true")
        assert res.status_code == 200
        assert isinstance(res.json(), list)


def test_server_error_branches(db: Database, test_static_dir: Path):
    # Server without db configured
    server = create_server(db=None, host="127.0.0.1", port=0, static_dir=test_static_dir)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with httpx.Client(base_url=url) as client:
            assert client.get("/api/certs").status_code == 500
            assert client.post("/api/progress", json={"cert_id": "c1", "status": "saved"}).status_code == 500
            assert client.post("/api/add-url", json={"url": "http://x.com", "title": "T"}).status_code == 500
            assert client.post("/api/generate-snippet", json={"cert_id": "c1"}).status_code == 500

            # Profile error handling
            with patch("cert_radar.server.load_profile", side_effect=RuntimeError("Profile error")):
                res_profile_err = client.get("/api/profile")
                assert res_profile_err.status_code == 500
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_handler_custom_db_property():
    class DummyServer:
        static_dir = None
        db = None

    handler = CertRadarRequestHandler.__new__(CertRadarRequestHandler)
    handler._custom_db = "custom_db"
    assert handler.db == "custom_db"

    handler._custom_db = None
    dummy_server = DummyServer()
    dummy_server.db = "server_db"
    handler.server = dummy_server
    assert handler.db == "server_db"


def test_default_static_files(live_server: str):
    # Test real static files shipped in src/cert_radar/static
    from cert_radar.server import DEFAULT_STATIC_DIR
    assert (DEFAULT_STATIC_DIR / "index.html").exists()
    assert (DEFAULT_STATIC_DIR / "style.css").exists()
    assert (DEFAULT_STATIC_DIR / "app.js").exists()

    index_content = (DEFAULT_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "CertRadar — Terminal Executivo" in index_content
    assert "app.js" in index_content
    assert "style.css" in index_content

    css_content = (DEFAULT_STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "--bg-base: #090A0F;" in css_content
    assert ".app-header" in css_content

    js_content = (DEFAULT_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "initApp" in js_content
    assert "/api/certs" in js_content


def test_run_server_invocation(db: Database, test_static_dir: Path):
    with patch("cert_radar.server.ThreadingHTTPServer") as mock_server_cls, \
         patch("cert_radar.server.webbrowser.open") as mock_webbrowser:
        mock_instance = mock_server_cls.return_value
        mock_instance.serve_forever.side_effect = KeyboardInterrupt()

        run_server(db=db, host="127.0.0.1", port=8999, open_browser=True, static_dir=test_static_dir)

        mock_server_cls.assert_called_once()
        mock_webbrowser.assert_called_once_with("http://127.0.0.1:8999")
        mock_instance.shutdown.assert_called_once()
        mock_instance.server_close.assert_called_once()


def test_post_open_url(live_server: str):
    with patch("cert_radar.server.webbrowser.open") as mock_open:
        with httpx.Client(base_url=live_server) as client:
            res = client.post("/api/open-url", json={"url": "https://learn.microsoft.com/ai-102"})
            assert res.status_code == 200
            assert res.json()["success"] is True
            mock_open.assert_called_once_with("https://learn.microsoft.com/ai-102", new=2)

            # Invalid scheme
            res_bad = client.post("/api/open-url", json={"url": "javascript:alert(1)"})
            assert res_bad.status_code == 400

            # Missing body
            res_empty = client.post("/api/open-url", content=b"not-json")
            assert res_empty.status_code == 400

