"""Explainable profile matcher engine for CertRadar.

Calculates match scores (0-100) across 4 pillars:
1. Role Alignment (0-35 pts)
2. Gap Closure (0-25 pts)
3. Recruiter Market Signal (0-20 pts)
4. Cost & Voucher Urgency (0-20 pts)

Handles redundancy suppression (e.g. CAPM) and foundations penalties.
"""

from datetime import date, datetime
import logging
import re
from typing import Optional
from pydantic import BaseModel, Field

from cert_radar.models import CandidateProfile, Certification

logger = logging.getLogger(__name__)

# Keywords identifying data, AI, and related modern engineering fields
DATA_AI_KEYWORDS = {
    "ai",
    "ia",
    "data",
    "dados",
    "machine learning",
    "ml",
    "analytics",
    "deep learning",
    "llm",
    "genai",
    "generative ai",
    "prompt",
    "nlp",
    "vision",
    "cloud ai",
    "lakehouse",
    "fabric",
    "databricks",
    "azure openai",
    "vector search",
}

FOUNDATION_LEVELS = {
    "foundations",
    "foundational",
    "foundation",
    "fundamentals",
    "fundamental",
}


class MatchResult(BaseModel):
    """Result of profile matching against a single certification."""

    cert_id: str = Field(..., description="Certification unique identifier")
    score: int = Field(..., ge=0, le=100, description="Overall match score (0-100)")
    role_score: int = Field(..., ge=0, le=35, description="Role alignment score (0-35)")
    gap_score: int = Field(..., ge=0, le=25, description="Gap closure score (0-25)")
    signal_score: int = Field(
        ..., ge=0, le=20, description="Recruiter market signal score (0-20)"
    )
    cost_score: int = Field(
        ..., ge=0, le=20, description="Cost & voucher urgency score (0-20)"
    )
    match_reasons: list[str] = Field(
        default_factory=list, description="Detailed explanatory reasons for the score"
    )
    redundancy_warning: Optional[str] = Field(
        default=None,
        description="Warning indicating redundancy or foundations penalty",
    )
    is_redundant: bool = Field(
        default=False, description="Flag indicating redundant certification"
    )


def _norm(text: str) -> str:
    """Normalize text for consistent comparison."""
    return text.strip().lower()


def _parse_deadline_date(deadline_str: Optional[str]) -> Optional[date]:
    """Parse ISO date or datetime string into a date object."""
    if not deadline_str:
        return None
    try:
        # Handles YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
        cleaned = deadline_str.strip()
        if "T" in cleaned:
            return datetime.fromisoformat(cleaned).date()
        return date.fromisoformat(cleaned)
    except Exception:
        return None


