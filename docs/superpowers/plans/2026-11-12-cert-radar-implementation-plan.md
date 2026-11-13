# CertRadar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o sistema pessoal `CertRadar` para curadoria sob demanda, matching determinístico e radar periódico com notificações ativas (Windows Toast + Telegram) de certificações gratuitas e vouchers oficiais, integrado em modo leitura ao `career-ops` e entregue em uma SPA local anti-slop de alta densidade.

**Architecture:** Projeto autônomo em Python 3.14 (`uv`) e SQLite local em `D:\Projetos\cert-radar`. Backend modular com ponte somente leitura para `D:\Projetos\career-ops` (`cv.md`, `profile.yml`, `upskill.mjs`, `reports/`), catálogo curado de 20 certificações nucleares, coletor de liveness com detecção de expiração, motor de matching explicável (0–100), serviço de notificações com deduplicação anti-spam (`activation_epoch`), micro-servidor local servindo SPA estática anti-slop (padrão Linear/GitHub) e launcher Windows em 1 clique.

**Tech Stack:** Python 3.14, `uv`, SQLite 3, `pydantic` v2, `httpx`, `pytest`, `winotify` (com fallback PowerShell), Telegram Bot API (HTTP nativo), HTML5/CSS3 semântico anti-slop (*Taste-Skill* compliant). Custo R$ 0,00, sem Docker.

**Spec:** `D:\Projetos\cert-radar\docs\superpowers\specs\2026-11-11-cert-radar-design.md`

## Global Constraints

- Armazenamento de código, `.venv`, banco SQLite, logs e caches estritamente no SSD `D:\Projetos\cert-radar`.
- Custo perpétuo de R$ 0,00: apenas bibliotecas open source, APIs gratuitas (Telegram) e notificações locais do Windows.
- Sem Docker: execução direta via Python 3.14 + `uv`.
- Acesso ao `D:\Projetos\career-ops` estritamente somente leitura (zero mutações em `cv.md` ou arquivos do tracker).
- Design Anti-Slop (*Taste-Skill*): sem roxo/violeta, sem dials de template, sem efeitos neon; layout tabular denso com atalhos de teclado.
- Test-Driven Development (TDD): todo componente deve ter teste unitário/integrado automatizado antes da implementação, com cobertura >= 80%.

## Review Focus

1. **Falha ou timeout na execução de `node upskill.mjs`:** o sistema deve degradar graciosamente lendo `config/profile.yml` e `reports/*.md` diretamente, sem travar o radar.
2. **URLs protegidas por login-wall (ex.: LinkedIn HTTP 999 ou 403):** o coletor não pode marcar o link como `dead`, mas sim como `unverified`, preservando a certificação no catálogo.
3. **Reativação de programas de voucher sem data de término fixa:** o gerador de chave de deduplicação deve usar `activation_epoch` para evitar spam mas permitir novos alertas quando o programa for relançado meses depois.
4. **Links de vouchers expirados ou alterados:** o coletor deve detectar strings de encerramento (*"closed"*, *"expired"*, *"ended"*) e atualizar `liveness_status` para `expired`, impedindo disparos falsos.
5. **Deduplicação de credenciais já obtidas:** o matcher deve suprimir ou sinalizar claramente certificações já listadas no `cv.md` (ex.: `CAPM`), evitando recomendações redundantes.

---

### Task 1: Scaffolding do Projeto, Modelos Pydantic e Esquema SQLite

