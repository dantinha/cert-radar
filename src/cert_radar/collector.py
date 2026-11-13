"""Radar Collector and Liveness Engine for CertRadar."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional, Union
import urllib.parse

import httpx

from cert_radar.db import Database
from cert_radar.models import Certification, VoucherEvent

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 CertRadar/1.0"
)
DEFAULT_TIMEOUT = 15.0

AUTH_WALL_DOMAINS = {
    "linkedin.com",
    "lnkd.in",
    "login.microsoftonline.com",
    "accounts.google.com",
    "auth0.com",
    "okta.com",
}


def _is_auth_wall(url: str) -> bool:
    """Detects whether a URL points to LinkedIn or a known authentication wall."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or url).lower().split(":")[0]

    if "linkedin" in host:
        return True
    if any(host.startswith(p) for p in ("auth.", "login.", "sso.", "accounts.")):
        return True
    if any(domain in host for domain in AUTH_WALL_DOMAINS):
        return True
    return False


def _is_expired_content(text: str) -> bool:
    """Checks response text for campaign termination phrases."""
    text_lower = text.lower()
    for phrase in ("registration ended", "no longer available", "challenge ended", "program ended"):
        if phrase in text_lower:
            return True
    for word_regex in (r"\bclosed\b", r"\bexpired\b"):
        if re.search(word_regex, text_lower):
            return True
    return False


def seed_initial_catalog(
    db: Database,
    seed_path: Union[Path, str] = "data/seed_catalog.json",
) -> int:
    """Loads default nuclear certifications into database idempotently."""
    path = Path(seed_path)
    if not path.exists():
        raise FileNotFoundError(f"Seed catalog file not found: {path}")

    content = path.read_text(encoding="utf-8")
    raw_data = json.loads(content)
    if not isinstance(raw_data, list):
        raise ValueError(f"Expected a list of certification records in {path}")

    now_iso = datetime.now(timezone.utc).isoformat()
    processed_count = 0

    for item in raw_data:
        cert = Certification(**item)
        existing = db.get_certification(cert.id)

        if existing is None:
            # Foreign key requires certification to exist before voucher_events record
            db.upsert_certification(cert)
            event = VoucherEvent(
                cert_id=cert.id,
                source_name="seed_catalog",
                event_type="baseline_seed",
                payload_json=json.dumps(
                    {
                        "title": cert.title,
                        "provider": cert.provider,
                        "track": cert.track,
                        "cost_type": cert.cost_type,
                    },
                    ensure_ascii=False,
                ),
                detected_at=now_iso,
            )
            db.record_event(event)
        else:
            db.upsert_certification(cert)

        processed_count += 1

    return processed_count


def check_liveness(
    url: str,
    client: Optional[httpx.Client] = None,
) -> tuple[str, Optional[int]]:
    """Performs HTTP health and content check on voucher or certification URL.

    Returns:
        (liveness_status, status_code)
        Status can be: 'live', 'expired', 'unverified', 'dead', 'error'
    """
    try:
        if client is not None:
            response = client.get(url, follow_redirects=True)
        else:
            headers = {"User-Agent": DEFAULT_USER_AGENT}
            with httpx.Client(
                timeout=DEFAULT_TIMEOUT,
                headers=headers,
                follow_redirects=True,
            ) as local_client:
                response = local_client.get(url)
    except (httpx.RequestError, httpx.HTTPError, TimeoutError, ConnectionError, OSError):
        return ("error", None)

    status_code = response.status_code

    # Check for unverified auth-walls (LinkedIn 403 or 999 anti-bot, login portals)
    if status_code == 999 or (status_code == 403 and _is_auth_wall(url)):
        return ("unverified", status_code)

    # Success / Redirect range
    if 200 <= status_code < 400:
        if _is_expired_content(response.text):
            return ("expired", status_code)
        return ("live", status_code)

    # Standard client and server errors
    if status_code >= 400:
        return ("dead", status_code)

    return ("live", status_code)