def calculate_match(
    profile: CandidateProfile,
    cert: Certification,
    reference_date: Optional[date | datetime] = None,
) -> MatchResult:
    """Calculates match score (0-100) between a candidate profile and a certification."""
    if reference_date is None:
        ref_date = date.today()
    elif isinstance(reference_date, datetime):
        ref_date = reference_date.date()
    else:
        ref_date = reference_date

    match_reasons: list[str] = []
    redundancy_warning: Optional[str] = None
    is_redundant = False

    # ---------------------------------------------------------
    # Redundancy Check against profile.existing_certifications
    # ---------------------------------------------------------
    for existing in profile.existing_certifications:
        existing_cleaned = existing.strip()
        if not existing_cleaned:
            continue

        # 1. Exact exam code match
        if cert.exam_code and _norm(cert.exam_code) == _norm(existing_cleaned):
            is_redundant = True
            redundancy_warning = (
                f"Credencial já existente no seu currículo ({existing_cleaned})"
            )
            break

        # 2. Exact title match
        if _norm(cert.title) == _norm(existing_cleaned):
            is_redundant = True
            redundancy_warning = (
                f"Credencial já existente no seu currículo ({existing_cleaned})"
            )
            break

        # 3. Token match (e.g. CAPM, AWS-SAA, etc.)
        if len(existing_cleaned) >= 3 and re.match(
            r"^[A-Za-z0-9_-]+$", existing_cleaned
        ):
            pattern = rf"\b{re.escape(existing_cleaned)}\b"
            if re.search(pattern, cert.title, re.IGNORECASE) or (
                cert.exam_code
                and re.search(pattern, cert.exam_code, re.IGNORECASE)
            ):
                is_redundant = True
                redundancy_warning = (
                    f"Credencial já existente no seu currículo ({existing_cleaned})"
                )
                break

    # ---------------------------------------------------------
    # Pillar 1: Role Alignment (35 pts max)
    # ---------------------------------------------------------
    role_score = 0
    primary_matched: Optional[str] = None
    for cert_role in cert.target_roles:
        c_role_norm = _norm(cert_role)
        for target in profile.target_roles:
            t_norm = _norm(target)
            if c_role_norm == t_norm or t_norm in c_role_norm or c_role_norm in t_norm:
                primary_matched = target
                break
        if primary_matched:
            break

    if primary_matched:
        role_score = 35
        match_reasons.append(f"Alinha com cargo-alvo principal: {primary_matched}")
    else:
        archetype_matched: Optional[str] = None
        for cert_role in cert.target_roles:
            c_role_norm = _norm(cert_role)
            for arch in profile.primary_archetypes:
                a_norm = _norm(arch)
                if c_role_norm == a_norm or a_norm in c_role_norm or c_role_norm in a_norm:
                    archetype_matched = arch
                    break
            if archetype_matched:
                break

        if archetype_matched:
            role_score = 25
            match_reasons.append(
                f"Alinha com arquétipo profissional: {archetype_matched}"
            )
        else:
            # Check for correlated area (Data/AI)
            is_related_area = False
            haystack = " ".join(
                [_norm(cert.title)]
                + [_norm(r) for r in cert.target_roles]
                + [_norm(s) for s in cert.skills_covered]
            )
            for kw in DATA_AI_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", haystack, re.IGNORECASE):
                    is_related_area = True
                    break

            if is_related_area:
                role_score = 10
                match_reasons.append(
                    "Atuação na área correlata de Dados e Inteligência Artificial"
                )
            else:
                role_score = 0

    # ---------------------------------------------------------
    # Pillar 2: Gap Closure (25 pts max)
    # ---------------------------------------------------------
    gap_score = 0
    closed_gaps: list[str] = []
    for gap in profile.gaps:
        g_norm = _norm(gap)
        for skill in cert.skills_covered:
            s_norm = _norm(skill)
            if g_norm == s_norm or g_norm in s_norm or s_norm in g_norm:
                closed_gaps.append(gap)
                break

    if closed_gaps:
        gap_score = min(25, len(closed_gaps) * 10)
        for g in closed_gaps:
            match_reasons.append(f"Fecha o gap real {g} extraído do career-ops")
    else:
        # Check if cert introduces new skills not in known_skills
        known_norms = [_norm(k) for k in profile.known_skills]
        new_skills: list[str] = []
        for skill in cert.skills_covered:
            s_norm = _norm(skill)
            if not any(
                s_norm == k or s_norm in k or k in s_norm for k in known_norms
            ):
                new_skills.append(skill)

        if new_skills:
            gap_score = 12
            match_reasons.append(
                f"Expande repertório com {len(new_skills)} novas habilidades ({', '.join(new_skills[:3])})"
            )
        else:
            gap_score = 0

    # ---------------------------------------------------------
    # Pillar 3: Recruiter Signal (20 pts max)
    # ---------------------------------------------------------
    signal_score = min(20, max(0, cert.recruiter_signal * 4))
    match_reasons.append(
        f"Sinal de mercado para recrutadores ({cert.recruiter_signal}/5)"
    )

    # ---------------------------------------------------------
    # Pillar 4: Cost & Voucher Urgency (20 pts max)
    # ---------------------------------------------------------
    cost_score = 0
    if cert.cost_type == "free":
        cost_score = 16
        match_reasons.append("Certificação gratuita contínua")
    elif cert.cost_type == "voucher_100":
        if cert.is_voucher_active:
            cost_score = 16
            match_reasons.append("Voucher oficial 100% gratuito ativo")
        else:
            cost_score = 0
    elif (
        cert.cost_type == "voucher_discount"
        or (cert.cost_type == "scholarship" and cert.discount_pct > 0)
        or cert.discount_pct > 0
    ):
        cost_score = 12
        match_reasons.append(
            f"Voucher com desconto ({cert.discount_pct}% off)"
        )
    else:
        cost_score = 0

    # Urgency bonus (+4 pts for deadlines <= 14 days)
    if cert.is_voucher_active and cert.deadline_at:
        deadline_date = _parse_deadline_date(cert.deadline_at)
        if deadline_date:
            days_left = (deadline_date - ref_date).days
            if 0 <= days_left <= 14:
                cost_score = min(20, cost_score + 4)
                match_reasons.append(
                    f"Urgência de prazo: restam {days_left} dias para expirar"
                )

    cost_score = min(20, cost_score)

    # ---------------------------------------------------------
    # Check Redundancy Suppressed Outcome
    # ---------------------------------------------------------
    if is_redundant:
        return MatchResult(
            cert_id=cert.id,
            score=0,
            role_score=role_score,
            gap_score=gap_score,
            signal_score=signal_score,
            cost_score=cost_score,
            match_reasons=match_reasons,
            redundancy_warning=redundancy_warning,
            is_redundant=True,
        )

    # ---------------------------------------------------------
    # Foundations Penalty (-25 pts if all skills known & no 100% voucher)
    # ---------------------------------------------------------
    penalty = 0
    is_foundations = _norm(cert.level) in FOUNDATION_LEVELS
    if is_foundations and cert.skills_covered:
        known_norms = [_norm(k) for k in profile.known_skills]
        all_skills_known = all(
            any(
                _norm(s) == k or _norm(s) in k or k in _norm(s)
                for k in known_norms
            )
            for s in cert.skills_covered
        )
        has_voucher_100_active = cert.is_voucher_active and (
            cert.cost_type in ("free", "voucher_100") or cert.discount_pct == 100
        )
        if all_skills_known and not has_voucher_100_active:
            penalty = 25
            redundancy_warning = (
                "Conteúdo já coberto por skills comprovadas no CV (penalidade foundations)"
            )
            match_reasons.append(
                "-25 pts: Nível foundations com conteúdo já dominado no CV sem voucher 100%"
            )

    raw_score = role_score + gap_score + signal_score + cost_score - penalty
    final_score = max(0, min(100, raw_score))

    return MatchResult(
        cert_id=cert.id,
        score=final_score,
        role_score=role_score,
        gap_score=gap_score,
        signal_score=signal_score,
        cost_score=cost_score,
        match_reasons=match_reasons,
        redundancy_warning=redundancy_warning,
        is_redundant=False,
    )


def rank_certifications(
    profile: CandidateProfile,
    certs: list[Certification],
    hide_redundant: bool = True,
    reference_date: Optional[date | datetime] = None,
) -> list[tuple[Certification, MatchResult]]:
    """Ranks certifications for a candidate profile by match score and urgency.

    Ordering:
    1. Score descending
    2. Expiration deadline ascending (nearest first; no deadline last)
    3. Recruiter signal descending
    4. Title ascending
    """
    evaluated: list[tuple[Certification, MatchResult]] = []
    for cert in certs:
        result = calculate_match(profile, cert, reference_date=reference_date)
        if hide_redundant and result.is_redundant:
            continue
        evaluated.append((cert, result))

    def _sort_key(item: tuple[Certification, MatchResult]):
        c, r = item
        score_key = -r.score
        # For deadline: format as YYYY-MM-DD string; None becomes "9999-12-31"
        deadline_key = c.deadline_at if c.deadline_at else "9999-12-31"
        signal_key = -c.recruiter_signal
        return (score_key, deadline_key, signal_key, c.title)

    return sorted(evaluated, key=_sort_key)
