# CertRadar

[![Python 3.14+](https://img.shields.io/badge/Python-3.14+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)
[![Tests](https://img.shields.io/badge/Tests-154_Passed_(100%25)-10b981.svg?style=for-the-badge)](tests/)
[![Zero Cost](https://img.shields.io/badge/Infra_Cost-R%24_0.00-3b82f6.svg?style=for-the-badge)](docs/superpowers/specs/2026-11-11-cert-radar-design.md)

**Deterministic certification curation, explainable career-gap matching, and official voucher radar.**

CertRadar bridges target career tracking (AI Product Management, Context Engineering, Data & AI) with verified certification opportunities — filtering out noise, checking live URLs, and alerting on expiring 50%–100% official exam vouchers.

---

## Key Capabilities

- **4-Pillar Explainable Scoring Engine (0–100 pts)** ([`matcher.py`](src/cert_radar/matcher.py)):
  1. **Role Alignment (35 pts):** Matches against target roles and primary career archetypes.
  2. **Skill Gap Closure (25 pts):** Prioritizes certifications closing concrete missing skills from CV/job analyses.
  3. **Recruiter Signal (20 pts):** Weights industry-recognized credentials and applied labs.
  4. **Cost & Voucher Urgency (20 pts):** Boosts free credentials and active 100%/discount vouchers expiring within `<= 14 days`, while suppressing redundant credentials already on the CV.
- **Two Curated Tracks:** `official_voucher` (proctored exams with active discounts/challenges) vs. `free_continuous` (verifiable zero-cost micro-credentials).
- **Local High-Density SPA & SQLite Persistence** ([`server.py`](src/cert_radar/server.py), [`db.py`](src/cert_radar/db.py)): Clean native HTML/CSS/JS dashboard with lifecycle status tracking (`radar` → `saved` → `studying` → `completed` / `ignored`).
- **Dual Anti-Spam Alert Pipeline** ([`notifier.py`](src/cert_radar/notifier.py)): Windows native Toast + optional Telegram Bot notifications deduplicated per `activation_epoch` for critical deadlines (`<= 7 days` and `<= 48h`).
- **Live Liveness Collector** ([`collector.py`](src/cert_radar/collector.py)): Verifies official campaign URLs before surfacing opportunities.

---

## Architecture

```
src/cert_radar/
├── cli.py             # CLI commands (serve, check-radar, sync-profile, setup-telegram, add-url)
├── collector.py       # Catalog loader & HTTP link liveness verification
├── db.py              # SQLite persistence & deduplicated alert ledger
├── matcher.py         # 4-pillar deterministic scoring & redundancy suppression
├── models.py          # Pydantic v2 domain models (Certification, CandidateProfile, MatchResult)
├── notifier.py        # Windows Toast & Telegram notification dispatcher
├── profile_bridge.py  # Read-only bridge for CV / career profile alignment
├── server.py          # Lightweight local HTTP API + SPA static server
└── static/            # Zero-dependency frontend (index.html, app.js, style.css)
```

---

## Quick Start

```bash
# 1. Install dependencies (Python >= 3.14, uv or pip)
pip install -e .

# 2. Launch the local SPA dashboard
python -m cert_radar serve

# 3. Run radar collection, profile matching, and alert checks
python -m cert_radar check-radar

# 4. Run full unit & integration test suite
pytest -v
```
