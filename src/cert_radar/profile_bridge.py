"""Profile Bridge to integrate with career-ops repository in read-only mode."""

import json
import logging
from pathlib import Path
import re
import subprocess
from typing import Any

from cert_radar.models import CandidateProfile

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

logger = logging.getLogger(__name__)


def _parse_yaml_fallback(text: str) -> dict[str, Any]:
    """Lightweight fallback YAML parser for profile.yml when pyyaml is unavailable."""
    result: dict[str, Any] = {
        "candidate": {},
        "target_roles": {"primary": [], "archetypes": []},
    }

    current_section = None
    sub_section = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped.endswith(":"):
            current_section = stripped[:-1].strip()
            sub_section = None
            continue

        if current_section == "candidate":
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                result["candidate"][k.strip()] = v.strip().strip("\"'")

        elif current_section == "target_roles":
            if indent == 2 and stripped.endswith(":"):
                sub_section = stripped[:-1].strip()
                continue

            if sub_section == "primary":
                if stripped.startswith("- "):
                    role = stripped[2:].strip().strip("\"'")
                    result["target_roles"]["primary"].append(role)
                elif ":" in stripped:
                    k, v = stripped.split(":", 1)
                    if k.strip() == "primary" and v.strip():
                        result["target_roles"]["primary"] = [v.strip().strip("\"'")]

            elif sub_section == "archetypes":
                if stripped.startswith("- name:"):
                    name = stripped.split(":", 1)[1].strip().strip("\"'")
                    result["target_roles"]["archetypes"].append({"name": name})
                elif stripped.startswith("name:"):
                    name = stripped.split(":", 1)[1].strip().strip("\"'")
                    result["target_roles"]["archetypes"].append({"name": name})

    return result


def parse_profile_yaml(yaml_path: Path) -> dict[str, Any]:
    """Reads config/profile.yml and extracts candidate info, target roles, and archetypes."""
    if not yaml_path.is_file():
        logger.warning(f"Profile config file not found: {yaml_path}")
        return {
            "full_name": "",
            "email": "",
            "target_roles": [],
            "primary_archetypes": [],
        }

    try:
        content = yaml_path.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(content) or {}
        else:  # pragma: no cover
            data = _parse_yaml_fallback(content)
        if not isinstance(data, dict):
            data = {}
    except Exception as e:
        logger.error(f"Failed to parse profile yaml at {yaml_path}: {e}")
        return {
            "full_name": "",
            "email": "",
            "target_roles": [],
            "primary_archetypes": [],
        }

    candidate = data.get("candidate", {}) or {}
    full_name = candidate.get("full_name", "")
    email = candidate.get("email", "")

    target_roles_data = data.get("target_roles", {}) or {}
    raw_primary = target_roles_data.get("primary", [])
    if isinstance(raw_primary, str):
        target_roles = [raw_primary]
    elif isinstance(raw_primary, list):
        target_roles = [str(r) for r in raw_primary]
    else:
        target_roles = []

    raw_archetypes = target_roles_data.get("archetypes", [])
    primary_archetypes: list[str] = []
    if isinstance(raw_archetypes, list):
        for arch in raw_archetypes:
            if isinstance(arch, dict) and "name" in arch:
                primary_archetypes.append(str(arch["name"]))
            elif isinstance(arch, str):
                primary_archetypes.append(arch)

    return {
        "full_name": full_name,
        "email": email,
        "target_roles": target_roles,
        "primary_archetypes": primary_archetypes,
    }


def extract_cv_certifications(cv_path: Path) -> list[str]:
    """Reads cv.md, extracts bulleted items under the ## Certifications section."""
    if not cv_path.is_file():
        logger.warning(f"CV markdown file not found: {cv_path}")
        return []

    try:
        content = cv_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read CV at {cv_path}: {e}")
        return []

    certifications: list[str] = []
    in_cert_section = False

    for line in content.splitlines():
        stripped = line.strip()
        if re.match(r"^##\s+Certifications\b", stripped, re.IGNORECASE):
            in_cert_section = True
            continue
        elif in_cert_section and stripped.startswith("## "):
            # Reached next section
            break

        if in_cert_section:
            if stripped.startswith("- ") or stripped.startswith("* "):
                cert_item = stripped[2:].strip()
                if cert_item:
                    certifications.append(cert_item)

    return certifications


def normalize_certification_tokens(cert_lines: list[str]) -> list[str]:
    """Extracts normalized certification acronyms/tokens for strict deduplication."""
    tokens: set[str] = set()

    for line in cert_lines:
        # 1. Extract acronyms in parentheses: e.g. (PMI)
        for match in re.findall(r"\(([A-Z0-9_-]+)\)", line):
            if not re.match(r"^\d{4}$", match):  # Skip 4-digit years like (2024)
                tokens.add(match)

        # 2. Extract leading acronym before hyphen/dash: e.g. 'CAPM – ...'
        lead_match = re.match(r"^([A-Z0-9_-]{2,10})\s*[–-]", line)
        if lead_match:
            lead = lead_match.group(1).strip()
            if not re.match(r"^\d{4}$", lead):
                tokens.add(lead)

        # 3. Standalone uppercase tokens (2 to 6 characters)
        for word in re.findall(r"\b[A-Z0-9-]{2,6}\b", line):
            # Ignore purely numeric tokens (e.g. 2024, 5)
            if not word.isdigit():
                tokens.add(word)

    return sorted(tokens)


