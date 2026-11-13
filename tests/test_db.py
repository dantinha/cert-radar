import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from cert_radar.db import Database
from cert_radar.models import (
    CandidateProfile,
    Certification,
    UserProgress,
    VoucherEvent,
)


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    db_file = tmp_path / "test_cert_radar.db"
    database = Database(db_path=db_file)
    database.init_db()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def sample_cert() -> Certification:
    return Certification(
        id="aws-certified-ai-practitioner",
        title="AWS Certified AI Practitioner",
        provider="AWS",
        track="official_voucher",
        cost_type="voucher_100",
        discount_pct=100,
        normal_price_usd=100.0,
        exam_code="AIF-C01",
        target_roles=["AI Product Manager", "Context Engineer"],
        skills_covered=["Bedrock", "SageMaker", "Prompt Engineering"],
        level="foundational",
        effort_hours=20,
        recruiter_signal=4,
        url="https://aws.amazon.com/certification/certified-ai-practitioner/",
        voucher_program_url="https://aws.amazon.com/events/",
        is_voucher_active=True,
        activation_epoch=1,
        deadline_at="2026-12-31",
        liveness_status="live",
        source_kind="seed",
        last_checked_at=datetime.now(timezone.utc).isoformat(),
        notes="Official beta voucher initiative",
    )


def test_init_db(tmp_path: Path):
    db_path = tmp_path / "new_db.db"
    with Database(db_path=db_path) as db:
        db.init_db()
        assert db_path.exists()

        # Check WAL pragma and tables exist
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        assert mode.lower() in ("wal", "memory")

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = [row[0] for row in cursor.fetchall()]
        assert "certifications" in tables
        assert "voucher_events" in tables
        assert "user_progress" in tables
        assert "alert_log" in tables


def test_database_in_memory():
    with Database(db_path=":memory:") as mem_db:
        mem_db.init_db()
        cursor = mem_db.conn.cursor()
        cursor.execute("SELECT 1;")
        assert cursor.fetchone()[0] == 1


def test_upsert_and_get_certification(db: Database, sample_cert: Certification):
    # Initial upsert
    db.upsert_certification(sample_cert)

    retrieved = db.get_certification("aws-certified-ai-practitioner")
    assert retrieved is not None
    assert retrieved.id == sample_cert.id
    assert retrieved.title == sample_cert.title
    assert retrieved.provider == "AWS"
    assert retrieved.track == "official_voucher"
    assert retrieved.cost_type == "voucher_100"
    assert retrieved.discount_pct == 100
    assert retrieved.normal_price_usd == 100.0
    assert retrieved.exam_code == "AIF-C01"
    assert retrieved.target_roles == ["AI Product Manager", "Context Engineer"]
    assert retrieved.skills_covered == ["Bedrock", "SageMaker", "Prompt Engineering"]
    assert retrieved.is_voucher_active is True
    assert retrieved.liveness_status == "live"

    # Upsert with update
    updated_cert = sample_cert.model_copy(
        update={
            "discount_pct": 50,
            "cost_type": "voucher_discount",
            "is_voucher_active": False,
            "liveness_status": "expired",
        }
    )
    db.upsert_certification(updated_cert)

    retrieved_updated = db.get_certification("aws-certified-ai-practitioner")
    assert retrieved_updated is not None
    assert retrieved_updated.discount_pct == 50
    assert retrieved_updated.cost_type == "voucher_discount"
    assert retrieved_updated.is_voucher_active is False
    assert retrieved_updated.liveness_status == "expired"


def test_get_certification_not_found(db: Database):
    assert db.get_certification("non-existent-id") is None


