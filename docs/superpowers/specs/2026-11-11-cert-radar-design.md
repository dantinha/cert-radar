# CertRadar — Design Specification

**Date:** 2026-11-11
**Location:** `D:\Projetos\cert-radar`
**Status:** Ready for user approval (Builder Check passed)

---

## 1. Intent & Why

Gabriel precisa de um sistema pessoal, de custo zero (R$ 0,00), que resolva dois problemas conectados na sua evolução de carreira (**AI Product Manager**, **Context Engineer**, **AI Product Engineer**, **Technical PM — Data & AI**):

1. **Curadoria e Matching Sob Demanda (Foco Principal):** descobrir e priorizar certificações gratuitas ou acessíveis por bolsa/voucher que realmente tenham **peso no currículo** e fechem **gaps concretos** identificados no seu perfil e nas vagas analisadas no `career-ops` (`D:\Projetos\career-ops`).
2. **Radar Periódico de Vouchers (Foco Secundário):** monitorar programas oficiais de vouchers (50%–100% de desconto em exames proctored) com janela curta de inscrição/expiração, validar que o link está ativo e disparar **notificações ativas** (Windows Toast + Telegram) antes que a oportunidade passe.

---

## 2. Goals, Non-Goals & Anti-Goals

### Goals
- **Integração viva com `career-ops` (somente leitura):** consumir `cv.md`, `config/profile.yml`, `reports/*.md` e a saída JSON de `node upskill.mjs` sem duplicar dados de perfil nem modificar o repositório `career-ops`.
- **Duas trilhas claras:**
  - `official_voucher`: exames oficiais pagos de alto sinal com voucher/bolsa/desafio ativo (Microsoft, Google Cloud, AWS, Databricks, dbt, Linux Foundation, FinOps, PMI).
  - `free_continuous`: certificações e micro-credenciais técnicas 100% gratuitas e contínuas com forte valor prático/curriculares (Microsoft Applied Skills, Databricks Fundamentals, dbt Fundamentals, Anthropic/MCP, DeepLearning.AI, Hugging Face, Kaggle/Google Cloud Skills Boost).
- **Score explicável:** todo item ranqueado exibe exatamente quais cargos-alvo atende, quais gaps fecha e por que não é redundante com o que já está no CV.
- **Interface visual própria:** painel web limpo em Streamlit com ranking personalizado, radar de prazos, tracker pessoal (`radar` → `saved` → `studying` → `completed` / `ignored`) e cadastro manual rápido de novos links/vouchers.
- **Notificação ativa dupla (Windows + Telegram):** alertas sem spam apenas para novos vouchers relevantes ou prazos críticos (`<= 7 dias` e `<= 48h`), com deduplicação persistida em banco.

### Non-Goals
- Não é um agregador genérico de cursos gratuitos (Coursera/Udemy/YouTube sem credencial verificável).
- Não envia candidaturas nem altera arquivos do `career-ops` automaticamente (no máximo gera um snippet de certificação concluída pronto para copiar no `cv.md`).
- Não depende de Docker, serviços pagos, bancos remotos pagos ou scraping pesado com navegador headless em toda execução.

### Anti-Goals (O que faria o sistema falhar na prática)
- Recomendar certificações já concluídas (ex.: CAPM) ou introdutórias triviais de skills já comprovadas em produção no CV (ex.: "SQL Básico").
- Exibir links mortos (404), páginas expiradas ou campanhas encerradas marcadas como ativas.
- Spam de alertas repetidos na mesma janela de prazo.

---

## 3. Constraints

