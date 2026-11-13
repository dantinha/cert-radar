"""Unit tests for the notification service (Windows Toast + Telegram) and deduplication."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import httpx
import pytest

from cert_radar.db import Database
from cert_radar.models import Certification
from cert_radar.matcher import MatchResult
from cert_radar.notifier import (
    build_alert_message,
    dispatch_alerts,
    generate_dedup_key,
    send_telegram_alert,
    send_windows_toast,
)


@pytest.fixture
def in_memory_db() -> Database:
    """Provides a clean in-memory database with tables initialized."""
    db = Database(":memory:")
    db.init_db()
    return db


@pytest.fixture
def sample_cert() -> Certification:
    """Provides a sample active certification."""
    return Certification(
        id="aws-certified-ai-practitioner",
        title="AWS Certified AI Practitioner",
        provider="AWS",
        track="official_voucher",
        cost_type="voucher_100",
        discount_pct=100,
        normal_price_usd=100.0,
        exam_code="AIF-C01",
        target_roles=["AI Engineer", "Cloud Architect"],
        skills_covered=["Generative AI", "Bedrock", "SageMaker"],
        level="foundational",
        effort_hours=20,
        recruiter_signal=4,
        url="https://aws.amazon.com/certification/certified-ai-practitioner/",
        voucher_program_url="https://pages.awscloud.com/ai-challenge.html",
        is_voucher_active=True,
        activation_epoch=1,
        deadline_at="2026-11-20T23:59:59Z",
        liveness_status="live",
        source_kind="seed",
        notes="Free voucher upon completing the cloud quest.",
    )


@pytest.fixture
def sample_match(sample_cert: Certification) -> MatchResult:
    """Provides a matching MatchResult."""
    return MatchResult(
        cert_id=sample_cert.id,
        score=85,
        role_score=30,
        gap_score=20,
        signal_score=15,
        cost_score=20,
        match_reasons=[
            "High career alignment with target AI roles",
            "Closes gaps in Generative AI",
            "100% discount active campaign",
        ],
    )


# ==========================================
# 1. Dedup Key Tests
# ==========================================

def test_generate_dedup_key_basic():
    key = generate_dedup_key(
        cert_id="aws-ai",
        alert_type="new_voucher",
        activation_epoch=1,
        deadline_at="2026-12-31",
        channel="telegram",
    )
    assert key == "aws-ai:new_voucher:1:2026-12-31:telegram"


def test_generate_dedup_key_none_deadline():
    key = generate_dedup_key(
        cert_id="nvidia-generative-ai",
        alert_type="expiring_48h",
        activation_epoch=2,
        deadline_at=None,
        channel="windows",
    )
    assert key == "nvidia-generative-ai:expiring_48h:2:none:windows"


def test_generate_dedup_key_empty_deadline():
    key = generate_dedup_key(
        cert_id="nvidia-generative-ai",
        alert_type="expiring_48h",
        activation_epoch=2,
        deadline_at="",
        channel="windows",
    )
    assert key == "nvidia-generative-ai:expiring_48h:2:none:windows"


def test_generate_dedup_key_channel_and_epoch_variance():
    key_win = generate_dedup_key("cert-1", "new_voucher", 1, "2026-10-10", "windows")
    key_tg = generate_dedup_key("cert-1", "new_voucher", 1, "2026-10-10", "telegram")
    key_epoch2 = generate_dedup_key("cert-1", "new_voucher", 2, "2026-10-10", "windows")

    assert key_win != key_tg
    assert key_win != key_epoch2


# ==========================================
# 2. Message Builder Tests
# ==========================================

def test_build_alert_message_expiring_48h(sample_cert: Certification, sample_match: MatchResult):
    msg = build_alert_message(sample_cert, sample_match, alert_type="expiring_48h")
    assert "EXPIRA EM 48H" in msg
    assert sample_cert.title in msg
    assert sample_cert.provider in msg
    assert "AIF-C01" in msg
    assert "100% Grátis" in msg
    assert "Fit Score" in msg
    assert "85/100" in msg
    assert sample_cert.voucher_program_url in msg


def test_build_alert_message_expiring_7d(sample_cert: Certification, sample_match: MatchResult):
    msg = build_alert_message(sample_cert, sample_match, alert_type="expiring_7d")
    assert "7 DIAS" in msg
    assert sample_cert.title in msg


def test_build_alert_message_new_voucher(sample_cert: Certification, sample_match: MatchResult):
    msg = build_alert_message(sample_cert, sample_match, alert_type="new_voucher")
    assert "NOVA OPORTUNIDADE" in msg
    assert sample_cert.title in msg


def test_build_alert_message_discount_voucher(sample_cert: Certification, sample_match: MatchResult):
    sample_cert.cost_type = "voucher_discount"
    sample_cert.discount_pct = 50
    sample_cert.normal_price_usd = 200.0
    sample_cert.voucher_program_url = None  # test fallback to url

    msg = build_alert_message(sample_cert, sample_match, alert_type="new_voucher")
    assert "50% OFF" in msg
    assert "$200" in msg
    assert sample_cert.url in msg


def test_build_alert_message_free_continuous(sample_cert: Certification, sample_match: MatchResult):
    sample_cert.cost_type = "free"
    msg = build_alert_message(sample_cert, sample_match, alert_type="new_voucher")
    assert "Acesso Gratuito Contínuo" in msg


def test_build_alert_message_scholarship(sample_cert: Certification, sample_match: MatchResult):
    sample_cert.cost_type = "scholarship"
    msg = build_alert_message(sample_cert, sample_match, alert_type="new_voucher")
    assert "Bolsa de Estudos" in msg


# ==========================================
# 3. Telegram Dispatch Tests
# ==========================================

def test_send_telegram_alert_missing_credentials():
    assert not send_telegram_alert(token="", chat_id="12345", message="Hello")
    assert not send_telegram_alert(token="tok", chat_id="", message="Hello")


def test_send_telegram_alert_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.telegram.org/bot123456:ABC/sendMessage"
        assert b"chat_id" in request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        success = send_telegram_alert(
            token="123456:ABC",
            chat_id="987654321",
            message="Test message",
            client=client,
        )
        assert success is True


def test_send_telegram_alert_api_error_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        success = send_telegram_alert(
            token="123456:ABC",
            chat_id="invalid_chat",
            message="Test message",
            client=client,
        )
        assert success is False


def test_send_telegram_alert_status_200_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        success = send_telegram_alert(
            token="123456:ABC",
            chat_id="some_chat",
            message="Test message",
            client=client,
        )
        assert success is False


def test_send_telegram_alert_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        success = send_telegram_alert(
            token="123456:ABC",
            chat_id="chat",
            message="Test message",
            client=client,
        )
        assert success is False


def test_send_telegram_alert_timeout_and_network_errors():
    def timeout_handler(request: httpx.Request):
        raise httpx.TimeoutException("Connection timed out")

    transport = httpx.MockTransport(timeout_handler)
    with httpx.Client(transport=transport) as client:
        assert send_telegram_alert("tok", "chat", "msg", client=client) is False


def test_send_telegram_alert_default_client():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_post.return_value = mock_response

        res = send_telegram_alert("tok", "chat", "msg")
        assert res is True
        mock_post.assert_called_once()


# ==========================================
# 4. Windows Toast Tests
# ==========================================

def test_send_windows_toast_winotify_success():
    mock_notification = MagicMock()
    with patch.dict("sys.modules", {"winotify": MagicMock(Notification=MagicMock(return_value=mock_notification))}):
        success = send_windows_toast(
            title="Title",
            message="Message with *markdown*",
            url="https://example.com",
        )
        assert success is True
        mock_notification.show.assert_called_once()


def test_send_windows_toast_winotify_error_fallback_to_powershell_success():
    mock_notification = MagicMock()
    mock_notification.show.side_effect = RuntimeError("winotify failed")

    with patch.dict("sys.modules", {"winotify": MagicMock(Notification=MagicMock(return_value=mock_notification))}), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        success = send_windows_toast("Title", "Message", "https://example.com")
        assert success is True
        mock_run.assert_called_once()


def test_send_windows_toast_without_winotify_powershell_success():
    # Simulate winotify not installed
    with patch.dict("sys.modules", {"winotify": None}), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        success = send_windows_toast("Title", "Message", "https://example.com")
        assert success is True
        mock_run.assert_called_once()


def test_send_windows_toast_powershell_failure():
    with patch.dict("sys.modules", {"winotify": None}), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)

        success = send_windows_toast("Title", "Message", "https://example.com")
        assert success is False


def test_send_windows_toast_powershell_exception():
    with patch.dict("sys.modules", {"winotify": None}), \
         patch("subprocess.run", side_effect=FileNotFoundError("powershell not found")):

        success = send_windows_toast("Title", "Message", "https://example.com")
        assert success is False


# ==========================================
# 5. Dispatch Alerts & Deduplication Tests
# ==========================================

def test_dispatch_alerts_filters(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    in_memory_db.upsert_certification(sample_cert)

    # Inactive voucher -> skipped
    sample_cert.is_voucher_active = False
    res = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], enable_windows=False)
    assert res == {"windows_sent": 0, "telegram_sent": 0, "skipped_dedup": 0}

    # Unverified / not live -> skipped
    sample_cert.is_voucher_active = True
    sample_cert.liveness_status = "unverified"
    res = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], enable_windows=False)
    assert res == {"windows_sent": 0, "telegram_sent": 0, "skipped_dedup": 0}

    # Score below threshold (e.g. 50 < 65) and not saved -> skipped
    sample_cert.liveness_status = "live"
    sample_match.score = 50
    res = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], min_score=65, enable_windows=False)
    assert res == {"windows_sent": 0, "telegram_sent": 0, "skipped_dedup": 0}

    # Score below threshold BUT user has 'saved' it in progress -> included!
    in_memory_db.set_user_progress(sample_cert.id, status="saved")
    with patch("cert_radar.notifier.send_windows_toast", return_value=True):
        res = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], min_score=65, enable_windows=True)
        assert res["windows_sent"] == 1
        assert res["skipped_dedup"] == 0


def test_dispatch_alerts_deadline_classification(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    in_memory_db.upsert_certification(sample_cert)
    ref_time = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Deadline within 24h (< 48h)
    sample_cert.deadline_at = "2026-11-11T10:00:00Z"
    with patch("cert_radar.notifier.send_windows_toast", return_value=True) as mock_toast:
        res = dispatch_alerts(
            in_memory_db,
            [(sample_cert, sample_match)],
            reference_date=ref_time,
            enable_windows=True,
        )
        assert res["windows_sent"] == 1
        # Check that message contains 48H alert marker
        args = mock_toast.call_args[0]
        assert "48H" in args[1]

    # Verify dedup prevents second send
    with patch("cert_radar.notifier.send_windows_toast", return_value=True) as mock_toast:
        res2 = dispatch_alerts(
            in_memory_db,
            [(sample_cert, sample_match)],
            reference_date=ref_time,
            enable_windows=True,
        )
        assert res2["windows_sent"] == 0
        assert res2["skipped_dedup"] == 1
        mock_toast.assert_not_called()


def test_dispatch_alerts_expiring_7d_and_new_voucher(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    in_memory_db.upsert_certification(sample_cert)
    ref_time = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)

    # Deadline 4 days ahead -> expiring_7d
    sample_cert.deadline_at = "2026-11-14T12:00:00Z"
    with patch("cert_radar.notifier.send_windows_toast", return_value=True) as mock_toast:
        res = dispatch_alerts(
            in_memory_db,
            [(sample_cert, sample_match)],
            reference_date=ref_time,
            enable_windows=True,
        )
        assert res["windows_sent"] == 1
        args = mock_toast.call_args[0]
        assert "7 DIAS" in args[1]

    # Deadline 20 days ahead -> new_voucher
    sample_cert.id = "cert-future"
    sample_cert.deadline_at = "2026-11-30T12:00:00Z"
    sample_match.cert_id = "cert-future"
    in_memory_db.upsert_certification(sample_cert)

    with patch("cert_radar.notifier.send_windows_toast", return_value=True) as mock_toast:
        res = dispatch_alerts(
            in_memory_db,
            [(sample_cert, sample_match)],
            reference_date=ref_time,
            enable_windows=True,
        )
        assert res["windows_sent"] == 1
        args = mock_toast.call_args[0]
        assert "NOVA OPORTUNIDADE" in args[1]


def test_dispatch_alerts_multi_channel_with_telegram(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    in_memory_db.upsert_certification(sample_cert)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as tg_client, \
         patch("cert_radar.notifier.send_windows_toast", return_value=True):

        res = dispatch_alerts(
            in_memory_db,
            [(sample_cert, sample_match)],
            telegram_token="dummy_token",
            telegram_chat_id="12345",
            client=tg_client,
            enable_windows=True,
        )
        assert res["windows_sent"] == 1
        assert res["telegram_sent"] == 1
        assert res["skipped_dedup"] == 0

        # Run again: both channels should be deduplicated
        res2 = dispatch_alerts(
            in_memory_db,
            [(sample_cert, sample_match)],
            telegram_token="dummy_token",
            telegram_chat_id="12345",
            client=tg_client,
            enable_windows=True,
        )
        assert res2["windows_sent"] == 0
        assert res2["telegram_sent"] == 0
        assert res2["skipped_dedup"] == 2


def test_dispatch_alerts_epoch_change_triggers_new_alert(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    in_memory_db.upsert_certification(sample_cert)

    with patch("cert_radar.notifier.send_windows_toast", return_value=True):
        res1 = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], enable_windows=True)
        assert res1["windows_sent"] == 1

        # Same epoch -> skipped
        res2 = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], enable_windows=True)
        assert res2["windows_sent"] == 0
        assert res2["skipped_dedup"] == 1

        # Epoch increments -> new dedup key -> sent again!
        sample_cert.activation_epoch = 2
        in_memory_db.upsert_certification(sample_cert)

        res3 = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], enable_windows=True)
        assert res3["windows_sent"] == 1
        assert res3["skipped_dedup"] == 0


def test_build_alert_message_unknown_cost_and_no_deadline(sample_cert: Certification, sample_match: MatchResult):
    sample_cert.cost_type = "uncommon_grant"  # type: ignore
    sample_cert.deadline_at = None
    msg = build_alert_message(sample_cert, sample_match, alert_type="new_voucher")
    assert "uncommon_grant" in msg
    assert "Contínuo / Não especificado" in msg


def test_send_telegram_alert_generic_exception():
    with patch("httpx.Client.post", side_effect=Exception("Fatal unexpected failure")):
        res = send_telegram_alert("token", "chat", "msg")
        assert res is False


def test_determine_alert_type_variations():
    from datetime import date
    from cert_radar.notifier import _determine_alert_type

    # No deadline
    assert _determine_alert_type(None) == "new_voucher"

    # Invalid deadline format
    assert _determine_alert_type("invalid-date-string") == "new_voucher"

    # Reference date as date object
    ref_d = date(2026, 11, 10)
    # Deadline 1 day after -> expiring_48h
    assert _determine_alert_type("2026-11-11", reference_date=ref_d) == "expiring_48h"

    # Reference date as naive datetime
    ref_naive = datetime(2026, 11, 10, 0, 0, 0)
    # Deadline 5 days after -> expiring_7d
    assert _determine_alert_type("2026-11-15T12:00:00", reference_date=ref_naive) == "expiring_7d"

    # No reference date passed (defaults to now)
    assert _determine_alert_type("2099-01-01") == "new_voucher"


def test_dispatch_alerts_no_active_channels(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    res = dispatch_alerts(
        in_memory_db,
        [(sample_cert, sample_match)],
        enable_windows=False,
        telegram_token=None,
    )
    assert res == {"windows_sent": 0, "telegram_sent": 0, "skipped_dedup": 0}


def test_dispatch_alerts_delivery_failure_does_not_log_alert(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    in_memory_db.upsert_certification(sample_cert)

    # Windows delivery fails -> windows_sent is 0 and alert is NOT logged
    with patch("cert_radar.notifier.send_windows_toast", return_value=False):
        res = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], enable_windows=True)
        assert res["windows_sent"] == 0
        assert res["skipped_dedup"] == 0

    # On next attempt, because it was not logged, it tries again (skipped_dedup is still 0)
    with patch("cert_radar.notifier.send_windows_toast", return_value=True):
        res2 = dispatch_alerts(in_memory_db, [(sample_cert, sample_match)], enable_windows=True)
        assert res2["windows_sent"] == 1
        assert res2["skipped_dedup"] == 0


def test_dispatch_alerts_skips_multiple_unmet_candidates(in_memory_db: Database, sample_cert: Certification, sample_match: MatchResult):
    # Candidate 1: inactive voucher
    cert_inactive = sample_cert.model_copy(update={"id": "cert-inactive", "is_voucher_active": False})
    match_inactive = sample_match.model_copy(update={"cert_id": "cert-inactive"})

    # Candidate 2: not live (expired)
    cert_expired = sample_cert.model_copy(update={"id": "cert-expired", "is_voucher_active": True, "liveness_status": "expired"})
    match_expired = sample_match.model_copy(update={"cert_id": "cert-expired"})

    # Candidate 3: score below min_score and not saved
    cert_low = sample_cert.model_copy(update={"id": "cert-low", "is_voucher_active": True, "liveness_status": "live"})
    match_low = sample_match.model_copy(update={"cert_id": "cert-low", "score": 40})

    # Candidate 4: valid candidate
    cert_valid = sample_cert.model_copy(update={"id": "cert-valid", "is_voucher_active": True, "liveness_status": "live"})
    match_valid = sample_match.model_copy(update={"cert_id": "cert-valid", "score": 80})

    in_memory_db.upsert_certification(cert_inactive)
    in_memory_db.upsert_certification(cert_expired)
    in_memory_db.upsert_certification(cert_low)
    in_memory_db.upsert_certification(cert_valid)

    candidates = [
        (cert_inactive, match_inactive),
        (cert_expired, match_expired),
        (cert_low, match_low),
        (cert_valid, match_valid),
    ]

    with patch("cert_radar.notifier.send_windows_toast", return_value=True):
        res = dispatch_alerts(in_memory_db, candidates, min_score=65, enable_windows=True)
        assert res["windows_sent"] == 1
        assert res["skipped_dedup"] == 0