**Files:**
- Create: `pyproject.toml`
- Create: `src/cert_radar/__init__.py`
- Create: `src/cert_radar/models.py`
- Create: `src/cert_radar/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `CandidateProfile`, `Certification`, `VoucherEvent`, `UserProgress`, `AlertLog` (Pydantic models).
- Produces: `Database` class com métodos `init_db()`, `upsert_certification(cert)`, `get_certifications(filter)`, `record_event(event)`, `get_user_progress(cert_id)`, `set_user_progress(cert_id, status, notes)`, `has_alert_been_sent(dedup_key)`, `log_alert(cert_id, channel, alert_type, dedup_key)`.

- [ ] **Step 1: Inicializar projeto com `uv` em `D:\Projetos\cert-radar` e configurar dependências**
  - Executar `uv init --name cert-radar` e adicionar dependências: `pydantic>=2.7`, `httpx>=0.27`, `pytest>=8.0`.

- [ ] **Step 2: Escrever testes que falham para o banco de dados em `tests/test_db.py`**
  - Testar criação de tabelas, inserção idempotente de certificação, transição de status em `user_progress` e deduplicação de `alert_log`.

- [ ] **Step 3: Executar teste para verificar falha**
  - Executar: `uv run pytest tests/test_db.py`
  - Esperado: FAIL (módulos não encontrados).

- [ ] **Step 4: Implementar `models.py` e `db.py`**
  - Criar modelos com validação e tipagem estrita. Implementar `Database` com SQLite embutido, `WAL` mode e constraints `UNIQUE` em `dedup_key`.

- [ ] **Step 5: Executar testes para verificar aprovação**
  - Executar: `uv run pytest tests/test_db.py`
  - Esperado: PASS.

- [ ] **Step 6: Commit**
  - `git init && git add . && git commit -m "feat: scaffold project, models, and sqlite persistence"`

---

### Task 2: Profile Bridge com `career-ops` (Somente Leitura)

**Files:**
- Create: `src/cert_radar/profile_bridge.py`
- Test: `tests/test_profile_bridge.py`

**Interfaces:**
- Consumes: arquivos em `D:\Projetos\career-ops` (`cv.md`, `config/profile.yml`, `node upskill.mjs`, `reports/*.md`).
- Produces: `load_profile(career_ops_root: Path) -> CandidateProfile`.

- [ ] **Step 1: Escrever testes unitários em `tests/test_profile_bridge.py`**
  - Testar parsing de `config/profile.yml` (extração de `target_roles`), extração de `## Certifications` do `cv.md` (detectando `CAPM`), execução mockada de `upskill.mjs` e fallback leve de leitura de gaps em `reports/*.md`.

- [ ] **Step 2: Executar teste para verificar falha**
  - Executar: `uv run pytest tests/test_profile_bridge.py`
  - Esperado: FAIL.

- [ ] **Step 3: Implementar `profile_bridge.py`**
  - Implementar leitura resiliente com timeout de subprocesso para `upskill.mjs`, parser regex defensivo para `cv.md` e fallback para arquivos de report sem crash.

- [ ] **Step 4: Executar testes para verificar aprovação**
  - Executar: `uv run pytest tests/test_profile_bridge.py`
  - Esperado: PASS.

- [ ] **Step 5: Commit**
  - `git add src/cert_radar/profile_bridge.py tests/test_profile_bridge.py && git commit -m "feat: implement read-only career-ops profile bridge"`

---

### Task 3: Catálogo Nuclear Seed e Coletor de Liveness do Radar

**Files:**
- Create: `data/seed_catalog.json`
- Create: `config/sources.yaml`
- Create: `src/cert_radar/collector.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Produces: `seed_initial_catalog(db: Database, seed_path: Path) -> int`.
- Produces: `check_liveness(url: str, client: httpx.Client) -> LivenessResult`.
- Produces: `run_radar_collection(db: Database, sources_config: Path) -> CollectionReport`.

- [ ] **Step 1: Criar catálogo inicial `data/seed_catalog.json` com as 20 certificações nucleares**
  - Incluir Microsoft (AI-102, DP-600, Applied Skills NLP/Docs), Databricks (GenAI, Data Eng, Lakehouse), AWS (AI Practitioner, ML), GCP (ML Engineer, Cloud Digital Leader), dbt Developer, Snowflake SnowPro, Anthropic/DeepLearning MCP e FinOps.

- [ ] **Step 2: Escrever testes unitários em `tests/test_collector.py`**
  - Testar carregamento idempotente do seed, detecção de status `live`, `expired` (via strings *"closed"*/*"ended"*), `dead` (HTTP 404/500) e `unverified` (LinkedIn HTTP 999).