- **Armazenamento no Drive `D:\`:** código, `.venv` (`uv`), banco SQLite, logs e caches exclusivamente em `D:\Projetos\cert-radar`. Nada pesado em `C:\`.
- **Custo Perpétuo R$ 0,00:** apenas bibliotecas open source, API gratuita do Telegram Bot, notificações nativas do Windows, Windows Task Scheduler e **Gemini Free Tier** (`google-genai`) estritamente opcional com circuit breaker local e fallback determinístico.
- **Sem Docker:** execução direta via Python 3.14 + `uv` (já instalados na máquina).
- **Resiliência offline/parcial:** se `career-ops` estiver com poucos reports no `upskill.mjs` (`gaps: []`, cenário atual com 4 reports) ou se o Gemini estiver indisponível/sem quota, o motor determinístico continua funcionando integralmente via `profile.yml` + `cv.md` + `reports/*.md`.

---

## 4. Approaches Considered & Selected

- **Abordagem A — Projeto Python Autônomo em `D:\Projetos\cert-radar` (SPA Local Anti-Slop + SQLite + CLI/Worker):** *(Escolhida e Refinada via Taste-Skill & Grilling)*
  - *Trade-off:* Fica em painel isolado em `D:\Projetos\cert-radar`, lê arquivos do `career-ops` em modo read-only e serve uma SPA local leve (HTML/CSS semântico nativo de alta densidade sem Streamlit e sem estética de IA genérica). Zero dependências de frontend complexas, 100% de controle sobre estilo anti-slop, máxima velocidade de carregamento e compatibilidade total com o ecossistema Python local.
- **Abordagem B — Módulo Embutido no `career-ops` (Next.js + SQLite existente):** descartada por acoplar personalizações pesadas de UI/notificação Windows ao repo upstream do `career-ops`.
- **Abordagem C — FastAPI + Frontend Customizado HTML/JS:** descartada na v1 pelo maior custo de construção de tabelas, filtros e formulários frente ao ganho imediato do Streamlit.

---

## 5. Architecture & Core Components

```text
D:\Projetos\career-ops\ (read-only)          Fontes Oficiais (Web/RSS/JSON)
  ├── cv.md                                       │
  ├── config/profile.yml                          ▼
  ├── upskill.mjs (JSON)              ┌───────────────────────────┐
  └── reports/*.md                    │  radar/ (Fetch + Liveness │
          │                           │  + Optional Gemini Parse) │
          ▼                           └─────────────┬─────────────┘
┌───────────────────────┐                           │
│ core/profile_bridge.py│                           ▼
└──────────┬────────────┘             ┌───────────────────────────┐
           │                          │  data/cert_radar.db       │
           └────────────┬────────────►│  (SQLite: certs, events,  │
                        │             │   progress, alert_log)    │
                        ▼             └─────────────┬─────────────┘
           ┌────────────────────────┐               │
           │  core/matcher.py       │◄──────────────┘
           │  (Dedup + Score 0-100  │
           │   + Explainable Why)   │
           └──────────┬─────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
┌───────────────────┐     ┌──────────────────────────┐
│ ui/app.py         │     │ notify/ (CLI + Scheduler)│
│ (Streamlit Panel) │     │ Windows Toast + Telegram │
└───────────────────┘     └──────────────────────────┘
```

### 5.1 Profile Bridge (`core/profile_bridge.py`)
Constrói um `CandidateProfile` normalizado em memória a partir de `CAREER_OPS_ROOT` (configurável via `.env`, padrão `D:\Projetos\career-ops`):
1. **Executa `node upskill.mjs --min-reports 1`** (timeout 10s, com fallback gracioso se Node falhar): extrai `knownSkills`, `gaps` e `skipBlockers`.
2. **Lê `config/profile.yml`:** extrai `target_roles.primary`, `target_roles.archetypes` e `narrative.superpowers`.
3. **Lê `cv.md`:** extrai a seção `## Certifications` (para deduplicação exata de credenciais já obtidas, ex.: `CAPM`) e tokens de skills/experiência comprovada.
4. **Enriquecimento sobre `reports/*.md`:** quando `upskill.mjs` retornar `gaps: []` (ex.: reports sem bloco `Machine Summary`), um parser leve lê os headers e linhas de `gap` / `Score de Fit` dos reports locais para extrair skills citadas como lacuna (ex.: `TypeScript/npm`, `Observability`, `Cloud Architecture`, etc.) sem depender de LLM.

### 5.2 Catálogo Curado + Radar Periódico (`radar/`)
- **Seed Curado Inicial (`data/seed_catalog.json`):** carregado de forma idempotente no SQLite (`certifications`), com 20–30 certificações e programas de alto sinal já mapeados para os arquétipos do Gabriel (Data/AI, Context/Agentic AI, Cloud AI/Data Engineering, Product Management/FinOps), separados em `official_voucher` e `free_continuous`.
- **Adaptadores de Fontes Oficiais (`radar/sources.py`):** lista declarativa em `config/sources.yaml` mapeando URLs oficiais de programas recorrentes de voucher/certificação gratuita (Microsoft Learn Events / Virtual Training Days / Applied Skills, Google Cloud Skills Boost / Arcade / Get Certified, AWS Skill Builder / Emerging Talent, Databricks Academy / Community promos, dbt Learn, Linux Foundation / CNCF scholarships, Anthropic / DeepLearning.AI / Hugging Face) aos respectivos `cert_id`s já curados. **Decisão de escopo (confirmada pelo usuário):** o radar periódico **apenas atualiza status, descontos, prazos e liveness do catálogo curado e de itens manuais**, sem auto-inserir itens desconhecidos (mantendo alta pureza de sinal).
- **Coletor & Verificador de Liveness (`radar/collector.py`):**
  - Faz requisição HTTP (`httpx`, timeout 15s, `User-Agent` explícito, suporte a `ETag` / `Last-Modified` e hash de conteúdo).
  - Verifica liveness da URL principal e da URL de voucher: rejeita status `>= 400` (exceto auth-walls/anti-bot conhecidos como LinkedIn HTTP 999 / 403 em domínios protegidos, que são preservados como `unverified` em vez de `dead` — **decisão do agente**), redirects para home genérica quando aplicável e padrões explícitos de encerramento (*"ended"*, *"no longer available"*, *"expired"*, *"registration closed"*), atualizando `liveness_status` (`live`, `expired`, `dead`, `unverified`, `error`).
  - **Parser Híbrido:** regras determinísticas por fonte (regex/seletores HTML/RSS) primeiro; se o conteúdo mudar e não bater nos seletores conhecidos, um extrator opcional via **Gemini Free Tier** (`google-genai`, structured output via Pydantic) pode sugerir atualização de campos (`voucher_pct`, `deadline_at`, `is_active`), protegido por **Circuit Breaker** (máx. 20 chamadas/dia) e sem nunca sobrescrever registros manuais fixados pelo usuário.
  - **Registro manual (`add-url` / Aba 2):** formulário na UI e comando CLI para colar uma URL nova encontrada no LinkedIn/evento. **Decisão do agente:** quando Gemini não estiver disponível ou o link for protegido (`auth-wall`), o sistema faz pré-preenchimento determinístico via palavras-chave de URL/HTML (com fallback seguro) e apresenta campos editáveis na UI (`title`, `provider`, `track`, `target_roles`, `skills_covered`, `level`, `deadline_at`) — ou flags opcionais na CLI — antes de gravar no catálogo.

### 5.3 Banco de Dados SQLite (`data/cert_radar.db`)
- **`certifications`**: `id` (slug único), `title`, `provider`, `track` (`official_voucher` | `free_continuous`), `cost_type` (`free` | `voucher_100` | `voucher_discount` | `scholarship`), `discount_pct` (0–100), `normal_price_usd`, `exam_code`, `target_roles` (JSON), `skills_covered` (JSON), `level` (`foundations` | `associate` | `specialty` | `practitioner`), `effort_hours`, `recruiter_signal` (1–5), `url`, `voucher_program_url`, `is_voucher_active` (bool), `activation_epoch` (int, incrementado a cada transição `False -> True`), `deadline_at` (ISO date nullable), `liveness_status` (`live` | `expired` | `dead` | `unverified` | `error`), `source_kind` (`seed` | `manual`), `last_checked_at`, `notes`.
- **`voucher_events`**: histórico de checagens/mudanças (`id`, `cert_id`, `source_name`, `event_type` [`baseline_seed` | `activated` | `deactivated` | `deadline_changed` | `manual_added` | `liveness_changed`], `payload_json`, `detected_at`).
- **`user_progress`**: `cert_id` (PK), `status` (`radar` | `saved` | `studying` | `completed` | `ignored`), `user_notes`, `updated_at`.
- **`alert_log`**: `id`, `cert_id`, `channel` (`windows` | `telegram`), `alert_type` (`new_voucher` | `expiring_7d` | `expiring_48h`), `dedup_key` (UNIQUE), `sent_at`, `delivery_status`.

### 5.4 Motor de Matching & Ranqueamento (`core/matcher.py`)
Para cada certificação com `liveness_status != 'dead'` e `status not in ('completed', 'ignored')`:
1. **Filtro de Redundância (Hard & Soft Dedup):**
   - Exclui/oculta por padrão se o título/código bater com credencial já listada em `cv.md` (`CAPM`, etc.) ou `completed`.
   - Aplica penalidade (-25 pts) a certificações de nível `foundations` cujas `skills_covered` já estejam 100% em `knownSkills` (a menos que seja exame oficial proctored com alto `recruiter_signal >= 4` ou voucher 100% ativo).
2. **Score Ponderado (0–100):**
   - **Role Alignment (35%):** interseção ponderada entre `target_roles` da certificação e `target_roles.primary` / `archetypes` (`primary` tem peso maior que `secondary`).
   - **Gap Closure (25%):** bônus para skills presentes nos `gaps` do `upskill.mjs` / `skipBlockers` / gaps extraídos de `reports/*.md`.
   - **Recruiter Signal (20%):** peso de mercado da credencial (`1..5` normalizado) + bônus para exames oficiais proctored / provedores líderes.
   - **Cost & Urgency (20%):** máximo para `free` ou `voucher_100` ativo; proporcional para `voucher_discount`; bônus de urgência quando `is_voucher_active` e `deadline_at` está a `<= 14 dias`.
3. **Explicabilidade:** retorna `MatchResult(cert, score, score_breakdown, match_reasons, redundancy_warnings)`.

### 5.5 Notificações Ativas & Agendamento (`notify/`)
- **Canais:**
  - `notify/windows_toast.py`: notificação nativa do Windows via `winotify` (com fallback silencioso em PowerShell Toast caso biblioteca não esteja disponível no ambiente).
  - `notify/telegram.py`: envio via HTTP POST na Telegram Bot API (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` via `.env`), com formatação Markdown limpa (título, desconto, prazo, score de fit, link direto).
- **Regras de Disparo Anti-Spam (Decisão do Agente):**
  - Só dispara para itens com `liveness_status == 'live'` e `score >= MIN_ALERT_SCORE` (padrão `65`) ou já marcados como `saved` pelo usuário.
  - **Bootstrap sem spam:** o carregamento inicial de `seed_catalog.json` registra evento `baseline_seed` em `voucher_events` sem disparar notificações.
  - Eventos elegíveis:
    - `new_voucher`: apenas em **transição observada** (`is_voucher_active: False -> True` em `voucher_events`) ou inclusão manual com voucher ativo.
    - `expiring_7d`: prazo entre 3 e 7 dias restantes.
    - `expiring_48h`: prazo `<= 48 horas` restantes.
  - Chave de deduplicação `"{cert_id}:{alert_type}:{activation_epoch}:{deadline_at or 'none'}:{channel}"` impede envio duplicado na mesma campanha, mas permite re-notificar caso um programa recorrente sem data expire e reative meses depois (novo `activation_epoch`).
- **Execução & Agendamento (100% Local na v1):**
  - CLI unificada (`python -m cert_radar ...`): `sync-profile`, `check-radar`, `notify`, `list`, `add-url <url>`.
  - Script PowerShell `scripts/register_task.ps1` para cadastrar execução automática a cada 12h no **Windows Task Scheduler** rodando pelo `.venv` em `D:\Projetos\cert-radar` (disparando Windows Toast + Telegram juntos).
  - **Fora do escopo v1 (confirmado pelo usuário):** sem workflow no GitHub Actions nem sincronização de perfil/estado na nuvem.

### 5.6 Interface Visual Própria (`ui/` — SPA Local Anti-Slop)
- **Diretriz de Design (Taste-Skill / Linear / Dev-tool):**
  - Zero estética de IA clichê (sem brilhos neon, sem roxo decorativo, sem dials circulares e sem firulas flutuantes).
  - Tabela interativa de alta densidade de informação: colunas compactas para *Exame/Código*, *Provedor*, *Trilha*, *Desconto*, *Prazo de Expiração*, *Fit Score* e *Ações Rápidas*.
  - Drawer lateral deslizante (gaveta de inspeção rápida) ao clicar na linha, exibindo decomposição do score nos 4 pilares (*Cargos-Alvo*, *Gaps do CV*, *Recruiter Signal*, *Urgência/Custo*), link oficial e justificativa técnica.
  - Navegação fluida por teclado (`j`/`k` para navegar linhas, `Enter` para abrir gaveta, `Esc` para fechar).
- **Ações Rápidas & Ciclo Fechado:**
  - Status em 1 clique: `Radar` → `Salva` → `Estudando` → `Concluída` / `Ignorar`.
  - Ao marcar `Concluída`: gera snippet formatado pronto para colar na seção `## Certifications` do [cv.md](file:///D:/Projetos/career-ops/cv.md) e cria automaticamente a nota de registro no [Segundo Cérebro](file:///D:/Segundo_Cerebro).
- **Launcher e Servidor Local:**
  - Servido localmente via micro-servidor HTTP Python em `http://localhost:8000`.
  - Launcher Windows `iniciar_cert_radar.bat` na raiz do projeto (abre o browser em 1 clique).

---

## 6. Decisions Made & Frozen via Grilling

1. **Stack UI Anti-Slop:** SPA local leve servida por Python (em vez de Streamlit), garantindo renderização ultra-rápida e fidelidade às regras do *Taste-Skill*.
2. **Setup Telegram Guiado:** CLI `python -m cert_radar setup-telegram` com validação de envio de teste em tempo real.
3. **Persistência:** SQLite local (`data/cert_radar.db`) com transações seguras e histórico de auditoria de alertas.
4. **Catálogo Nuclear Inicial (Seed):** ~20 certificações de altíssimo valor de mercado (Microsoft AI-102, DP-600, Applied Skills; Databricks GenAI/Data Eng; GCP ML/Digital Leader; AWS AI/ML; dbt Certified Developer; Snowflake SnowPro; Anthropic/DeepLearning.AI MCP; FinOps).
5. **Anti-Spam de Bootstrap & Reativação:** O seed inicial grava `baseline_seed` sem disparar alertas; `new_voucher` dispara apenas em transição `False -> True` e a chave de deduplicação inclui `activation_epoch`.
6. **Links Protegidos & Ingestão Manual:** URLs com auth-wall (ex.: LinkedIn HTTP 999/403) ficam como `unverified` (nunca `dead`), e o cadastro manual permite confirmação direta na interface.
7. **Integração Somente Leitura:** `career-ops` permanece 100% protegido contra mutações silenciosas; snippets de conclusão são entregues ao usuário para validação humana.

---

## 7. What's Left to the Builder

- Definir estrutura exata dos pacotes Python (`src/cert_radar/...`), schemas Pydantic e testes unitários/integrados (`pytest`, cobertura >= 80% nos módulos core, matcher, profile bridge, collector e notifier com mocks HTTP/Telegram/Toast).
- Escrever os seletores iniciais por fonte em `config/sources.yaml` e os 20–30 itens iniciais curados em `data/seed_catalog.json` (com validação de liveness real das URLs antes da entrega).
- Implementar o launcher `.bat` / comando `uv run` e o script PowerShell de agendamento no Task Scheduler.
