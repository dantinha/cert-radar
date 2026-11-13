"""Data models for CertRadar using Pydantic v2."""

from typing import Literal, Optional
from pydantic import BaseModel, Field

CostType = Literal["free", "voucher_100", "voucher_discount", "scholarship"]
TrackType = Literal["official_voucher", "free_continuous"]
LivenessStatus = Literal["live", "expired", "dead", "unverified", "error"]
ProgressStatus = Literal["radar", "saved", "studying", "completed", "ignored"]
AlertChannel = Literal["windows", "telegram"]
AlertType = Literal["new_voucher", "expiring_7d", "expiring_48h"]


class Certification(BaseModel):
    id: str = Field(..., description="Unique slug identifier (e.g. aws-certified-ai-practitioner)")
    title: str = Field(..., description="Official title of the certification")
    provider: str = Field(..., description="Issuing entity (AWS, Microsoft, NVIDIA, etc.)")
    track: TrackType = Field(..., description="Track type: official_voucher or free_continuous")
    cost_type: CostType = Field(..., description="Cost classification")
    discount_pct: int = Field(default=0, ge=0, le=100, description="Discount percentage")
    normal_price_usd: float = Field(default=0.0, ge=0.0, description="List price in USD")
    exam_code: Optional[str] = Field(default=None, description="Official exam code if proctored")
    target_roles: list[str] = Field(default_factory=list, description="Target career roles")
    skills_covered: list[str] = Field(default_factory=list, description="Covered domains & skills")
    level: str = Field(default="associate", description="Difficulty level (foundational, associate, etc.)")
    effort_hours: int = Field(default=10, ge=0, description="Estimated study time in hours")
    recruiter_signal: int = Field(default=3, ge=1, le=5, description="Market value signal rating (1-5)")
    url: str = Field(..., description="Official URL for registration or course")
    voucher_program_url: Optional[str] = Field(default=None, description="URL of voucher campaign")
    is_voucher_active: bool = Field(default=False, description="Whether free voucher/access is active now")
    activation_epoch: int = Field(default=1, ge=1, description="Epoch generation for anti-spam dedup")
    deadline_at: Optional[str] = Field(default=None, description="ISO date or datetime string for campaign deadline")
    liveness_status: LivenessStatus = Field(default="unverified", description="Health check status of official URL")
    source_kind: str = Field(default="seed", description="Origin: seed, crawler, manual")
    last_checked_at: Optional[str] = Field(default=None, description="ISO timestamp of last health check")
    notes: str = Field(default="", description="Internal notes, redemption instructions or constraints")


class VoucherEvent(BaseModel):
    id: Optional[int] = Field(default=None, description="Auto-incremented event ID")
    cert_id: str = Field(..., description="Associated certification ID")
    source_name: str = Field(..., description="Feed or collector name that caught the event")
    event_type: str = Field(..., description="Type of event (voucher_detected, expired, etc.)")
    payload_json: str = Field(default="{}", description="Raw detection context serialized as JSON")
    detected_at: str = Field(..., description="ISO timestamp of detection")


class UserProgress(BaseModel):
    cert_id: str = Field(..., description="Certification identifier")
    status: ProgressStatus = Field(default="radar", description="Personal tracking status")
    user_notes: str = Field(default="", description="Personal study logs or scheduled exam dates")
    updated_at: str = Field(..., description="ISO timestamp of last update")


class AlertLog(BaseModel):
    id: Optional[int] = Field(default=None, description="Log entry ID")
    cert_id: str = Field(..., description="Associated certification ID")
    channel: AlertChannel = Field(..., description="Notification channel (windows or telegram)")
    alert_type: AlertType = Field(..., description="Alert trigger category")
    dedup_key: str = Field(..., description="Unique deduplication hash/key")
    sent_at: str = Field(..., description="ISO timestamp when alert was dispatched")
    delivery_status: str = Field(default="sent", description="Delivery status (sent, failed, mocked)")


class CandidateProfile(BaseModel):
    full_name: str = Field(..., description="Candidate's full name")
    email: str = Field(..., description="Contact email")
    target_roles: list[str] = Field(default_factory=list, description="Target career roles")
    primary_archetypes: list[str] = Field(default_factory=list, description="Target skill/career archetypes")
    known_skills: list[str] = Field(default_factory=list, description="Validated skills from profile & CV")
    gaps: list[str] = Field(default_factory=list, description="Identified skill gaps to address")
    existing_certifications: list[str] = Field(default_factory=list, description="Certifications already acquired")