def test_get_certifications_filters(db: Database, sample_cert: Certification):
    cert1 = sample_cert
    cert2 = Certification(
        id="nvidia-generative-ai-explained",
        title="Generative AI Explained",
        provider="NVIDIA",
        track="free_continuous",
        cost_type="free",
        discount_pct=100,
        normal_price_usd=0.0,
        exam_code=None,
        target_roles=["AI Product Manager"],
        skills_covered=["GenAI Concepts"],
        level="introductory",
        effort_hours=4,
        recruiter_signal=3,
        url="https://learn.nvidia.com/courses?course_id=course-v1:DLI+S-FX-07+V1",
        is_voucher_active=True,
    )
    cert3 = Certification(
        id="azure-ai-fundamentals",
        title="Azure AI Fundamentals",
        provider="Microsoft",
        track="official_voucher",
        cost_type="voucher_100",
        discount_pct=100,
        normal_price_usd=99.0,
        exam_code="AI-900",
        target_roles=["Technical PM"],
        skills_covered=["Azure AI", "Cognitive Services"],
        url="https://learn.microsoft.com/certifications/azure-ai-fundamentals/",
        is_voucher_active=False,
    )

    db.upsert_certification(cert1)
    db.upsert_certification(cert2)
    db.upsert_certification(cert3)

    # All certifications
    all_certs = db.get_certifications()
    assert len(all_certs) == 3

    # Filter by track
    vouchers = db.get_certifications(track="official_voucher")
    assert len(vouchers) == 2
    assert {c.id for c in vouchers} == {cert1.id, cert3.id}

    continuous = db.get_certifications(track="free_continuous")
    assert len(continuous) == 1
    assert continuous[0].id == cert2.id

    # Filter by is_active
    active = db.get_certifications(is_active=True)
    assert len(active) == 2
    assert {c.id for c in active} == {cert1.id, cert2.id}

    inactive = db.get_certifications(is_active=False)
    assert len(inactive) == 1
    assert inactive[0].id == cert3.id

    # Combined filter
    active_vouchers = db.get_certifications(track="official_voucher", is_active=True)
    assert len(active_vouchers) == 1
    assert active_vouchers[0].id == cert1.id


def test_record_event(db: Database, sample_cert: Certification):
    db.upsert_certification(sample_cert)

    event = VoucherEvent(
        cert_id=sample_cert.id,
        source_name="aws_events_feed",
        event_type="voucher_detected",
        payload_json='{"seats": 500}',
        detected_at=datetime.now(timezone.utc).isoformat(),
    )
    db.record_event(event)

    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT cert_id, source_name, event_type, payload_json FROM voucher_events WHERE cert_id = ?",
        (sample_cert.id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == sample_cert.id
    assert row[1] == "aws_events_feed"
    assert row[2] == "voucher_detected"
    assert row[3] == '{"seats": 500}'


def test_user_progress(db: Database, sample_cert: Certification):
    db.upsert_certification(sample_cert)

    # Initial state: None
    assert db.get_user_progress(sample_cert.id) is None

    # Set to studying
    db.set_user_progress(sample_cert.id, status="studying", notes="Reviewing chapter 1")
    prog = db.get_user_progress(sample_cert.id)
    assert prog is not None
    assert prog.cert_id == sample_cert.id
    assert prog.status == "studying"
    assert prog.user_notes == "Reviewing chapter 1"
    assert prog.updated_at != ""

    # Update to completed
    db.set_user_progress(sample_cert.id, status="completed", notes="Passed with 850/1000")
    prog_updated = db.get_user_progress(sample_cert.id)
    assert prog_updated is not None
    assert prog_updated.status == "completed"
    assert prog_updated.user_notes == "Passed with 850/1000"


def test_alert_log_and_deduplication(db: Database, sample_cert: Certification):
    db.upsert_certification(sample_cert)

    dedup_key = f"{sample_cert.id}:windows:new_voucher:epoch_1"
    assert db.has_alert_been_sent(dedup_key) is False

    # Log alert
    db.log_alert(
        cert_id=sample_cert.id,
        channel="windows",
        alert_type="new_voucher",
        dedup_key=dedup_key,
        status="sent",
    )

    assert db.has_alert_been_sent(dedup_key) is True

    # Duplicate insertion should fail on constraint or be rejected
    with pytest.raises(Exception):
        db.log_alert(
            cert_id=sample_cert.id,
            channel="windows",
            alert_type="new_voucher",
            dedup_key=dedup_key,
            status="sent",
        )


def test_candidate_profile_model():
    profile = CandidateProfile(
        full_name="Gabriel Test",
        email="test@example.com",
        target_roles=["AI Product Manager", "Context Engineer"],
        primary_archetypes=["Product Leader", "Builder"],
        known_skills=["Python", "System Design"],
        gaps=["SageMaker", "AWS AI"],
        existing_certifications=["CAPM"],
    )
    assert profile.full_name == "Gabriel Test"
    assert "CAPM" in profile.existing_certifications
    assert len(profile.gaps) == 2