- [ ] **Step 3: Executar teste para verificar falha**
  - Executar: `uv run pytest tests/test_collector.py`
  - Esperado: FAIL.

- [ ] **Step 4: Implementar `collector.py`**
  - Utilizar `httpx` com timeout de 15s, headers institucionais de `User-Agent` e transições de estado registradas na tabela `voucher_events`.

- [ ] **Step 5: Executar testes para verificar aprovação**
  - Executar: `uv run pytest tests/test_collector.py`
  - Esperado: PASS.

- [ ] **Step 6: Commit**
  - `git add data/ config/ src/cert_radar/collector.py tests/test_collector.py && git commit -m "feat: implement seed catalog and liveness radar collector"`

---

### Task 4: Motor de Matching Explicável (0–100)

**Files:**
- Create: `src/cert_radar/matcher.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes: `CandidateProfile`, `List[Certification]`.
- Produces: `MatchResult(cert_id, score, role_score, gap_score, signal_score, cost_score, match_reasons, redundancy_warning)`.
- Produces: `rank_certifications(profile: CandidateProfile, certs: List[Certification]) -> List[MatchResult]`.

- [ ] **Step 1: Escrever testes unitários em `tests/test_matcher.py`**
  - Testar pontuação de alinhamento com `target_roles` (AI PM / Context Eng), bônus de fechamento de gaps reais, bônus de voucher urgente (`<= 48h`), penalidade de redundância (-25 pts para certificações básicas cujo conteúdo já está no CV) e exclusão/alerta para credencial já conquistada (ex.: CAPM).

- [ ] **Step 2: Executar teste para verificar falha**
  - Executar: `uv run pytest tests/test_matcher.py`
  - Esperado: FAIL.

- [ ] **Step 3: Implementar `matcher.py`**
  - Implementar lógica determinística com 4 pilares: Role Alignment (35%), Gap Closure (25%), Recruiter Signal (20%), Custo/Urgência (20%). Gerar justificativas explicáveis em português baseadas nas skills.

- [ ] **Step 4: Executar testes para verificar aprovação**
  - Executar: `uv run pytest tests/test_matcher.py`
  - Esperado: PASS.

- [ ] **Step 5: Commit**
  - `git add src/cert_radar/matcher.py tests/test_matcher.py && git commit -m "feat: implement explainable profile matcher engine"`

---

### Task 5: Serviço de Notificações com Deduplicação Anti-Spam (Windows Toast + Telegram)

**Files:**
- Create: `src/cert_radar/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Produces: `send_windows_toast(title: str, message: str, url: str) -> bool`.
- Produces: `send_telegram_alert(token: str, chat_id: str, message: str) -> bool`.
- Produces: `dispatch_alerts(db: Database, scored_certs: List[MatchResult], min_score: int) -> int`.

- [ ] **Step 1: Escrever testes unitários em `tests/test_notifier.py`**
  - Testar formatação de mensagem Markdown para o Telegram, geração de chave de deduplicação com `activation_epoch`, prevenção de envio repetido via `alert_log` e disparo apenas para vouchers com score `>= 65` ou status `saved`.

- [ ] **Step 2: Executar teste para verificar falha**
  - Executar: `uv run pytest tests/test_notifier.py`
  - Esperado: FAIL.

- [ ] **Step 3: Implementar `notifier.py`**
  - Implementar envio HTTP assíncrono/síncrono para Telegram API e integração nativa Windows Toast via `winotify` (com fallback elegante para script PowerShell caso executado em ambientes sem DLL nativa).

- [ ] **Step 4: Executar testes para verificar aprovação**
  - Executar: `uv run pytest tests/test_notifier.py`
  - Esperado: PASS.

- [ ] **Step 5: Commit**
  - `git add src/cert_radar/notifier.py tests/test_notifier.py && git commit -m "feat: implement windows toast and telegram notification service"`

---

