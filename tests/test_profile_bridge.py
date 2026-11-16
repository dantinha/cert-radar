import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from cert_radar.models import CandidateProfile
from cert_radar.profile_bridge import (
    extract_cv_certifications,
    extract_gaps_from_reports,
    load_profile,
    normalize_certification_tokens,
    parse_profile_yaml,
    run_upskill,
)


@pytest.fixture
def mock_career_ops(tmp_path: Path) -> Path:
    """Creates a realistic mock career-ops directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # 1. config/profile.yml
    profile_content = """
candidate:
  full_name: "Test Candidate"
  email: "candidate@example.com"
  phone: "+55 11 99999-9999"

target_roles:
  primary:
    - "AI Product Manager"
    - "Context Engineer"
  archetypes:
    - name: "AI Product Manager"
      fit: "primary"
    - name: "AI Solutions Architect"
      fit: "secondary"
"""
    (config_dir / "profile.yml").write_text(profile_content, encoding="utf-8")

    # 2. cv.md
    cv_content = """# CV -- Test Candidate

## Summary
Experienced engineer.

## Certifications

- CAPM – Certified Associate in Project Management, Project Management Institute (PMI) (2024)
- Formação Acessibilidade & Front-End (HTML, CSS3, JavaScript), Alura

## Skills
- Python, SQL
"""
    (tmp_path / "cv.md").write_text(cv_content, encoding="utf-8")

    # 3. reports/*.md
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report1 = """# Report 001
- **Score de Fit:** `4.2 / 5.0` (gap a endereçar: Observability, Cloud Architecture)
"""
    report2 = """# Report 002
- **Score de Fit:** `4.0 / 5.0` (principal gap a endereçar na entrevista é profundidade em TypeScript/npm vs stack Python)
"""
    (reports_dir / "001-test.md").write_text(report1, encoding="utf-8")
    (reports_dir / "002-test.md").write_text(report2, encoding="utf-8")

    return tmp_path


def test_parse_profile_yaml(mock_career_ops: Path):
    yaml_path = mock_career_ops / "config" / "profile.yml"
    data = parse_profile_yaml(yaml_path)

    assert data["full_name"] == "Test Candidate"
    assert data["email"] == "candidate@example.com"
    assert "AI Product Manager" in data["target_roles"]
    assert "Context Engineer" in data["target_roles"]
    assert "AI Product Manager" in data["primary_archetypes"]
    assert "AI Solutions Architect" in data["primary_archetypes"]


def test_parse_profile_yaml_single_role_fallback(tmp_path: Path):
    yaml_path = tmp_path / "profile.yml"
    yaml_path.write_text(
        """
candidate:
  full_name: "Solo Role"
  email: "solo@example.com"
target_roles:
  primary: "Lead AI Engineer"
  archetypes:
    - name: "Builder"
