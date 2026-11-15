"""HTTP server and REST API backend for CertRadar."""

import http.server
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Optional, Union
from urllib.parse import parse_qs, urlparse
import webbrowser

from cert_radar.collector import check_liveness
from cert_radar.db import Database
from cert_radar.matcher import rank_certifications
from cert_radar.models import Certification
from cert_radar.profile_bridge import load_profile

logger = logging.getLogger(__name__)

DEFAULT_STATIC_DIR = Path(__file__).parent / "static"

# Ensure MIME types are properly registered
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("application/json", ".json")


class CertRadarRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom request handler serving CertRadar API and static SPA."""

    def __init__(
        self,
        request: Any,
        client_address: Any,
        server: Any,
        directory: Optional[Union[Path, str]] = None,
        db: Optional[Database] = None,
    ) -> None:
        self._custom_db = db
        static_path = directory or getattr(server, "static_dir", None) or DEFAULT_STATIC_DIR
        super().__init__(request, client_address, server, directory=str(static_path))

    @property
    def db(self) -> Optional[Database]:
        if self._custom_db is not None:
            return self._custom_db
        return getattr(self.server, "db", None)

    def log_message(self, format: str, *args: Any) -> None:
        """Redirect server log messages to standard logging."""
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status=status)

    def _drain_body(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(content_length)
        except Exception:
            pass

    def _read_json_body(self) -> Optional[dict[str, Any]]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                return None
            raw_body = self.rfile.read(content_length)
            return json.loads(raw_body.decode("utf-8"))
        except Exception:
            return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            if path == "/api/profile":
                self._handle_get_profile()
            elif path == "/api/certs":
                self._handle_get_certs()
            elif path in ("/api/progress", "/api/add-url", "/api/generate-snippet", "/api/open-url"):
                self._send_error_json("Method Not Allowed", status=405)
            else:
                self._send_error_json("Endpoint not found", status=404)
            return

        # Static assets
        if path == "/" or path == "":
            self.path = "/index.html"

        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            if path == "/api/progress":
                self._handle_post_progress()
            elif path == "/api/add-url":
                self._handle_post_add_url()
            elif path == "/api/generate-snippet":
                self._handle_post_generate_snippet()
            elif path == "/api/open-url":
                self._handle_post_open_url()
            elif path in ("/api/profile", "/api/certs"):
                self._drain_body()
                self._send_error_json("Method Not Allowed", status=405)
            else:
                self._drain_body()
                self._send_error_json("Endpoint not found", status=404)
            return

        self._drain_body()
        self._send_error_json("Method Not Allowed", status=405)

    def do_PUT(self) -> None:
        self._send_error_json("Method Not Allowed", status=405)

    def do_DELETE(self) -> None:
        self._send_error_json("Method Not Allowed", status=405)

    def _handle_get_profile(self) -> None:
        try:
            profile = load_profile()
            data = profile.model_dump()
            data["skills_count"] = len(profile.known_skills)
            data["gaps_count"] = len(profile.gaps)
            self._send_json(data, status=200)
        except Exception as e:
            logger.exception("Error loading profile")
            self._send_error_json(f"Error loading profile: {e}", status=500)

    def _handle_get_certs(self) -> None:
        try:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            hide_redundant_str = params.get("hide_redundant", ["false"])[0].lower()
            hide_redundant = hide_redundant_str in ("true", "1", "yes")

            db = self.db
            if not db:
                self._send_error_json("Database not configured", status=500)
                return

            profile = load_profile()
            certs = db.get_certifications()
            ranked = rank_certifications(profile, certs, hide_redundant=hide_redundant)

            results = []
            for cert, result in ranked:
                prog = db.get_user_progress(cert.id)
                cert_dict = cert.model_dump()
                cert_dict["score"] = result.score
                cert_dict["score_breakdown"] = {
                    "role_score": result.role_score,
                    "gap_score": result.gap_score,
                    "signal_score": result.signal_score,
                    "cost_score": result.cost_score,
                }
                cert_dict["match_reasons"] = result.match_reasons
                cert_dict["redundancy_warning"] = result.redundancy_warning
                cert_dict["is_redundant"] = result.is_redundant
                cert_dict["user_progress"] = {
                    "status": prog.status if prog else "radar",
                    "user_notes": prog.user_notes if prog else "",
                    "updated_at": prog.updated_at if prog else None,
                }
                results.append(cert_dict)

            self._send_json(results, status=200)
        except Exception as e:
            logger.exception("Error listing certifications")
            self._send_error_json(f"Error fetching certifications: {e}", status=500)

    def _handle_post_progress(self) -> None:
        body = self._read_json_body()
        if not body or not isinstance(body, dict):
            self._send_error_json("Invalid or missing JSON payload", status=400)
            return

        cert_id = body.get("cert_id")
        status = body.get("status")
        notes = body.get("notes", "")

        if not cert_id or not isinstance(cert_id, str):
            self._send_error_json("Field 'cert_id' is required and must be a string", status=400)
            return

        valid_statuses = {"radar", "saved", "studying", "completed", "ignored"}
        if not status or status not in valid_statuses:
            self._send_error_json(f"Field 'status' must be one of {sorted(valid_statuses)}", status=400)
            return

        db = self.db
        if not db:
            self._send_error_json("Database not configured", status=500)
            return

        db.set_user_progress(cert_id=cert_id, status=status, notes=notes or "")
        self._send_json({"success": True}, status=200)

    def _handle_post_add_url(self) -> None:
        body = self._read_json_body()
        if not body or not isinstance(body, dict):
            self._send_error_json("Invalid or missing JSON payload", status=400)
            return

        db = self.db
        if not db:
            self._send_error_json("Database not configured", status=500)
            return

        url = body.get("url")
        title = body.get("title")
        if not url or not isinstance(url, str) or not url.strip():
            self._send_error_json("Field 'url' is required", status=400)
            return
        if not title or not isinstance(title, str) or not title.strip():
            self._send_error_json("Field 'title' is required", status=400)
            return

        # Slugify title
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if not slug:
            slug = f"cert-{int(datetime.now(timezone.utc).timestamp())}"

        # Liveness check
        liveness_status, _ = check_liveness(url)

        cert_id = body.get("id") or slug
        provider = body.get("provider", "Custom")
        track = body.get("track", "official_voucher" if int(body.get("discount_pct", 0)) > 0 else "free_continuous")
        cost_type = body.get("cost_type", "free")
        discount_pct = int(body.get("discount_pct", 0))
        normal_price_usd = float(body.get("normal_price_usd", 0.0))
        exam_code = body.get("exam_code")
        target_roles = body.get("target_roles", [])
        skills_covered = body.get("skills_covered", [])
        level = body.get("level", "associate")
        effort_hours = int(body.get("effort_hours", 10))
        recruiter_signal = int(body.get("recruiter_signal", 3))
        voucher_program_url = body.get("voucher_program_url")
        is_voucher_active = bool(body.get("is_voucher_active", True if discount_pct > 0 else False))
        deadline_at = body.get("deadline_at")
        notes = body.get("notes", "")

        now_iso = datetime.now(timezone.utc).isoformat()
        cert = Certification(
            id=cert_id,
            title=title,
            provider=provider,
            track=track,
            cost_type=cost_type,
            discount_pct=discount_pct,
            normal_price_usd=normal_price_usd,
            exam_code=exam_code,
            target_roles=target_roles,
            skills_covered=skills_covered,
            level=level,
            effort_hours=effort_hours,
            recruiter_signal=recruiter_signal,
            url=url,
            voucher_program_url=voucher_program_url,
            is_voucher_active=is_voucher_active,
            deadline_at=deadline_at,
            liveness_status=liveness_status,
            source_kind="manual",
            last_checked_at=now_iso,
            notes=notes,
        )

        db = self.db
        if not db:
            self._send_error_json("Database not configured", status=500)
            return

        db.upsert_certification(cert)
        self._send_json(cert.model_dump(), status=200)

    def _handle_post_generate_snippet(self) -> None:
        body = self._read_json_body()
        if not body or not isinstance(body, dict):
            self._send_error_json("Invalid or missing JSON payload", status=400)
            return

        cert_id = body.get("cert_id")
        if not cert_id or not isinstance(cert_id, str):
            self._send_error_json("Field 'cert_id' is required", status=400)
            return

        db = self.db
        if not db:
            self._send_error_json("Database not configured", status=500)
            return

        cert = db.get_certification(cert_id)
        if not cert:
            self._send_error_json("Certification not found", status=404)
            return

        year = datetime.now().year
        today_iso = datetime.now().strftime("%Y-%m-%d")
        exam_part = f" ({cert.exam_code})" if cert.exam_code else ""
        cv_snippet = f"- **{cert.title}**{exam_part} — {cert.provider} ({year})"

        skills_list = (
            "\n".join([f"  - {s}" for s in cert.skills_covered])
            if cert.skills_covered
            else "  - Competências técnicas oficiais validadas."
        )

        obsidian_snippet = f"""---
