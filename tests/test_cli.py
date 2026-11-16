"""Tests for the CertRadar command-line interface (CLI)."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cert_radar.cli import (
    build_parser,
    load_env_file,
    main,
    save_env_variables,
)
from cert_radar.db import Database
from cert_radar.matcher import MatchResult
from cert_radar.models import CandidateProfile, Certification


@pytest.fixture
def sample_profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Gabriel Tester",
        email="gabriel@example.com",
        target_roles=["AI Product Manager", "Context Engineer"],
        primary_archetypes=["Builder", "Strategist"],
        known_skills=["Python", "FastAPI", "Prompt Engineering"],
        gaps=["MLOps pipelines", "RAG evaluation with RAGAS"],
        existing_certifications=["AWS Certified Cloud Practitioner"],
    )


@pytest.fixture
def sample_cert() -> Certification:
    return Certification(
        id="cert-ai-eng",
        title="Azure AI Engineer Associate",
        provider="Microsoft",
        track="official_voucher",
        cost_type="voucher_100",
        discount_pct=100,
        normal_price_usd=165.0,
        exam_code="AI-102",
        target_roles=["AI Product Manager", "AI Engineer"],
        skills_covered=["Azure AI", "MLOps pipelines", "Cognitive Services"],
        level="associate",
        effort_hours=25,
        recruiter_signal=4,
        url="https://learn.microsoft.com/en-us/credentials/certifications/azure-ai-engineer/",
        voucher_program_url="https://microsoft.com/cloud-skills-challenge",
        is_voucher_active=True,
        deadline_at="2026-12-31",
        liveness_status="live",
        source_kind="official_feed",
    )


@pytest.fixture
def sample_match(sample_cert: Certification) -> MatchResult:
    return MatchResult(
        cert_id=sample_cert.id,
        score=91,
        role_score=30,
        gap_score=25,
        signal_score=16,
        cost_score=20,
        match_reasons=[
            "Alinhamento direto com o cargo-alvo AI Product Manager",
            "Fecha o gap real MLOps pipelines",
        ],
        redundancy_warning=None,
        is_redundant=False,
    )


def test_build_parser():
    parser = build_parser()
    assert parser.prog == "cert-radar"
    subparsers_actions = [
        action
        for action in parser._actions
        if action.__class__.__name__ == "_SubParsersAction"
    ]
    assert len(subparsers_actions) == 1
    subparser = subparsers_actions[0]
    expected_cmds = {"serve", "check-radar", "sync-profile", "setup-telegram", "add-url"}
    assert expected_cmds.issubset(set(subparser.choices.keys()))


def test_main_no_args_prints_help(capsys):
    ret = main([])
    assert ret == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "cert-radar" in captured.out


def test_main_help_flag(capsys):
    ret = main(["--help"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "cert-radar" in captured.out


def test_main_invalid_command(capsys):
    ret = main(["invalid-command-xyz"])
    assert ret != 0


def test_serve_subcommand_starts_server_and_seeds(tmp_path: Path):
    db_file = tmp_path / "test_radar.db"
    seed_file = tmp_path / "seed.json"
    seed_file.write_text("[]", encoding="utf-8")

    with patch("cert_radar.cli.Database") as mock_db_cls, \
         patch("cert_radar.cli.collector.seed_initial_catalog") as mock_seed, \
         patch("cert_radar.cli.server.run_server") as mock_run_server:

        mock_db = MagicMock(spec=Database)
        mock_db.get_certifications.return_value = []
        mock_db_cls.return_value = mock_db

        ret = main([
            "serve",
            "--host", "0.0.0.0",
            "--port", "8420",
            "--no-browser",
            "--db-path", str(db_file),
            "--seed-path", str(seed_file),
        ])

        assert ret == 0
        mock_db.init_db.assert_called_once()
        mock_seed.assert_called_once_with(mock_db, seed_path=seed_file)
        mock_run_server.assert_called_once_with(
            db=mock_db,
            host="0.0.0.0",
            port=8420,
            open_browser=False,
        )


def test_serve_subcommand_skips_seed_if_already_populated(tmp_path: Path, sample_cert: Certification):
    db_file = tmp_path / "test_radar.db"

    with patch("cert_radar.cli.Database") as mock_db_cls, \
         patch("cert_radar.cli.collector.seed_initial_catalog") as mock_seed, \
         patch("cert_radar.cli.server.run_server") as mock_run_server:

        mock_db = MagicMock(spec=Database)
        mock_db.get_certifications.return_value = [sample_cert]
        mock_db_cls.return_value = mock_db

        ret = main([
            "serve",
            "--db-path", str(db_file),
        ])

        assert ret == 0
        mock_seed.assert_not_called()
        mock_run_server.assert_called_once_with(
            db=mock_db,
            host="127.0.0.1",
            port=8420,
            open_browser=True,
        )


def test_check_radar_normal(
    sample_profile: CandidateProfile,
    sample_cert: Certification,
    sample_match: MatchResult,
    capsys,
):
    with patch("cert_radar.cli.Database") as mock_db_cls, \
         patch("cert_radar.cli.collector.run_radar_collection") as mock_collect, \
         patch("cert_radar.cli.profile_bridge.load_profile") as mock_load_profile, \
         patch("cert_radar.cli.matcher.rank_certifications") as mock_rank, \
         patch("cert_radar.cli.notifier.dispatch_alerts") as mock_dispatch, \
         patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok123", "TELEGRAM_CHAT_ID": "chat456"}):

        mock_db = MagicMock(spec=Database)
        mock_db.get_certifications.return_value = [sample_cert]
        mock_db_cls.return_value = mock_db

        mock_collect.return_value = {
            "sources_checked": 3,
            "certs_updated": 1,
            "events_recorded": 1,
        }
        mock_load_profile.return_value = sample_profile
        mock_rank.return_value = [(sample_cert, sample_match)]
        mock_dispatch.return_value = {
            "windows_sent": 1,
            "telegram_sent": 1,
            "skipped_dedup": 0,
        }

        ret = main(["check-radar", "--min-score", "80"])
        assert ret == 0

        mock_collect.assert_called_once()
        mock_load_profile.assert_called_once()
        mock_rank.assert_called_once()
        mock_dispatch.assert_called_once()

        captured = capsys.readouterr()
        assert "Azure AI Engineer Associate" in captured.out
        assert "Microsoft" in captured.out
        assert "91" in captured.out
        assert "Fontes verificadas: 3" in captured.out


def test_check_radar_dry_run(
    sample_profile: CandidateProfile,
    sample_cert: Certification,
    sample_match: MatchResult,
    capsys,
):
    with patch("cert_radar.cli.Database") as mock_db_cls, \
         patch("cert_radar.cli.collector.run_radar_collection") as mock_collect, \
         patch("cert_radar.cli.profile_bridge.load_profile") as mock_load_profile, \
         patch("cert_radar.cli.matcher.rank_certifications") as mock_rank, \
         patch("cert_radar.cli.notifier.dispatch_alerts") as mock_dispatch:

        mock_db = MagicMock(spec=Database)
        mock_db.get_certifications.return_value = [sample_cert]
        mock_db_cls.return_value = mock_db

        mock_collect.return_value = {
            "sources_checked": 2,
            "certs_updated": 0,
            "events_recorded": 0,
        }
        mock_load_profile.return_value = sample_profile
        mock_rank.return_value = [(sample_cert, sample_match)]

        ret = main(["check-radar", "--dry-run"])
        assert ret == 0

        mock_dispatch.assert_not_called()
        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out
        assert "Azure AI Engineer" in captured.out


def test_sync_profile(sample_profile: CandidateProfile, capsys):
    with patch("cert_radar.cli.profile_bridge.load_profile") as mock_load:
        mock_load.return_value = sample_profile

        ret = main(["sync-profile", "--career-ops-dir", "custom/career-ops"])
        assert ret == 0
        mock_load.assert_called_once()
        assert "custom/career-ops" in str(mock_load.call_args[1]["career_ops_root"]).replace("\\", "/")

        captured = capsys.readouterr()
        assert "Gabriel Tester" in captured.out
        assert "gabriel@example.com" in captured.out
        assert "AI Product Manager" in captured.out
        assert "MLOps pipelines" in captured.out
        assert "3" in captured.out  # known_skills length


def test_setup_telegram_success(tmp_path: Path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    inputs = iter(["my-bot-token-123", "my-chat-id-789"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with patch("cert_radar.cli.notifier.send_telegram_alert") as mock_alert:
        mock_alert.return_value = True

        ret = main(["setup-telegram", "--env-file", str(env_file)])
        assert ret == 0

        mock_alert.assert_called_once()
        assert mock_alert.call_args[1]["token"] == "my-bot-token-123"
        assert mock_alert.call_args[1]["chat_id"] == "my-chat-id-789"

        env_content = env_file.read_text(encoding="utf-8")
        assert "TELEGRAM_BOT_TOKEN=my-bot-token-123" in env_content
        assert "TELEGRAM_CHAT_ID=my-chat-id-789" in env_content

        captured = capsys.readouterr()
        assert "sucesso" in captured.out.lower()


def test_setup_telegram_failure_sending_alert(tmp_path: Path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    inputs = iter(["invalid-token", "invalid-chat-id"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with patch("cert_radar.cli.notifier.send_telegram_alert") as mock_alert:
        mock_alert.return_value = False

        ret = main(["setup-telegram", "--env-file", str(env_file)])
        assert ret == 1

        captured = capsys.readouterr()
        assert "falha" in captured.out.lower() or "verifique" in captured.out.lower()


def test_setup_telegram_empty_input(tmp_path: Path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    inputs = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    ret = main(["setup-telegram", "--env-file", str(env_file)])
    assert ret == 1

    captured = capsys.readouterr()
    assert "obrigat" in captured.out.lower()


def test_add_url_command(tmp_path: Path, capsys):
    db_file = tmp_path / "radar.db"

    with patch("cert_radar.cli.collector.check_liveness") as mock_liveness:
        mock_liveness.return_value = ("live", 200)

        ret = main([
            "add-url",
            "https://learn.microsoft.com/credentials/certifications/azure-ai-engineer",
            "--title", "Azure AI Engineer Associate",
            "--provider", "Microsoft",
            "--exam-code", "AI-102",
            "--cost-type", "voucher_100",
            "--db-path", str(db_file),
        ])

        assert ret == 0
        mock_liveness.assert_called_once_with("https://learn.microsoft.com/credentials/certifications/azure-ai-engineer")

        # Verify database record
        db = Database(db_path=db_file)
        certs = db.get_certifications()
        db.close()
        assert len(certs) == 1
        assert certs[0].title == "Azure AI Engineer Associate"
        assert certs[0].provider == "Microsoft"
        assert certs[0].exam_code == "AI-102"
        assert certs[0].liveness_status == "live"

        captured = capsys.readouterr()
        assert "cadastrada com sucesso" in captured.out.lower()


def test_env_helpers(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("# Existing comment\nOTHER_KEY=123\n", encoding="utf-8")

    save_env_variables({"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": "456"}, env_path=env_path)
    loaded = load_env_file(env_path)

    assert loaded["OTHER_KEY"] == "123"
    assert loaded["TELEGRAM_BOT_TOKEN"] == "abc"
    assert loaded["TELEGRAM_CHAT_ID"] == "456"

    # Update existing key
    save_env_variables({"TELEGRAM_CHAT_ID": "789"}, env_path=env_path)
    reloaded = load_env_file(env_path)
    assert reloaded["TELEGRAM_CHAT_ID"] == "789"
    assert reloaded["TELEGRAM_BOT_TOKEN"] == "abc"
    assert reloaded["OTHER_KEY"] == "123"


def test_env_helpers_edge_cases(tmp_path: Path):
    # Non-existent file
    assert load_env_file(tmp_path / "missing.env") == {}

    # File that raises on read
    unreadable = tmp_path / "bad.env"
    unreadable.write_text("A=1", encoding="utf-8")
    original_read_text = Path.read_text

    def selective_read_text(self, *args, **kwargs):
        if str(self) == str(unreadable):
            raise PermissionError("denied")
        return original_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", selective_read_text):
        assert load_env_file(unreadable) == {}
        # save_env_variables with read error still proceeds to write
        save_env_variables({"FOO": "BAR"}, env_path=unreadable)
        assert "FOO=BAR" in original_read_text(unreadable, encoding="utf-8")


def test_main_default_argv(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cert-radar"])
    ret = main()
    assert ret == 0


def test_main_module_execution():
    import runpy
    with patch("cert_radar.cli.main", return_value=0) as mock_cli_main:
        with patch("sys.exit") as mock_exit:
            runpy.run_module("cert_radar", run_name="__main__")
            mock_exit.assert_called_with(0)


def test_add_url_without_explicit_title(tmp_path: Path):
    db_file = tmp_path / "radar2.db"
    with patch("cert_radar.cli.collector.check_liveness", return_value=("live", 200)):
        ret = main([
            "add-url",
            "https://test.com/exam-1",
            "--db-path", str(db_file),
        ])
        assert ret == 0
        db = Database(db_path=db_file)
        certs = db.get_certifications()
        db.close()
        assert len(certs) == 1
        assert "exam-1" in certs[0].id or "manual" in certs[0].title.lower()


def test_serve_cloud_env_vars_resolution(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("CERT_RADAR_DB_PATH", "/data/cert_radar.db")
    parser = build_parser()
    args = parser.parse_args(["serve", "--no-browser"])
    assert args.host == "0.0.0.0"
    assert args.port == 10000
    assert args.db_path == "/data/cert_radar.db"


def test_sync_profile_export_snapshot(tmp_path: Path, sample_profile: CandidateProfile, capsys):
    snap_out = tmp_path / "profile_snapshot.json"
    with patch("cert_radar.cli.profile_bridge.load_profile", return_value=sample_profile):
        ret = main([
            "sync-profile",
            "--career-ops-dir", str(tmp_path),
            "--export",
            "--snapshot-path", str(snap_out),
        ])
        assert ret == 0
        assert snap_out.is_file()
        captured = capsys.readouterr()
        assert "Snapshot de nuvem salvo em" in captured.out


