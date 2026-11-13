"""Notification service for CertRadar with anti-spam deduplication.

Dispatches actionable alerts via Windows Toast notifications and Telegram Bot,
strictly guarding against duplicate messages using composite deduplication keys
and campaign activation epochs.
"""

from datetime import date, datetime, timezone
import logging
import re
import subprocess
import sys
from typing import Optional, Union

import httpx

from cert_radar.db import Database
from cert_radar.matcher import MatchResult
from cert_radar.models import Certification

logger = logging.getLogger(__name__)


def generate_dedup_key(
    cert_id: str,
    alert_type: str,
    activation_epoch: int,
    deadline_at: Optional[str],
    channel: str,
) -> str:
    """Generates a composite anti-spam deduplication key.

    Format: {cert_id}:{alert_type}:{activation_epoch}:{deadline_at or 'none'}:{channel}
    """
    clean_deadline = deadline_at.strip() if deadline_at and deadline_at.strip() else "none"
    return f"{cert_id}:{alert_type}:{activation_epoch}:{clean_deadline}:{channel}"


def build_alert_message(
    cert: Certification,
    match: MatchResult,
    alert_type: str,
) -> str:
    """Builds a formatted Markdown alert notification message for Telegram or desktop displays."""
    if alert_type == "expiring_48h":
        header = "🚨 *[URGENTE - EXPIRA EM 48H] Certificação & Voucher Detectado!*"
    elif alert_type == "expiring_7d":
        header = "⏰ *[EXPIRA EM BREVE - 7 DIAS] Certificação & Voucher Detectado!*"
    else:
        header = "🎯 *[NOVA OPORTUNIDADE] Certificação com Acesso Gratuito/Voucher!*"

    # Cost / voucher breakdown
    if cert.cost_type == "voucher_100":
        cost_info = "100% Grátis (Voucher de 100% OFF)"
    elif cert.cost_type == "free":
        cost_info = "100% Grátis (Acesso Gratuito Contínuo)"
    elif cert.cost_type == "voucher_discount":
        cost_info = f"Desconto de {cert.discount_pct}% OFF (Preço normal: ${cert.normal_price_usd:.0f})"
    elif cert.cost_type == "scholarship":
        cost_info = "Bolsa de Estudos / Scholarship"
    else:
        cost_info = cert.cost_type

    # Deadline information
    if cert.deadline_at:
        if alert_type == "expiring_48h":
            deadline_info = f"⚠️ *Prazo Final:* `{cert.deadline_at}` (Restam menos de 48 horas!)"
        else:
            deadline_info = f"📅 *Prazo:* `{cert.deadline_at}`"
    else:
        deadline_info = "📅 *Prazo:* Contínuo / Não especificado"

    # Score breakdown
    score_info = f"📊 *Fit Score:* {match.score}/100"
    breakdown = (
        f"• Alinhamento de Carreira: {match.role_score}/35\n"
        f"• Fechamento de Gaps: {match.gap_score}/25\n"
        f"• Sinal de Mercado: {match.signal_score}/20\n"
        f"• Urgência/Custo: {match.cost_score}/20"
    )

    # Highlight reasons or gaps
    reasons_block = ""
    if match.match_reasons:
        reasons_list = "\n".join(f"  - {r}" for r in match.match_reasons[:3])
        reasons_block = f"\n💡 *Motivos de Destaque:*\n{reasons_list}"

    target_url = cert.voucher_program_url or cert.url

    message = (
        f"{header}\n\n"
        f"🏆 *{cert.title}*\n"
        f"🏢 Provedor: {cert.provider}\n"
        f"🏷️ Exame: `{cert.exam_code or 'N/A'}`\n"
        f"💰 Condição: {cost_info}\n"
        f"{deadline_info}\n\n"
        f"{score_info}\n"
        f"{breakdown}"
        f"{reasons_block}\n\n"
        f"🔗 *Resgate direto:* {target_url}"
    )
    return message


def _clean_toast_text(text: str) -> str:
    """Strips Markdown markers for plain desktop notifications."""
    cleaned = re.sub(r"[*_`]", "", text)
    return cleaned.strip()


def send_windows_toast(title: str, message: str, url: str) -> bool:
    """Sends a native Windows Toast notification.

    Attempts to use `winotify` first. If unavailable or fails, executes
    a safe PowerShell script via Windows Runtime Toast API. Returns True
    on success, False otherwise without raising exceptions.
    """
    clean_title = _clean_toast_text(title)
    clean_msg = _clean_toast_text(message)

    # 1. Try winotify if installed and available
    try:
        import winotify

        if hasattr(winotify, "Notification"):
            toast = winotify.Notification(
                app_id="CertRadar",
                title=clean_title,
                msg=clean_msg[:250],
                launch=url,
            )
            toast.show()
            return True
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("winotify notification failed: %s; falling back to PowerShell", exc)

    # 2. Safe PowerShell fallback
    try:
        ps_script = """
        param([string]$toastTitle, [string]$toastMsg, [string]$launchUrl)
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $textNodes = $template.GetElementsByTagName("text")
        $textNodes.Item(0).AppendChild($template.CreateTextNode($toastTitle)) > $null
        $textNodes.Item(1).AppendChild($template.CreateTextNode($toastMsg)) > $null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("CertRadar")
        $notifier.Show($toast)
        """
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script,
            clean_title,
            clean_msg[:250],
            url,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception as exc:
        logger.warning("PowerShell toast notification fallback failed: %s", exc)
        return False