data_criacao: {today_iso}
tipo: certificacao
projeto: "[[CertRadar]]"
provedor: "{cert.provider}"
status: concluida
tags:
  - certificacao
  - segundo-cerebro
  - carreira
---

# {cert.title}

## 📜 Detalhes da Certificação
- **Provedor:** {cert.provider}
- **Exame / Código:** {cert.exam_code or "N/A"}
- **Trilha:** {cert.track}
- **URL Oficial:** {cert.url}

## 🎯 Competências Validadas
{skills_list}

## 📝 Notas e Conclusão
- Certificação concluída com sucesso via CertRadar.
"""

        self._send_json(
            {
                "cv_snippet": cv_snippet,
                "obsidian_snippet": obsidian_snippet.strip(),
            },
            status=200,
        )

    def _handle_post_open_url(self) -> None:
        body = self._read_json_body()
        if not body or not isinstance(body, dict):
            self._send_error_json("Invalid JSON body", status=400)
            return

        url = str(body.get("url", "")).strip()
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            self._send_error_json("Valid http/https url is required", status=400)
            return

        try:
            webbrowser.open(url, new=2)
            self._send_json({"success": True, "url": url}, status=200)
        except Exception as e:
            logger.exception("Error opening URL in browser")
            self._send_error_json(f"Error opening URL: {e}", status=500)


def create_server(
    db: Database,
    host: str = "127.0.0.1",
    port: int = 8000,
    static_dir: Optional[Union[Path, str]] = None,
) -> ThreadingHTTPServer:
    """Creates a ThreadingHTTPServer configured with database and static directory."""
    server = ThreadingHTTPServer((host, port), CertRadarRequestHandler)
    server.db = db  # type: ignore[attr-defined]
    server.static_dir = Path(static_dir) if static_dir else DEFAULT_STATIC_DIR  # type: ignore[attr-defined]
    return server


def run_server(
    db: Database,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = False,
    static_dir: Optional[Union[Path, str]] = None,
) -> None:
    """Launches the CertRadar local server and optionally opens a web browser."""
    server = create_server(db=db, host=host, port=port, static_dir=static_dir)
    url = f"http://{host}:{port}"
    logger.info(f"CertRadar server running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user interrupt")
    finally:
        server.shutdown()
        server.server_close()
