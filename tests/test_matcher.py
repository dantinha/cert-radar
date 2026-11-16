"""Unit tests for CertRadar explainable profile matcher engine."""

from datetime import date, datetime
import pytest

from cert_radar.models import CandidateProfile, Certification
from cert_radar.matcher import (
    MatchResult,
    calculate_match,
    rank_certifications,
)


@pytest.fixture
def sample_profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Gabriel Santos",
        email="gabriel@example.com",
        target_roles=["AI Product Manager", "Context Engineer"],
        primary_archetypes=[
            "Technical Product Manager (Data & Analytics)",
            "AI Solutions Architect",
        ],
        known_skills=["Python", "SQL", "Git", "Project Management"],
        gaps=["Azure OpenAI", "Vector Search", "Prompt Flow"],
        existing_certifications=[
            "CAPM – Certified Associate in Project Management (PMI)",
            "CAPM",
            "PMI",
        ],
    )


@pytest.fixture
def base_cert() -> Certification:
    return Certification(
        id="test-cert-ai",
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
        effort_hours=35,
        recruiter_signal=5,
        url="https://learn.microsoft.com/certifications/azure-ai-engineer/",
        voucher_program_url="https://learn.microsoft.com/challenges",
        is_voucher_active=True,
        activation_epoch=1,
        deadline_at="2026-11-20",
        liveness_status="live",
    )


def test_match_result_dataclass():
    res = MatchResult(
        cert_id="c1",
        score=85,
        role_score=35,
        gap_score=20,
        signal_score=20,
        cost_score=10,
        match_reasons=["Test reason"],
        redundancy_warning=None,
        is_redundant=False,
    )
    assert res.cert_id == "c1"
    assert res.score == 85
    assert res.is_redundant is False
    assert len(res.match_reasons) == 1


def test_role_alignment_primary(sample_profile: CandidateProfile, base_cert: Certification):
    # Matches sample_profile.target_roles (AI Product Manager) -> 35 pts
    res = calculate_match(sample_profile, base_cert)
    assert res.role_score == 35
    assert any("AI Product Manager" in r for r in res.match_reasons)


def test_role_alignment_archetype(sample_profile: CandidateProfile, base_cert: Certification):
    # Matches archetype only -> 25 pts
    base_cert.target_roles = ["Technical Product Manager (Data & Analytics)"]
    res = calculate_match(sample_profile, base_cert)
    assert res.role_score == 25
    assert any("arquétipo" in r.lower() for r in res.match_reasons)


def test_role_alignment_related_area(sample_profile: CandidateProfile, base_cert: Certification):
    # Role is not exact target role or archetype, but in Data/AI area -> 10 pts
    base_cert.target_roles = ["Data Analyst"]
    base_cert.skills_covered = ["Power BI", "Data Modeling"]
    res = calculate_match(sample_profile, base_cert)
    assert res.role_score == 10
    assert any("área correlata" in r.lower() or "dados" in r.lower() for r in res.match_reasons)


def test_role_alignment_unrelated(sample_profile: CandidateProfile, base_cert: Certification):
    # Completely unrelated field -> 0 pts
    base_cert.target_roles = ["Chef de Cuisine"]
    base_cert.skills_covered = ["Baking", "Gastronomy"]
    base_cert.title = "Culinary Arts Master"
    res = calculate_match(sample_profile, base_cert)
    assert res.role_score == 0


def test_gap_closure_explicit_gaps(sample_profile: CandidateProfile, base_cert: Certification):
    # base_cert covers "Azure OpenAI" and "Prompt Flow" (2 gaps in sample_profile)
    # 2 gaps * 10 pts = 20 pts
    base_cert.skills_covered = ["Azure OpenAI", "Prompt Flow"]
    res = calculate_match(sample_profile, base_cert)
    assert res.gap_score == 20
    assert any("Azure OpenAI" in r for r in res.match_reasons)
    assert any("Prompt Flow" in r for r in res.match_reasons)


