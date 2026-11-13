import json
from pathlib import Path
from typing import Generator
import pytest
import httpx

from cert_radar.db import Database
from cert_radar.models import Certification, VoucherEvent
from cert_radar.collector import (
    check_liveness,
    seed_initial_catalog,
    run_radar_collection,
)


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    db_file = tmp_path / "test_collector.db"
    database = Database(db_path=db_file)
    database.init_db()
    try:
        yield database
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Tests: seed_initial_catalog
# ---------------------------------------------------------------------------

def test_seed_initial_catalog_success(db: Database):
    """Loads default seed_catalog.json (20 certs), verifies db records and baseline_seed events."""
    count = seed_initial_catalog(db, "data/seed_catalog.json")
    assert count == 20

    certs = db.get_certifications()
    assert len(certs) == 20

    # Verify baseline_seed events recorded in voucher_events
    cursor = db.conn.cursor()
    cursor.execute("SELECT count(*) as total FROM voucher_events WHERE event_type = 'baseline_seed';")
    row = cursor.fetchone()
    assert row["total"] == 20

    # Spot check one cert
    ms_ai = db.get_certification("ms-ai-102")
    assert ms_ai is not None
    assert ms_ai.title == "Azure AI Engineer Associate"
    assert ms_ai.provider == "Microsoft"
    assert ms_ai.cost_type == "voucher_100"
    assert ms_ai.discount_pct == 100


def test_seed_initial_catalog_idempotency(db: Database):
    """Running seed_initial_catalog twice does not duplicate records or baseline_seed events."""
    count1 = seed_initial_catalog(db, "data/seed_catalog.json")
    assert count1 == 20

    # Second pass
    count2 = seed_initial_catalog(db, "data/seed_catalog.json")
    assert count2 == 20

    # Still exactly 20 certs
    certs = db.get_certifications()
    assert len(certs) == 20

    # Still exactly 20 baseline_seed events, no duplicates
    cursor = db.conn.cursor()
    cursor.execute("SELECT count(*) as total FROM voucher_events WHERE event_type = 'baseline_seed';")
    row = cursor.fetchone()
    assert row["total"] == 20


def test_seed_initial_catalog_file_not_found(db: Database):
    """Raises FileNotFoundError when seed file does not exist."""
    with pytest.raises(FileNotFoundError):
        seed_initial_catalog(db, "data/non_existent_seed.json")


def test_seed_initial_catalog_invalid_format(db: Database, tmp_path: Path):
    """Raises ValueError when seed JSON is not a list."""
    bad_json = tmp_path / "bad_seed.json"
    bad_json.write_text(json.dumps({"error": "not a list"}), encoding="utf-8")

    with pytest.raises(ValueError):
        seed_initial_catalog(db, bad_json)


# ---------------------------------------------------------------------------
# Tests: check_liveness
# ---------------------------------------------------------------------------

def test_check_liveness_live():
    """Status 200 with normal body returns ('live', 200)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Welcome to Microsoft Training</body></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://learn.microsoft.com/training", client=client)
    assert status == "live"
    assert code == 200


@pytest.mark.parametrize(
    "body_text",
    [
        "This challenge is now closed.",
        "Registration for this event is closed",
        "The voucher campaign is expired",
        "Registration ended on October 31",
        "This promotion is no longer available.",
        "EVENT EXPIRED AND CLOSED",
    ],
)
def test_check_liveness_expired(body_text: str):
    """Status 200 with termination phrases in body returns ('expired', 200)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<html><body>{body_text}</body></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://events.example.com/voucher", client=client)
    assert status == "expired"
    assert code == 200


def test_check_liveness_unverified_linkedin_403():
    """LinkedIn returning 403 returns ('unverified', 403)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://www.linkedin.com/posts/voucher-alert", client=client)
    assert status == "unverified"
    assert code == 403


def test_check_liveness_unverified_999():
    """Status 999 (LinkedIn anti-bot) returns ('unverified', 999)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(999, text="Request Denied")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://www.linkedin.com/feed", client=client)
    assert status == "unverified"
    assert code == 999


def test_check_liveness_unverified_auth_wall():
    """Known auth walls returning 403 return ('unverified', 403)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Login Required")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://login.microsoftonline.com/auth", client=client)
    assert status == "unverified"
    assert code == 403


@pytest.mark.parametrize("status_code", [400, 403, 404, 500, 503])
def test_check_liveness_dead(status_code: int):
    """Standard status >= 400 (non-auth wall) returns ('dead', status_code)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="Error")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://api.example.com/vouchers", client=client)
    assert status == "dead"
    assert code == status_code