""",
        encoding="utf-8",
    )
    data = parse_profile_yaml(yaml_path)
    assert data["target_roles"] == ["Lead AI Engineer"]
    assert data["primary_archetypes"] == ["Builder"]


def test_parse_cv_certifications(mock_career_ops: Path):
    cv_path = mock_career_ops / "cv.md"
    certs = extract_cv_certifications(cv_path)

    assert len(certs) == 2
    assert "CAPM" in certs[0]
    assert "Acessibilidade" in certs[1]


def test_parse_cv_certifications_missing_file(tmp_path: Path):
    certs = extract_cv_certifications(tmp_path / "nonexistent.md")
    assert certs == []


def test_normalize_certification_tokens():
    raw_certs = [
        "CAPM – Certified Associate in Project Management, Project Management Institute (PMI) (2024)",
        "Formação Acessibilidade & Front-End (HTML, CSS3, JavaScript), Alura",
    ]
    tokens = normalize_certification_tokens(raw_certs)

    assert "CAPM" in tokens
    assert "PMI" in tokens
    assert "2024" not in tokens  # 4-digit year excluded


def test_extract_gaps_from_reports(mock_career_ops: Path):
    reports_dir = mock_career_ops / "reports"
    gaps = extract_gaps_from_reports(reports_dir)

    assert "Observability" in gaps
    assert "Cloud Architecture" in gaps
    assert "TypeScript" in gaps


def test_extract_gaps_from_missing_reports(tmp_path: Path):
    gaps = extract_gaps_from_reports(tmp_path / "nonexistent_reports")
    assert gaps == []


def test_run_upskill_success(monkeypatch):
    mock_json = """{
      "schema_version": 2,
      "knownSkills": ["Python", "FastAPI", "SQL"],
      "gaps": [{"skill": "Observability"}, {"skill": "Kubernetes"}],
      "skipBlockers": {"blockers": [{"label": "Cloud Architecture"}]}
    }"""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = mock_json

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_res)

    result = run_upskill(Path("dummy/path"))
    assert result["known_skills"] == ["Python", "FastAPI", "SQL"]
    assert "Observability" in result["gaps"]
    assert "Kubernetes" in result["gaps"]
    assert "Cloud Architecture" in result["gaps"]


def test_run_upskill_timeout(monkeypatch):
    def timeout_mock(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["node", "upskill.mjs"], timeout=12)

    monkeypatch.setattr(subprocess, "run", timeout_mock)

    result = run_upskill(Path("dummy/path"))
    assert result["known_skills"] == []
    assert result["gaps"] == []


def test_run_upskill_node_not_found(monkeypatch):
    def not_found_mock(*args, **kwargs):
        raise FileNotFoundError("node not found")

    monkeypatch.setattr(subprocess, "run", not_found_mock)

    result = run_upskill(Path("dummy/path"))
    assert result["known_skills"] == []
    assert result["gaps"] == []


def test_run_upskill_non_zero_exit(monkeypatch):
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = "Error occurred"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_res)

    result = run_upskill(Path("dummy/path"))
    assert result["known_skills"] == []
    assert result["gaps"] == []


def test_load_profile_mock(mock_career_ops: Path, monkeypatch):
    # Mock upskill to return known skills and empty gaps to trigger reports fallback
    def mock_run_upskill(path: Path):
        return {"known_skills": ["Python", "SQL"], "gaps": []}

    monkeypatch.setattr("cert_radar.profile_bridge.run_upskill", mock_run_upskill)

    profile = load_profile(mock_career_ops)

    assert isinstance(profile, CandidateProfile)
    assert profile.full_name == "Test Candidate"
    assert profile.email == "candidate@example.com"
    assert "AI Product Manager" in profile.target_roles
    assert "AI Solutions Architect" in profile.primary_archetypes
    assert profile.known_skills == ["Python", "SQL"]
    # Fallback to reports
    assert "Observability" in profile.gaps
    assert "Cloud Architecture" in profile.gaps
    assert "TypeScript" in profile.gaps
    # Certifications & normalized tokens
    assert any("CAPM – Certified Associate" in c for c in profile.existing_certifications)
    assert "CAPM" in profile.existing_certifications


def test_load_profile_real_career_ops():
    real_path = Path("D:/Projetos/career-ops")
    if not real_path.exists():
        pytest.skip("Real career-ops path not accessible")

    profile = load_profile(real_path)

    assert isinstance(profile, CandidateProfile)
    assert profile.full_name == "Gabriel Dantas da Silva Oliveira"
    assert profile.email == "gabrielsilva07032002@gmail.com"
    assert "AI Product Manager" in profile.target_roles
    assert len(profile.primary_archetypes) >= 1
    assert any("CAPM" in c for c in profile.existing_certifications)
    assert "CAPM" in profile.existing_certifications
    assert len(profile.known_skills) > 0
    assert "Python" in profile.known_skills
    # Gaps should be populated via fallback to reports/*.md (e.g. TypeScript)
    assert len(profile.gaps) > 0
    assert "TypeScript" in profile.gaps


def test_parse_yaml_fallback_direct():
    from cert_radar.profile_bridge import _parse_yaml_fallback

    yaml_text = """# Comment line
candidate:
  full_name: "Fallback Candidate"
  email: "fallback@example.com"

target_roles:
  primary:
    - "Role A"
    - "Role B"
  archetypes:
    - name: "Arch A"
    name: "Arch B"
"""
    parsed = _parse_yaml_fallback(yaml_text)
    assert parsed["candidate"]["full_name"] == "Fallback Candidate"
    assert parsed["candidate"]["email"] == "fallback@example.com"
    assert parsed["target_roles"]["primary"] == ["Role A", "Role B"]
    arch_names = [a["name"] for a in parsed["target_roles"]["archetypes"]]
    assert "Arch A" in arch_names
    assert "Arch B" in arch_names


def test_parse_profile_yaml_edge_cases(tmp_path: Path):
    # 1. Missing file
    missing = parse_profile_yaml(tmp_path / "absent.yml")
    assert missing["full_name"] == ""
    assert missing["target_roles"] == []

    # 2. Corrupt / unparseable content
    corrupt_file = tmp_path / "corrupt.yml"
    corrupt_file.write_text(":: invalid : yaml ::", encoding="utf-8")
    corrupt = parse_profile_yaml(corrupt_file)
    assert corrupt["full_name"] == ""

    # 3. Invalid types in target_roles and string archetypes
    weird_file = tmp_path / "weird.yml"
    weird_file.write_text(
        """