def _load_sources_yaml(sources_config: Union[Path, str]) -> list[dict[str, Any]]:
    """Loads and parses sources YAML file."""
    path = Path(sources_config)
    if not path.exists():
        raise FileNotFoundError(f"Sources config not found: {path}")

    content = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(content)
    else:  # pragma: no cover
        data = {}

    if not isinstance(data, dict):
        return []
    return data.get("sources", [])


def run_radar_collection(
    db: Database,
    sources_config: Union[Path, str] = "config/sources.yaml",
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """Runs a complete radar collection pass against configured voucher sources."""
    sources = _load_sources_yaml(sources_config)

    sources_checked = len(sources)
    certs_updated = 0
    events_recorded = 0
    activated_count = 0
    deactivated_count = 0
    liveness_changed_count = 0
    results: list[dict[str, Any]] = []

    for source in sources:
        source_id = source.get("id", "radar_feed")
        source_name = source.get("name", source_id)
        source_url = source.get("url")
        eligible_cert_ids = source.get("eligible_cert_ids", [])
        track = source.get("track", "official_voucher")

        if not source_url:
            continue

        status, status_code = check_liveness(source_url, client=client)
        source_result = {
            "source_id": source_id,
            "url": source_url,
            "status": status,
            "status_code": status_code,
            "eligible_certs": eligible_cert_ids,
        }
        results.append(source_result)

        for cert_id in eligible_cert_ids:
            cert = db.get_certification(cert_id)
            if cert is None:
                continue

            now_iso = datetime.now(timezone.utc).isoformat()
            old_active = cert.is_voucher_active
            old_liveness = cert.liveness_status

            # Derive target state from check result
            if status == "live":
                new_active = True if track == "official_voucher" else old_active
                new_liveness = "live"
            elif status in ("expired", "dead"):
                new_active = False
                new_liveness = status
            elif status == "unverified":
                new_active = old_active
                new_liveness = "unverified"
            else:  # "error"
                new_active = old_active
                new_liveness = "error"

            # Transition: liveness changed
            if new_liveness != old_liveness:
                cert.liveness_status = new_liveness
                event = VoucherEvent(
                    cert_id=cert.id,
                    source_name=source_name,
                    event_type="liveness_changed",
                    payload_json=json.dumps(
                        {
                            "old_liveness": old_liveness,
                            "new_liveness": new_liveness,
                            "url": source_url,
                            "status_code": status_code,
                        },
                        ensure_ascii=False,
                    ),
                    detected_at=now_iso,
                )
                db.record_event(event)
                events_recorded += 1
                liveness_changed_count += 1

            # Transition: activated
            if not old_active and new_active:
                cert.is_voucher_active = True
                cert.activation_epoch += 1
                event = VoucherEvent(
                    cert_id=cert.id,
                    source_name=source_name,
                    event_type="activated",
                    payload_json=json.dumps(
                        {
                            "url": source_url,
                            "status_code": status_code,
                            "activation_epoch": cert.activation_epoch,
                        },
                        ensure_ascii=False,
                    ),
                    detected_at=now_iso,
                )
                db.record_event(event)
                events_recorded += 1
                activated_count += 1
            # Transition: deactivated
            elif old_active and not new_active:
                cert.is_voucher_active = False
                event = VoucherEvent(
                    cert_id=cert.id,
                    source_name=source_name,
                    event_type="deactivated",
                    payload_json=json.dumps(
                        {
                            "url": source_url,
                            "status_code": status_code,
                            "reason": status,
                        },
                        ensure_ascii=False,
                    ),
                    detected_at=now_iso,
                )
                db.record_event(event)
                events_recorded += 1
                deactivated_count += 1

            cert.last_checked_at = now_iso
            db.upsert_certification(cert)
            certs_updated += 1

    return {
        "sources_checked": sources_checked,
        "certs_updated": certs_updated,
        "events_recorded": events_recorded,
        "activated": activated_count,
        "deactivated": deactivated_count,
        "liveness_changed": liveness_changed_count,
        "results": results,
    }