def test_check_liveness_timeout_error():
    """Timeout exception returns ('error', None)."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Request timed out", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://slow.example.com", client=client)
    assert status == "error"
    assert code is None


def test_check_liveness_connect_error():
    """Connect error returns ('error', None)."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed to resolve host", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://unreachable.example.com", client=client)
    assert status == "error"
    assert code is None


def test_check_liveness_default_client(monkeypatch):
    """When client is None, instantiates httpx.Client and succeeds."""
    called_with_user_agent = False

    def mock_get(self, url, **kwargs):
        nonlocal called_with_user_agent
        ua = self.headers.get("User-Agent", "")
        if "CertRadar" in ua:
            called_with_user_agent = True
        return httpx.Response(200, text="Live page content")

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    status, code = check_liveness("https://example.com/test")
    assert status == "live"
    assert code == 200
    assert called_with_user_agent is True


# ---------------------------------------------------------------------------
# Tests: run_radar_collection
# ---------------------------------------------------------------------------

def test_run_radar_collection_real_sources(db: Database):
    """Executes radar collection using config/sources.yaml with seeded certs and a mock client."""
    seed_initial_catalog(db, "data/seed_catalog.json")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # All live except linux foundation
        url_str = str(request.url)
        if "linuxfoundation" in url_str:
            return httpx.Response(200, text="Registration for scholarships is closed.")
        return httpx.Response(200, text="Active vouchers available")

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))

    summary = run_radar_collection(
        db,
        sources_config="config/sources.yaml",
        client=mock_client,
    )

    assert summary["sources_checked"] == 7
    assert summary["certs_updated"] >= 7
    assert summary["events_recorded"] >= 1

    # ms-ai-102 should be live and active
    ms_ai = db.get_certification("ms-ai-102")
    assert ms_ai is not None
    assert ms_ai.liveness_status == "live"
    assert ms_ai.is_voucher_active is True
    assert ms_ai.last_checked_at is not None

    # finops-practitioner (from linuxfoundation) should be expired and inactive
    finops = db.get_certification("finops-practitioner")
    assert finops is not None
    assert finops.liveness_status == "expired"
    assert finops.is_voucher_active is False


def test_run_radar_collection_state_transitions(db: Database, tmp_path: Path):
    """Tests activated, deactivated, and liveness_changed state transitions."""
    # Create test cert initially inactive and unverified
    cert = Certification(
        id="test-trans-cert",
        title="Transition Test Cert",
        provider="TestProvider",
        track="official_voucher",
        cost_type="voucher_100",
        url="https://test.example.com/cert",
        is_voucher_active=False,
        activation_epoch=1,
        liveness_status="unverified",
    )
    db.upsert_certification(cert)

    test_sources = tmp_path / "test_sources.yaml"
    test_sources.write_text(
        """sources:
  - id: test-feed
    name: "Test Feed"
    url: "https://test.example.com/feed"
    track: "official_voucher"
    eligible_cert_ids: ["test-trans-cert"]
""",
        encoding="utf-8",
    )

    # Pass 1: Feed goes live -> triggers 'activated' and 'liveness_changed'
    def live_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Registration is open and vouchers available")

    client1 = httpx.Client(transport=httpx.MockTransport(live_handler))
    summary1 = run_radar_collection(db, sources_config=test_sources, client=client1)

    assert summary1["activated"] == 1
    assert summary1["liveness_changed"] == 1

    updated_cert = db.get_certification("test-trans-cert")
    assert updated_cert.is_voucher_active is True
    assert updated_cert.activation_epoch == 2
    assert updated_cert.liveness_status == "live"

    # Pass 2: Feed now returns expired -> triggers 'deactivated' and 'liveness_changed'
    def expired_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Challenge closed. No longer available.")

    client2 = httpx.Client(transport=httpx.MockTransport(expired_handler))
    summary2 = run_radar_collection(db, sources_config=test_sources, client=client2)

    assert summary2["deactivated"] == 1
    assert summary2["liveness_changed"] == 1

    expired_cert = db.get_certification("test-trans-cert")
    assert expired_cert.is_voucher_active is False
    assert expired_cert.activation_epoch == 2  # Not incremented on deactivation
    assert expired_cert.liveness_status == "expired"

    # Verify event logs in voucher_events
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT event_type FROM voucher_events WHERE cert_id = 'test-trans-cert' ORDER BY id ASC;"
    )
    events = [r["event_type"] for r in cursor.fetchall()]
    assert "liveness_changed" in events
    assert "activated" in events
    assert "deactivated" in events