candidate:
  full_name: "Weird Candidate"
target_roles:
  primary: 12345
  archetypes:
    - "DirectStringArchetype"
""",
        encoding="utf-8",
    )
    weird = parse_profile_yaml(weird_file)
    assert weird["target_roles"] == []
    assert weird["primary_archetypes"] == ["DirectStringArchetype"]


def test_extract_cv_certifications_read_error(tmp_path: Path, monkeypatch):
    dummy_file = tmp_path / "cv.md"
    dummy_file.write_text("## Certifications", encoding="utf-8")

    def mock_read(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", mock_read)
    certs = extract_cv_certifications(dummy_file)
    assert certs == []


def test_run_upskill_more_errors(monkeypatch):
    # 1. SubprocessError
    def mock_sub_err(*args, **kwargs):
        raise subprocess.SubprocessError("generic subprocess error")

    monkeypatch.setattr(subprocess, "run", mock_sub_err)
    res = run_upskill(Path("dummy"))
    assert res == {"known_skills": [], "gaps": []}

    # 2. JSONDecodeError
    mock_bad_json = MagicMock()
    mock_bad_json.returncode = 0
    mock_bad_json.stdout = "{ not valid json"
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_bad_json)
    res = run_upskill(Path("dummy"))
    assert res == {"known_skills": [], "gaps": []}


def test_run_upskill_string_gaps_and_blockers(monkeypatch):
    mock_json = """{
      "schema_version": 2,
      "knownSkills": ["Python"],
      "gaps": ["Observability", "Terraform"],
      "skipBlockers": {"blockers": ["Security Clearance"]}
    }"""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = mock_json

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_res)

    result = run_upskill(Path("dummy/path"))
    assert result["known_skills"] == ["Python"]
    assert "Observability" in result["gaps"]
    assert "Terraform" in result["gaps"]
    assert "Security Clearance" in result["gaps"]


def test_extract_gaps_read_error(mock_career_ops: Path, monkeypatch):
    reports_dir = mock_career_ops / "reports"
    orig_read = Path.read_text

    def selective_read(self, *args, **kwargs):
        if "001" in self.name:
            raise OSError("Read failed")
        return orig_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", selective_read)
    gaps = extract_gaps_from_reports(reports_dir)
    # 002-test.md should still be read
    assert "TypeScript" in gaps


def test_load_profile_when_upskill_returns_gaps(mock_career_ops: Path, monkeypatch):
    def mock_run_upskill(path: Path):
        return {"known_skills": ["Python"], "gaps": ["PreExistingGap"]}

    monkeypatch.setattr("cert_radar.profile_bridge.run_upskill", mock_run_upskill)

    profile = load_profile(mock_career_ops)
    # Should NOT fallback to reports
    assert profile.gaps == ["PreExistingGap"]


def test_profile_snapshot_export_and_cloud_fallback(tmp_path: Path):
    from cert_radar.profile_bridge import export_profile_snapshot, load_profile_snapshot

    profile = CandidateProfile(
        full_name="Cloud Gabriel",
        email="secret@example.com",
        target_roles=["AI Product Manager"],
        primary_archetypes=["Context Engineer"],
        known_skills=["Python", "SQL"],
        gaps=["TypeScript"],
        existing_certifications=["CAPM"],
    )

    snap_file = tmp_path / "profile_snapshot.json"
    export_profile_snapshot(profile, output_path=snap_file, include_email=False)
    assert snap_file.is_file()

    loaded_snap = load_profile_snapshot(snap_file)
    assert loaded_snap is not None
    assert loaded_snap.full_name == "Cloud Gabriel"
    assert loaded_snap.email == ""  # Anonymized by default
    assert loaded_snap.gaps == ["TypeScript"]

    # Export with email
    export_profile_snapshot(profile, output_path=snap_file, include_email=True)
    assert load_profile_snapshot(snap_file).email == "secret@example.com"

    # Fallback in load_profile when career-ops directory does not exist
    missing_career_ops = tmp_path / "nonexistent_career_ops"
    cloud_profile = load_profile(career_ops_root=missing_career_ops, snapshot_path=snap_file)
    assert cloud_profile.full_name == "Cloud Gabriel"
    assert "TypeScript" in cloud_profile.gaps

    # Invalid / missing snapshot returns None gracefully
    assert load_profile_snapshot(tmp_path / "missing.json") is None
    bad_snap = tmp_path / "bad.json"
    bad_snap.write_text("{invalid", encoding="utf-8")
    assert load_profile_snapshot(bad_snap) is None