def run_upskill(career_ops_root: Path) -> dict[str, Any]:
    """Executes node upskill.mjs --min-reports 1 in career_ops_root and parses JSON output."""
    cmd = ["node", "upskill.mjs", "--min-reports", "1"]
    logger.info(f"Running upskill command: {' '.join(cmd)} in {career_ops_root}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(career_ops_root),
            capture_output=True,
            text=True,
            timeout=12,
        )
    except FileNotFoundError:
        logger.warning("Node.js executable not found in PATH; skipping upskill execution.")
        return {"known_skills": [], "gaps": []}
    except subprocess.TimeoutExpired:
        logger.warning("Execution of node upskill.mjs timed out (12s); skipping.")
        return {"known_skills": [], "gaps": []}
    except subprocess.SubprocessError as e:
        logger.warning(f"Error running node upskill.mjs: {e}")
        return {"known_skills": [], "gaps": []}

    if proc.returncode != 0:
        logger.warning(
            f"upskill.mjs exited with non-zero code {proc.returncode}: {proc.stderr.strip()}"
        )
        return {"known_skills": [], "gaps": []}

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to decode JSON from upskill.mjs: {e}")
        return {"known_skills": [], "gaps": []}

    if not isinstance(data, dict):
        return {"known_skills": [], "gaps": []}

    known_skills = [str(s) for s in (data.get("knownSkills") or [])]

    gaps: list[str] = []
    for g in (data.get("gaps") or []):
        if isinstance(g, dict) and "skill" in g:
            gaps.append(str(g["skill"]))
        elif isinstance(g, str):
            gaps.append(g)

    # Also capture skipBlockers.blockers[].label
    skip_blockers = data.get("skipBlockers", {})
    if isinstance(skip_blockers, dict):
        for b in skip_blockers.get("blockers", []):
            if isinstance(b, dict) and "label" in b:
                gaps.append(str(b["label"]))
            elif isinstance(b, str):
                gaps.append(b)

    return {
        "known_skills": known_skills,
        "gaps": list(dict.fromkeys(gaps)),
    }


def extract_gaps_from_reports(reports_dir: Path) -> list[str]:
    """Inspects reports/*.md to extract skill gaps when upskill.mjs reports zero gaps."""
    if not reports_dir.is_dir():
        logger.info(f"Reports directory not found: {reports_dir}")
        return []

    gaps: list[str] = []

    for report_file in sorted(reports_dir.glob("*.md")):
        try:
            content = report_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Could not read report file {report_file}: {e}")
            continue

        # Pattern 1: explicit "gap a endereçar:" or "gaps a endereçar:"
        for match in re.finditer(
            r"gap(?:s)?\s+a\s+endereçar\s*:\s*([^\n\)\.]+)",
            content,
            re.IGNORECASE,
        ):
            matched_text = match.group(1).strip()
            for part in re.split(r"[,;]|\be\b|\band\b", matched_text):
                cleaned = part.strip().strip("`*_- ")
                if cleaned and len(cleaned) < 50 and cleaned not in gaps:
                    gaps.append(cleaned)

        # Pattern 2: narrative phrases like "principal gap a endereçar na entrevista é profundidade em TypeScript/npm vs seu stack principal em Python"
        for match in re.finditer(
            r"gap(?:s)?\s+a\s+endereçar.*?profundidade\s+em\s+([A-Za-z0-9_/#+-]+)",
            content,
            re.IGNORECASE,
        ):
            matched_text = match.group(1).strip()
            for part in re.split(r"[/,]", matched_text):
                cleaned = part.strip().strip("`*_- ")
                if cleaned and cleaned not in gaps:
                    gaps.append(cleaned)

        # Pattern 3: "gap a endereçar na entrevista é ..."
        for match in re.finditer(
            r"gap(?:s)?\s+a\s+endereçar\s+(?:na\s+entrevista\s+)?é\s+([^\n\)\.]+)",
            content,
            re.IGNORECASE,
        ):
            matched_text = match.group(1).strip()
            if " vs " in matched_text.lower():
                matched_text = re.split(r"\s+vs\s+", matched_text, flags=re.IGNORECASE)[0]
            matched_text = re.sub(
                r"^profundidade\s+em\s+", "", matched_text, flags=re.IGNORECASE
            ).strip()
            for part in re.split(r"[/,]|;|\be\b", matched_text):
                cleaned = part.strip().strip("`*_- ")
                if cleaned and len(cleaned) < 50 and cleaned not in gaps:
                    gaps.append(cleaned)

    return gaps


def load_profile(
    career_ops_root: Path | str = "D:\\Projetos\\career-ops",
) -> CandidateProfile:
    """Loads candidate profile from career-ops repository in strictly read-only mode."""
    root = Path(career_ops_root)

    # 1. Parse config/profile.yml
    profile_data = parse_profile_yaml(root / "config" / "profile.yml")

    # 2. Parse cv.md certifications
    raw_certs = extract_cv_certifications(root / "cv.md")
    tokens = normalize_certification_tokens(raw_certs)
    all_certifications = list(dict.fromkeys(raw_certs + tokens))

    # 3. Run upskill.mjs
    upskill_data = run_upskill(root)
    known_skills = upskill_data.get("known_skills", [])
    gaps = upskill_data.get("gaps", [])

    # 4. Fallback / enrichment if gaps is empty
    if not gaps:
        logger.info("Upskill returned no gaps; enriching from reports/*.md")
        gaps = extract_gaps_from_reports(root / "reports")

    return CandidateProfile(
        full_name=profile_data["full_name"],
        email=profile_data["email"],
        target_roles=profile_data["target_roles"],
        primary_archetypes=profile_data["primary_archetypes"],
        known_skills=known_skills,
        gaps=gaps,
        existing_certifications=all_certifications,
    )