def test_gap_closure_capped_at_25(sample_profile: CandidateProfile, base_cert: Certification):
    # 3 gaps in sample_profile: Azure OpenAI, Vector Search, Prompt Flow -> 3 * 10 = 30 -> capped at 25
    base_cert.skills_covered = ["Azure OpenAI", "Vector Search", "Prompt Flow"]
    res = calculate_match(sample_profile, base_cert)
    assert res.gap_score == 25


def test_gap_closure_fallback_new_skills(sample_profile: CandidateProfile, base_cert: Certification):
    # No explicit gaps closed, but introduces new skills not in known_skills -> 12 pts
    base_cert.skills_covered = ["Docker", "Kubernetes"]
    res = calculate_match(sample_profile, base_cert)
    assert res.gap_score == 12
    assert any("novas habilidades" in r.lower() for r in res.match_reasons)


def test_gap_closure_all_known_skills(sample_profile: CandidateProfile, base_cert: Certification):
    # No explicit gaps closed and all skills are already known -> 0 pts
    base_cert.skills_covered = ["Python", "SQL"]
    res = calculate_match(sample_profile, base_cert)
    assert res.gap_score == 0


def test_recruiter_signal_calculation(sample_profile: CandidateProfile, base_cert: Certification):
    base_cert.recruiter_signal = 5
    res5 = calculate_match(sample_profile, base_cert)
    assert res5.signal_score == 20

    base_cert.recruiter_signal = 3
    res3 = calculate_match(sample_profile, base_cert)
    assert res3.signal_score == 12

    base_cert.recruiter_signal = 1
    res1 = calculate_match(sample_profile, base_cert)
    assert res1.signal_score == 4


def test_cost_free_continuous(sample_profile: CandidateProfile, base_cert: Certification):
    base_cert.cost_type = "free"
    base_cert.discount_pct = 100
    base_cert.deadline_at = None
    res = calculate_match(sample_profile, base_cert)
    assert res.cost_score == 16
    assert any("gratuita" in r.lower() for r in res.match_reasons)


def test_cost_voucher_100_active_vs_inactive(sample_profile: CandidateProfile, base_cert: Certification):
    base_cert.cost_type = "voucher_100"
    base_cert.is_voucher_active = True
    base_cert.deadline_at = None
    res_active = calculate_match(sample_profile, base_cert)
    assert res_active.cost_score == 16

    base_cert.is_voucher_active = False
    res_inactive = calculate_match(sample_profile, base_cert)
    assert res_inactive.cost_score == 0


def test_cost_voucher_discount(sample_profile: CandidateProfile, base_cert: Certification):
    base_cert.cost_type = "voucher_discount"
    base_cert.discount_pct = 50
    base_cert.deadline_at = None
    res = calculate_match(sample_profile, base_cert)
    assert res.cost_score == 12
    assert any("desconto" in r.lower() for r in res.match_reasons)


def test_cost_urgency_bonus(sample_profile: CandidateProfile, base_cert: Certification):
    ref_date = date(2026, 11, 10)
    # Deadline in 8 days (<= 14 days) -> +4 pts bonus (16 + 4 = 20)
    base_cert.deadline_at = "2026-11-18"
    base_cert.is_voucher_active = True
    res_urgent = calculate_match(sample_profile, base_cert, reference_date=ref_date)
    assert res_urgent.cost_score == 20
    assert any("urgência" in r.lower() for r in res_urgent.match_reasons)

    # Deadline in 25 days (> 14 days) -> no urgency bonus (16 pts)
    base_cert.deadline_at = "2026-12-05"
    res_not_urgent = calculate_match(sample_profile, base_cert, reference_date=ref_date)
    assert res_not_urgent.cost_score == 16


def test_redundancy_suppression_exam_code(sample_profile: CandidateProfile, base_cert: Certification):
    # Candidate already has CAPM in profile.existing_certifications
    base_cert.exam_code = "CAPM"
    base_cert.title = "Project Management Credential"
    res = calculate_match(sample_profile, base_cert)

    assert res.is_redundant is True
    assert res.score == 0
    assert res.redundancy_warning is not None
    assert "já existente" in res.redundancy_warning.lower() or "cv" in res.redundancy_warning.lower()