def test_run_radar_collection_missing_config(db: Database):
    """Raises FileNotFoundError when sources_config file is missing."""
    with pytest.raises(FileNotFoundError):
        run_radar_collection(db, sources_config="non_existent_sources.yaml")


def test_run_radar_collection_non_existent_cert(db: Database, tmp_path: Path):
    """Gracefully handles sources with cert_ids not present in db."""
    test_sources = tmp_path / "missing_cert_sources.yaml"
    test_sources.write_text(
        """sources:
  - id: ghost-feed
    name: "Ghost Feed"
    url: "https://test.example.com/ghost"
    eligible_cert_ids: ["non-existent-id"]
""",
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="All good")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = run_radar_collection(db, sources_config=test_sources, client=client)
    assert summary["sources_checked"] == 1
    assert summary["certs_updated"] == 0


def test_check_liveness_accounts_google_auth_wall():
    """URL with okta.com returning 403 returns ('unverified', 403)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Auth required")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://corp.okta.com/login", client=client)
    assert status == "unverified"
    assert code == 403


def test_check_liveness_status_under_200():
    """Unusual informational status codes < 200 default to ('live', code)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(100, text="Continue")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    status, code = check_liveness("https://example.com/info", client=client)
    assert status == "live"
    assert code == 100


def test_run_radar_collection_invalid_yaml_structure(db: Database, tmp_path: Path):
    """Sources YAML with root that is not a dict returns 0 sources checked."""
    test_sources = tmp_path / "list_sources.yaml"
    test_sources.write_text("- item1\n- item2\n", encoding="utf-8")

    summary = run_radar_collection(db, sources_config=test_sources)
    assert summary["sources_checked"] == 0
    assert summary["certs_updated"] == 0


def test_run_radar_collection_source_without_url(db: Database, tmp_path: Path):
    """Source missing URL is skipped without error."""
    test_sources = tmp_path / "no_url_sources.yaml"
    test_sources.write_text(
        """sources:
  - id: no-url-source
    name: "No URL"
""",
        encoding="utf-8",
    )

    summary = run_radar_collection(db, sources_config=test_sources)
    assert summary["sources_checked"] == 1
    assert summary["certs_updated"] == 0


def test_run_radar_collection_unverified_and_error_handling(db: Database, tmp_path: Path):
    """Covers unverified and error status handling in run_radar_collection."""
    cert = Certification(
        id="error-test-cert",
        title="Error Test Cert",
        provider="TestProvider",
        track="free_continuous",
        cost_type="free",
        url="https://test.example.com/cert",
        is_voucher_active=True,
        activation_epoch=1,
        liveness_status="live",
    )
    db.upsert_certification(cert)

    # 1. Unverified pass: cert active status preserved, liveness becomes unverified
    test_sources_unverified = tmp_path / "unverified_sources.yaml"
    test_sources_unverified.write_text(
        """sources:
  - id: linkedin-feed
    name: "LinkedIn Feed"
    url: "https://www.linkedin.com/posts/test"
    track: "free_continuous"
    eligible_cert_ids: ["error-test-cert"]
""",
        encoding="utf-8",
    )

    def linkedin_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(999, text="Denied")

    client_unverified = httpx.Client(transport=httpx.MockTransport(linkedin_handler))
    summary_unverified = run_radar_collection(
        db, sources_config=test_sources_unverified, client=client_unverified
    )
    assert summary_unverified["liveness_changed"] == 1
    c1 = db.get_certification("error-test-cert")
    assert c1.liveness_status == "unverified"
    assert c1.is_voucher_active is True  # preserved

    # 2. Error pass (timeout): cert active preserved, liveness becomes error
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout", request=request)

    client_timeout = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    summary_error = run_radar_collection(
        db, sources_config=test_sources_unverified, client=client_timeout
    )
    assert summary_error["liveness_changed"] == 1
    c2 = db.get_certification("error-test-cert")
    assert c2.liveness_status == "error"
    assert c2.is_voucher_active is True  # preserved

