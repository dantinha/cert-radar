"""Unified Command Line Interface for CertRadar.

Commands:
- serve: Start the local web dashboard and API server.
- check-radar: Run collection, calculate matching against profile, and dispatch alerts.
- sync-profile: Fetch candidate profile from career-ops and display consolidated data.
- setup-telegram: Interactive setup wizard for Telegram notifications.
- add-url: Add a manual certification or voucher URL to database.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any, Optional, Union

from cert_radar import collector, matcher, notifier, profile_bridge, server
from cert_radar.db import Database
from cert_radar.models import Certification

logger = logging.getLogger("cert_radar.cli")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "cert_radar.db"
DEFAULT_SEED_PATH = REPO_ROOT / "data" / "seed_catalog.json"
DEFAULT_SOURCES_PATH = REPO_ROOT / "config" / "sources.yaml"
DEFAULT_CAREER_OPS_DIR = Path("D:/Projetos/career-ops")


def _resolve_path(path_input: Union[Path, str], base_dir: Path = REPO_ROOT) -> Path:
    """Resolves path relative to base_dir if relative and not present in cwd."""
    p = Path(path_input)
    if p.exists() or p.is_absolute():
        return p
    candidate = base_dir / p
    if candidate.exists():
        return candidate
    return p


def load_env_file(env_path: Union[Path, str] = ".env") -> dict[str, str]:
    """Loads key-value pairs from .env into os.environ and returns a dict."""
    path = Path(env_path)
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read env file %s: %s", path, exc)
        return loaded

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            loaded[key] = val
            if key not in os.environ:
                os.environ[key] = val

    return loaded


def save_env_variables(
    vars_to_save: dict[str, str],
    env_path: Union[Path, str] = ".env",
) -> None:
    """Updates or appends environment variables in a .env file preserving structure."""
    path = Path(env_path)
    lines: list[str] = []
    keys_written = set()

    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
            for line in existing:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    k = k.strip()
                    if k in vars_to_save:
                        lines.append(f"{k}={vars_to_save[k]}")
                        keys_written.add(k)
                        continue
                lines.append(line)
        except Exception as exc:
            logger.warning("Failed reading existing .env file: %s", exc)

    for k, v in vars_to_save.items():
        if k not in keys_written:
            lines.append(f"{k}={v}")

    output = "\n".join(lines).strip() + "\n"
    path.write_text(output, encoding="utf-8")


def _handle_serve(args: argparse.Namespace) -> int:
    db_path = _resolve_path(args.db_path)
    print(f"Inicializando banco de dados ({db_path})...")
    db = Database(db_path=db_path)
    db.init_db()

    existing_certs = db.get_certifications()
    seed_path = _resolve_path(args.seed_path)
    if not existing_certs and seed_path.exists():
        print(f"[Seed] Catálogo vazio. Carregando certificações iniciais de {seed_path}...")
        count = collector.seed_initial_catalog(db, seed_path=seed_path)
        print(f"[Seed] {count} certificações carregadas com sucesso.")

    print(f"Iniciando servidor CertRadar em http://{args.host}:{args.port}...")
    server.run_server(
        db=db,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


def _handle_check_radar(args: argparse.Namespace) -> int:
    env_file = _resolve_path(args.env_file)
    load_env_file(env_file)

    db_path = _resolve_path(args.db_path)
    db = Database(db_path=db_path)
    db.init_db()

    sources_path = _resolve_path(args.sources)
    print(f"Executando coleta de radar a partir de {sources_path}...")
    collection_summary = collector.run_radar_collection(
        db=db,
        sources_config=sources_path,
    )

    existing_certs = db.get_certifications()
    seed_path = _resolve_path(DEFAULT_SEED_PATH)
    if not existing_certs and seed_path.exists():
        print(f"[Seed] Catálogo vazio. Inicializando a partir de {seed_path}...")
        collector.seed_initial_catalog(db, seed_path=seed_path)

    career_ops_path = _resolve_path(args.career_ops_dir)
    print(f"Carregando perfil do candidato de {career_ops_path}...")
    profile = profile_bridge.load_profile(career_ops_root=career_ops_path)

    print("Calculando matching e ranqueando oportunidades...")
    certs = db.get_certifications()
    ranked = matcher.rank_certifications(
        profile=profile,
        certs=certs,
        hide_redundant=False,
    )

    # Dispatch alerts if not dry-run
    alert_summary: dict[str, int] = {}
    if args.dry_run:
        print("[DRY-RUN] Modo de simulação ativado: alertas externos não foram enviados.")
    else:
        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        alert_summary = notifier.dispatch_alerts(
            db=db,
            scored_certs=ranked,
            min_score=args.min_score,
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
        )

    # Print tabular summary
    print("\n" + "=" * 105)
    print(f" {'SCORE':<5} | {'STATUS':<7} | {'PROVEDOR':<13} | {'TÍTULO':<35} | {'PRAZO':<10} | {'GAPS / MATCH'}")
    print("=" * 105)
    for cert, match in ranked:
        deadline_display = cert.deadline_at if cert.deadline_at else "Sem prazo"
        match_summary = "; ".join(match.match_reasons[:2]) if match.match_reasons else ""
        title_trunc = cert.title[:33] + ".." if len(cert.title) > 35 else cert.title
        prov_trunc = cert.provider[:11] + ".." if len(cert.provider) > 13 else cert.provider
        print(f" {match.score:<5} | {cert.liveness_status:<7} | {prov_trunc:<13} | {title_trunc:<35} | {deadline_display:<10} | {match_summary}")
    print("=" * 105)

    print(f"Fontes verificadas: {collection_summary.get('sources_checked', 0)} | Atualizadas: {collection_summary.get('certs_updated', 0)} | Eventos: {collection_summary.get('events_recorded', 0)}")
    if not args.dry_run:
        print(f"Alertas disparados: Windows: {alert_summary.get('windows_sent', 0)} | Telegram: {alert_summary.get('telegram_sent', 0)} | Ignorados (dedup): {alert_summary.get('skipped_dedup', 0)}")

    return 0


def _handle_sync_profile(args: argparse.Namespace) -> int:
    career_ops_path = _resolve_path(args.career_ops_dir)
    profile = profile_bridge.load_profile(career_ops_root=career_ops_path)
    print("=" * 65)
    print(f" Perfil do Candidato: {profile.full_name} ({profile.email})")
    print("=" * 65)
    print(f"Cargos-Alvo: {', '.join(profile.target_roles)}")
    print(f"Arquétipos Primários: {', '.join(profile.primary_archetypes)}")
    print(f"Total de Skills Conhecidas: {len(profile.known_skills)}")
    if profile.known_skills:
        print(f"Exemplos de Skills: {', '.join(profile.known_skills[:6])}")
    print(f"Gaps Extraídos ({len(profile.gaps)}):")
    for gap in profile.gaps:
        print(f"  • {gap}")
    if profile.existing_certifications:
        print(f"Certificações Atuais ({len(profile.existing_certifications)}):")
        for c in profile.existing_certifications:
            print(f"  ✓ {c}")
    print("=" * 65)
    return 0


def _handle_setup_telegram(args: argparse.Namespace) -> int:
    print("=" * 65)
    print(" Configuração do Alerta Telegram - CertRadar")
    print("=" * 65)
    print("Informe as credenciais do seu Bot Telegram para alertas em tempo real.\n")

    token = input("Digite o TELEGRAM_BOT_TOKEN: ").strip()
    chat_id = input("Digite o TELEGRAM_CHAT_ID: ").strip()

    if not token or not chat_id:
        print("Erro: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID são obrigatórios.")
        return 1

    env_path = Path(args.env_file)
    print(f"Salvando credenciais em {env_path}...")
    save_env_variables({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id}, env_path=env_path)
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    os.environ["TELEGRAM_CHAT_ID"] = chat_id

    print("Enviando mensagem de teste via Telegram...")
    test_msg = (
        "🚀 *CertRadar* configurado com sucesso!\n\n"
        "Notificações de novos vouchers e prazos críticos ativas para este chat."
    )
    success = notifier.send_telegram_alert(token=token, chat_id=chat_id, message=test_msg)

    if success:
        print("✓ Alerta de teste enviado com sucesso! Configuração salva em .env.")
        return 0
    else:
        print("✗ Falha ao enviar alerta de teste no Telegram. Verifique seu token e chat_id.")
        return 1


def _handle_add_url(args: argparse.Namespace) -> int:
    url = args.url.strip()
    print(f"Verificando liveness da URL: {url}...")
    liveness_status, status_code = collector.check_liveness(url)
    print(f"Status de Liveness: {liveness_status} (HTTP {status_code or 'N/A'})")

    title = args.title or ""
    if not title:
        title = f"Manual Cert ({url[:30]})"

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = f"cert-{int(datetime.now(timezone.utc).timestamp())}"

    now_iso = datetime.now(timezone.utc).isoformat()
    discount_pct = args.discount_pct if args.discount_pct is not None else (100 if args.cost_type == "voucher_100" else 0)
    cert = Certification(
        id=slug,
        title=title,
        provider=args.provider or "Custom",
        track=args.track or ("official_voucher" if discount_pct > 0 else "free_continuous"),
        cost_type=args.cost_type or "free",
        discount_pct=discount_pct,
        normal_price_usd=args.normal_price_usd,
        exam_code=args.exam_code,
        target_roles=args.target_roles or [],
        skills_covered=args.skills_covered or [],
        level=args.level or "associate",
        effort_hours=args.effort_hours,
        recruiter_signal=args.recruiter_signal,
        url=url,
        voucher_program_url=args.voucher_program_url,
        is_voucher_active=True if discount_pct > 0 or args.cost_type in ("free", "voucher_100") else False,
        deadline_at=args.deadline_at,
        liveness_status=liveness_status,
        source_kind="manual",
        last_checked_at=now_iso,
        notes=args.notes or "",
    )

    db_path = _resolve_path(args.db_path)
    db = Database(db_path=db_path)
    db.init_db()
    db.upsert_certification(cert)

    print(f"✓ Certificação '{cert.title}' cadastrada com sucesso! (ID: {cert.id}, Provedor: {cert.provider})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Builds and configures the argument parser for CertRadar CLI."""
    parser = argparse.ArgumentParser(
        prog="cert-radar",
        description="CertRadar: Sistema pessoal de curadoria, matching e radar contínuo de certificações e vouchers.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Comando a ser executado")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Inicia o servidor e painel web local")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Interface de rede (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8420, help="Porta HTTP do servidor (default: 8420)")
    serve_parser.add_argument("--no-browser", action="store_true", help="Não abre automaticamente o navegador padrão")
    serve_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help=f"Caminho do banco SQLite (default: {DEFAULT_DB_PATH})")
    serve_parser.add_argument("--seed-path", default=str(DEFAULT_SEED_PATH), help=f"Caminho do catálogo seed (default: {DEFAULT_SEED_PATH})")
    serve_parser.set_defaults(func=_handle_serve)

    # check-radar
    radar_parser = subparsers.add_parser("check-radar", help="Verifica fontes, ranqueia certificações e envia alertas")
    radar_parser.add_argument("--min-score", type=int, default=65, help="Pontuação mínima para disparo de alertas (default: 65)")
    radar_parser.add_argument("--dry-run", action="store_true", help="Modo simulação: não dispara alertas externos (Windows/Telegram)")
    radar_parser.add_argument("--sources", default=str(DEFAULT_SOURCES_PATH), help=f"Arquivo de fontes (default: {DEFAULT_SOURCES_PATH})")
    radar_parser.add_argument("--career-ops-dir", default=str(DEFAULT_CAREER_OPS_DIR), help=f"Diretório do career-ops (default: {DEFAULT_CAREER_OPS_DIR})")
    radar_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help=f"Caminho do banco SQLite (default: {DEFAULT_DB_PATH})")
    radar_parser.add_argument("--env-file", default=".env", help="Arquivo .env com variáveis de ambiente (default: .env)")
    radar_parser.set_defaults(func=_handle_check_radar)

    # sync-profile
    profile_parser = subparsers.add_parser("sync-profile", help="Lê e exibe dados consolidados do perfil do candidato")
    profile_parser.add_argument("--career-ops-dir", default=str(DEFAULT_CAREER_OPS_DIR), help=f"Diretório do career-ops (default: {DEFAULT_CAREER_OPS_DIR})")
    profile_parser.set_defaults(func=_handle_sync_profile)

    # setup-telegram
    telegram_parser = subparsers.add_parser("setup-telegram", help="Assistente interativo de configuração do Bot Telegram")
    telegram_parser.add_argument("--env-file", default=".env", help="Caminho do arquivo .env (default: .env)")
    telegram_parser.set_defaults(func=_handle_setup_telegram)

    # add-url
    add_parser = subparsers.add_parser("add-url", help="Adiciona manualmente uma URL de certificação ou voucher")
    add_parser.add_argument("url", help="URL oficial da certificação ou do voucher")
    add_parser.add_argument("--title", help="Título da certificação")
    add_parser.add_argument("--provider", default="Custom", help="Provedor (ex: Microsoft, Google Cloud, AWS)")
    add_parser.add_argument("--exam-code", help="Código oficial do exame (ex: AI-102, PL-300)")
    add_parser.add_argument("--cost-type", default="free", choices=["free", "voucher_100", "voucher_50", "paid"], help="Tipo de custo (default: free)")
    add_parser.add_argument("--track", choices=["official_voucher", "free_continuous"], help="Trilha da certificação")
    add_parser.add_argument("--discount-pct", type=int, default=None, help="Percentual de desconto (ex: 100)")
    add_parser.add_argument("--normal-price-usd", type=float, default=0.0, help="Preço normal em USD")
    add_parser.add_argument("--target-roles", nargs="*", default=[], help="Cargos-alvo relacionados")
    add_parser.add_argument("--skills-covered", nargs="*", default=[], help="Habilidades cobertas pelo exame")
    add_parser.add_argument("--level", default="associate", choices=["foundational", "associate", "specialty", "expert"], help="Nível da certificação")
    add_parser.add_argument("--effort-hours", type=int, default=15, help="Horas estimadas de estudo (default: 15)")
    add_parser.add_argument("--recruiter-signal", type=int, default=3, help="Sinal para recrutadores 1 a 5 (default: 3)")
    add_parser.add_argument("--voucher-program-url", help="URL do programa de voucher, se houver")
    add_parser.add_argument("--deadline-at", help="Data limite do voucher (YYYY-MM-DD)")
    add_parser.add_argument("--notes", default="", help="Anotações adicionais")
    add_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help=f"Caminho do banco SQLite (default: {DEFAULT_DB_PATH})")
    add_parser.set_defaults(func=_handle_add_url)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entrypoint for cert-radar."""
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)