def test_redundancy_suppression_title_token(sample_profile: CandidateProfile, base_cert: Certification):
    # Title has CAPM token
    base_cert.exam_code = "PMI-100"
    base_cert.title = "Certified Associate in Project Management (CAPM) Preparation"
    res = calculate_match(sample_profile, base_cert)

    assert res.is_redundant is True
    assert res.score == 0
    assert res.redundancy_warning is not None


def test_foundations_penalty_without_voucher_100(sample_profile: CandidateProfile, base_cert: Certification):
    # Level foundations, all skills already known, cost_type discount (not voucher_100)
    base_cert.level = "foundations"
    base_cert.skills_covered = ["Python", "SQL"]  # both in sample_profile.known_skills
    base_cert.cost_type = "voucher_discount"
    base_cert.discount_pct = 50
    base_cert.is_voucher_active = True
    base_cert.recruiter_signal = 3  # 12 pts
    base_cert.deadline_at = None

    # Role score: 35
    # Gap score: 0 (all skills known)
    # Signal score: 12
    # Cost score: 12
    # Sum: 35 + 0 + 12 + 12 = 59
    # Penalty: -25 -> score 34
    res = calculate_match(sample_profile, base_cert)
    assert res.is_redundant is False
    assert res.score == 34
    assert res.redundancy_warning is not None
    assert "coberto por skills" in res.redundancy_warning.lower() or "cv" in res.redundancy_warning.lower()


def test_foundations_penalty_waived_with_voucher_100(sample_profile: CandidateProfile, base_cert: Certification):
    # Level foundations, all skills known, BUT voucher 100% active -> NO penalty!
    base_cert.level = "foundations"
    base_cert.skills_covered = ["Python", "SQL"]
    base_cert.cost_type = "voucher_100"
    base_cert.discount_pct = 100
    base_cert.is_voucher_active = True
    base_cert.recruiter_signal = 3  # 12 pts
    base_cert.deadline_at = None

    # Role score: 35
    # Gap score: 0
    # Signal score: 12
    # Cost score: 16
    # Sum: 35 + 0 + 12 + 16 = 63 (no penalty)
    res = calculate_match(sample_profile, base_cert)
    assert res.is_redundant is False
    assert res.score == 63
    assert res.redundancy_warning is None


def test_clamped_score_bounds(sample_profile: CandidateProfile, base_cert: Certification):
    # Perfect score: 35 + 25 + 20 + 20 = 100
    base_cert.target_roles = ["AI Product Manager"]
    base_cert.skills_covered = ["Azure OpenAI", "Vector Search", "Prompt Flow"]
    base_cert.recruiter_signal = 5
    base_cert.cost_type = "voucher_100"
    base_cert.is_voucher_active = True
    base_cert.deadline_at = "2026-11-15"
    ref_date = date(2026, 11, 10)

    res = calculate_match(sample_profile, base_cert, reference_date=ref_date)
    assert res.score == 100
    assert 0 <= res.score <= 100


def test_rank_certifications_ordering_and_filtering(sample_profile: CandidateProfile, base_cert: Certification):
    ref_date = date(2026, 11, 10)

    # Cert 1: High score, deadline in 5 days
    c1 = base_cert.model_copy()
    c1.id = "c1"
    c1.title = "Cert 1 Urgent"
    c1.deadline_at = "2026-11-15"

    # Cert 2: High score, deadline in 20 days
    c2 = base_cert.model_copy()
    c2.id = "c2"
    c2.title = "Cert 2 Later"
    c2.deadline_at = "2026-11-30"

    # Cert 3: Lower score
    c3 = base_cert.model_copy()
    c3.id = "c3"
    c3.title = "Cert 3 Lower"
    c3.target_roles = ["Chef"]
    c3.skills_covered = ["Cooking"]
    c3.recruiter_signal = 2

    # Cert 4: Redundant (CAPM)
    c4 = base_cert.model_copy()
    c4.id = "c4"
    c4.title = "CAPM Exam"
    c4.exam_code = "CAPM"

    all_certs = [c3, c4, c2, c1]

    # Test with hide_redundant = True (default)
    ranked = rank_certifications(sample_profile, all_certs, hide_redundant=True, reference_date=ref_date)
    assert len(ranked) == 3
    assert all(not r.is_redundant for _, r in ranked)
    # c1 has urgency bonus (+4 pts in cost score), so c1 > c2 > c3
    assert ranked[0][0].id == "c1"
    assert ranked[1][0].id == "c2"
    assert ranked[2][0].id == "c3"

    # Test with hide_redundant = False
    ranked_with_redundant = rank_certifications(sample_profile, all_certs, hide_redundant=False, reference_date=ref_date)
    assert len(ranked_with_redundant) == 4
    assert ranked_with_redundant[-1][0].id == "c4"
    assert ranked_with_redundant[-1][1].is_redundant is True
    assert ranked_with_redundant[-1][1].score == 0