### Task 6: SPA Local Anti-Slop (Linear / Dev-Tool Style) & API Backend

**Files:**
- Create: `src/cert_radar/server.py`
- Create: `src/cert_radar/static/index.html`
- Create: `src/cert_radar/static/app.js`
- Create: `src/cert_radar/static/style.css`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: Servidor HTTP embutido com rotas JSON:
  - `GET /api/profile` (retorna dados resumidos do perfil e gaps)
  - `GET /api/certs` (retorna certificações ranqueadas com breakdown de score)
  - `POST /api/progress` (atualiza status: `radar`, `saved`, `studying`, `completed`, `ignored`)
  - `POST /api/add-url` (insere link manual no catálogo com checagem de liveness)
  - `POST /api/generate-snippet` (gera Markdown formatado para `cv.md` e Segundo Cérebro)

- [ ] **Step 1: Escrever testes de API em `tests/test_server.py`**
  - Testar rotas `/api/profile`, `/api/certs` e mutação de status em `/api/progress`.

- [ ] **Step 2: Executar teste para verificar falha**
  - Executar: `uv run pytest tests/test_server.py`
  - Esperado: FAIL.

- [ ] **Step 3: Implementar `server.py` e arquivos estáticos anti-slop**
  - Backend leve em Python puro (usando `http.server` avançado ou `starlette`/`uvicorn` sem overhead).
  - Frontend SPA estático fiel ao *Taste-Skill*: tabela densa, drawer lateral, atalhos de teclado (`j`/`k`/`Enter`/`o`), sem brilhos neon, sem roxo, tipografia limpa em `Inter` e `JetBrains Mono`.

- [ ] **Step 4: Executar testes para verificar aprovação**
  - Executar: `uv run pytest tests/test_server.py`
  - Esperado: PASS.

- [ ] **Step 5: Commit**
  - `git add src/cert_radar/server.py src/cert_radar/static/ tests/test_server.py && git commit -m "feat: implement anti-slop dense web spa and local api"`

---

### Task 7: CLI Unificada, Setup Interativo do Telegram e Scripts Windows

**Files:**
- Create: `src/cert_radar/cli.py`
- Create: `iniciar_cert_radar.bat`
- Create: `scripts/register_task.ps1`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: CLI invocável via `python -m cert_radar` com subcomandos:
  - `serve`: inicia o servidor web local e abre navegador padrão em `http://localhost:8000`.
  - `check-radar`: executa checagem de liveness e dispara alertas pendentes.
  - `setup-telegram`: wizard interativo no terminal que pede Token/ChatID e dispara teste imediato.
  - `sync-profile`: força re-sincronização do `career-ops`.
  - `add-url <url>`: cadastra link manual no catálogo.
- Produces: `iniciar_cert_radar.bat` (launcher de 1 clique).
- Produces: `scripts/register_task.ps1` (registra Task no Agendador do Windows para rodar a cada 12h em background).

- [ ] **Step 1: Escrever testes unitários em `tests/test_cli.py`**
  - Testar parsing de argumentos da CLI e rotinas de comando com mocks.

- [ ] **Step 2: Executar teste para verificar falha**
  - Executar: `uv run pytest tests/test_cli.py`
  - Esperado: FAIL.

- [ ] **Step 3: Implementar `cli.py`, `iniciar_cert_radar.bat` e `register_task.ps1`**
  - Implementar comandos com saídas monoespaçadas limpas no terminal e arquivos executáveis Windows no padrão do projeto.

- [ ] **Step 4: Executar testes para verificar aprovação**
  - Executar: `uv run pytest tests/test_cli.py`
  - Esperado: PASS.

- [ ] **Step 5: Executar suíte completa de testes com medição de cobertura**
  - Executar: `uv run pytest --cov=src/cert_radar --cov-report=term-missing`
  - Esperado: 100% dos testes passando com cobertura >= 80%.

- [ ] **Step 6: Commit final**
  - `git add . && git commit -m "feat: add unified cli, telegram wizard, and windows launcher scripts"`