def send_telegram_alert(
    token: str,
    chat_id: str,
    message: str,
    client: Optional[httpx.Client] = None,
) -> bool:
    """Dispatches a Markdown alert message to Telegram Bot sendMessage API."""
    if not token or not chat_id:
        logger.warning("Telegram token or chat_id is missing.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        if client is not None:
            response = client.post(url, json=payload, timeout=10.0)
        else:
            with httpx.Client(timeout=10.0) as default_client:
                response = default_client.post(url, json=payload)

        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                return True
            logger.warning("Telegram API returned 200 with ok=False: %s", data)
            return False
        else:
            logger.warning(
                "Telegram API error HTTP %d: %s",
                response.status_code,
                response.text,
            )
            return False
    except httpx.HTTPError as exc:
        logger.warning("HTTP error sending Telegram alert: %s", exc)
        return False
    except Exception as exc:
        logger.warning("Unexpected error sending Telegram alert: %s", exc)
        return False


def _parse_deadline_datetime(deadline_str: Optional[str]) -> Optional[datetime]:
    """Parses ISO date or datetime string into a UTC datetime."""
    if not deadline_str:
        return None
    try:
        cleaned = deadline_str.strip()
        if len(cleaned) == 10 and "T" not in cleaned:
            # Full day deadline: expires at end of day UTC
            return datetime.fromisoformat(cleaned).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _determine_alert_type(
    deadline_at: Optional[str],
    reference_date: Optional[Union[date, datetime]] = None,
) -> str:
    """Classifies notification urgency: expiring_48h, expiring_7d, or new_voucher."""
    if not deadline_at:
        return "new_voucher"

    if reference_date is None:
        ref_dt = datetime.now(timezone.utc)
    elif isinstance(reference_date, datetime):
        if reference_date.tzinfo is None:
            ref_dt = reference_date.replace(tzinfo=timezone.utc)
        else:
            ref_dt = reference_date
    elif isinstance(reference_date, date):
        ref_dt = datetime(
            reference_date.year,
            reference_date.month,
            reference_date.day,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        )
    else:
        ref_dt = datetime.now(timezone.utc)

    deadline_dt = _parse_deadline_datetime(deadline_at)
    if deadline_dt is None:
        return "new_voucher"

    diff = deadline_dt - ref_dt
    diff_seconds = diff.total_seconds()

    if 0 <= diff_seconds <= 48 * 3600:
        return "expiring_48h"
    elif 48 * 3600 < diff_seconds <= 7 * 86400:
        return "expiring_7d"
    else:
        return "new_voucher"


def dispatch_alerts(
    db: Database,
    scored_certs: list[tuple[Certification, MatchResult]],
    min_score: int = 65,
    telegram_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    reference_date: Optional[Union[date, datetime]] = None,
    client: Optional[httpx.Client] = None,
    enable_windows: bool = True,
) -> dict[str, int]:
    """Evaluates candidates, dedupes against database history, and delivers notifications.

    Filters criteria:
    - is_voucher_active is True
    - liveness_status == 'live'
    - match.score >= min_score OR progress.status == 'saved'

    Deduplication:
    - Uses composite key per channel & activation epoch.
    - If already sent in database, increments skipped_dedup and skips delivery.
    - If successfully delivered, logs in database alert_log.

    Returns:
        dict: {"windows_sent": int, "telegram_sent": int, "skipped_dedup": int}
    """
    windows_sent = 0
    telegram_sent = 0
    skipped_dedup = 0

    active_channels: list[str] = []
    if enable_windows:
        active_channels.append("windows")
    if telegram_token and telegram_chat_id:
        active_channels.append("telegram")

    if not active_channels:
        return {
            "windows_sent": 0,
            "telegram_sent": 0,
            "skipped_dedup": 0,
        }

    for cert, match in scored_certs:
        # 1. Strict health and activity filters
        if not cert.is_voucher_active:
            continue
        if cert.liveness_status != "live":
            continue

        # 2. Check score threshold or user saved bookmark
        progress = db.get_user_progress(cert.id)
        is_saved = progress is not None and progress.status == "saved"
        if match.score < min_score and not is_saved:
            continue

        # 3. Urgency detection
        alert_type = _determine_alert_type(cert.deadline_at, reference_date)

        # 4. Message formulation
        message = build_alert_message(cert, match, alert_type)
        title = f"CertRadar: {cert.title}"
        target_url = cert.voucher_program_url or cert.url

        # 5. Dispatch per active channel with deduplication check
        for channel in active_channels:
            dedup_key = generate_dedup_key(
                cert_id=cert.id,
                alert_type=alert_type,
                activation_epoch=cert.activation_epoch,
                deadline_at=cert.deadline_at,
                channel=channel,
            )

            if db.has_alert_been_sent(dedup_key):
                skipped_dedup += 1
                continue

            success = False
            if channel == "windows":
                success = send_windows_toast(title, message, target_url)
                if success:
                    db.log_alert(cert.id, "windows", alert_type, dedup_key, status="sent")
                    windows_sent += 1
            elif channel == "telegram":
                assert telegram_token is not None and telegram_chat_id is not None
                success = send_telegram_alert(
                    token=telegram_token,
                    chat_id=telegram_chat_id,
                    message=message,
                    client=client,
                )
                if success:
                    db.log_alert(cert.id, "telegram", alert_type, dedup_key, status="sent")
                    telegram_sent += 1

    return {
        "windows_sent": windows_sent,
        "telegram_sent": telegram_sent,
        "skipped_dedup": skipped_dedup,
    }