def test_calculate_match_with_datetime_and_iso_format(sample_profile: CandidateProfile, base_cert: Certification):
    # Reference date as datetime
    ref_dt = datetime(2026, 11, 10, 14, 30, 0)
    # Deadline as ISO datetime with 'T'
    base_cert.deadline_at = "2026-11-18T23:59:59"
    base_cert.is_voucher_active = True
    res = calculate_match(sample_profile, base_cert, reference_date=ref_dt)
    assert res.cost_score == 20


def test_calculate_match_with_invalid_deadline(sample_profile: CandidateProfile, base_cert: Certification):
    from cert_radar.matcher import _parse_deadline_date
    assert _parse_deadline_date(None) is None
    assert _parse_deadline_date("") is None

    base_cert.deadline_at = "invalid-date-format"
    base_cert.is_voucher_active = True
    res = calculate_match(sample_profile, base_cert)
    # Should not raise exception and no urgency bonus
    assert res.cost_score == 16


def test_calculate_match_without_reference_date(sample_profile: CandidateProfile, base_cert: Certification):
    base_cert.deadline_at = None
    res = calculate_match(sample_profile, base_cert, reference_date=None)
    assert res.cost_score == 16


def test_redundancy_suppression_exact_title(sample_profile: CandidateProfile, base_cert: Certification):
    sample_profile.existing_certifications.insert(0, "   ")  # tests whitespace skip
    sample_profile.existing_certifications.append("Azure AI Engineer Associate")
    base_cert.exam_code = None
    base_cert.title = "Azure AI Engineer Associate"
    res = calculate_match(sample_profile, base_cert)
    assert res.is_redundant is True
    assert res.score == 0
    assert "Azure AI Engineer Associate" in (res.redundancy_warning or "")


def test_cost_score_unsupported_or_zero(sample_profile: CandidateProfile, base_cert: Certification):
    # cost_type not matching free/voucher and discount_pct=0
    base_cert.cost_type = "scholarship"
    base_cert.discount_pct = 0
    base_cert.is_voucher_active = False
    base_cert.deadline_at = None
    res = calculate_match(sample_profile, base_cert)
    assert res.cost_score == 0


def test_real_catalog_ai_102_match(sample_profile: CandidateProfile):
    import json
    from pathlib import Path

    catalog_path = Path(__file__).resolve().parents[1] / "data" / "seed_catalog.json"
    if not catalog_path.exists():
        return

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    certs = [Certification.model_validate(c) for c in data]

    ai_102 = next((c for c in certs if c.exam_code == "AI-102"), None)
    assert ai_102 is not None

    ref_date = date(2026, 11, 16)
    match_result = calculate_match(sample_profile, ai_102, reference_date=ref_date)

    # AI-102 aligns with AI Product Manager (35 pts), closes gaps (Azure OpenAI, Prompt Flow) (20+ pts),
    # recruiter_signal 5 (20 pts), voucher_100 active with deadline 2026-11-28 (<= 14 days from 2026-11-16) (20 pts)
    # Total = 95
    assert match_result.score >= 90
    assert match_result.role_score == 35
    assert match_result.gap_score >= 20
    assert match_result.signal_score == 20
    assert match_result.cost_score == 20
    assert match_result.is_redundant is False

