# Guia de Deploy Online & Acesso Mobile (CertRadar)

Este guia mostra como colocar o **CertRadar** online com **custo R$ 0,00** para usar diretamente pelo celular (inclusive instalável como app PWA).

---

## Opção 1: Nuvem 24/7 Gratuita via Render (Recomendada)

Fica online permanentemente na nuvem mesmo com o seu PC desligado.

### 1. Enviar para o repositório GitHub (`origin/main`)
O snapshot `data/profile_snapshot.json` já é exportado **sem seu e-mail pessoal** por segurança.

```bash
cd D:\Projetos\cert-radar
git push origin main
```

### 2. Criar o Web Service no Render (Free Tier)
1. Acesse [render.com](https://render.com) e conecte sua conta GitHub.
2. Clique em **New +** → **Blueprint** (ou **Web Service** escolhendo **Docker**).
3. Selecione o repositório `dantinha/cert-radar`. O arquivo `render.yaml` e o `Dockerfile` serão detectados automaticamente.
4. *(Opcional, recomendado)* Na aba **Environment** do Render, defina uma senha para proteger seu painel público:
   - `CERT_RADAR_USER`: `gabriel`
   - `CERT_RADAR_PASSWORD`: *(sua senha forte)*
5. Clique em **Deploy Web Service**. Em ~2 minutos seu link HTTPS estará no ar (ex: `https://cert-radar.onrender.com`).

> **Nota sobre Free Tier:** No plano gratuito da Render, se o serviço hibernar após 15 min sem acesso, o primeiro carregamento leva ~30s e o banco SQLite reinicia com o catálogo seed atualizado (`data/seed_catalog.json`) + seu snapshot (`data/profile_snapshot.json`).

### 3. Instalar como App no Celular (PWA)
- **Android (Chrome):** Abra sua URL do Render → Menu `⋮` → **Adicionar à tela inicial / Instalar aplicativo**.
- **iPhone (Safari):** Abra sua URL → Botão **Compartilhar** → **Adicionar à Tela de Início**.

### 4. Atualizar seu Perfil do `career-ops` na Nuvem
Sempre que atualizar seu currículo ou gerar novos relatórios no `career-ops`:
```bash
uv run cert-radar sync-profile --export
git add data/profile_snapshot.json
git commit -m "chore: update career-ops profile snapshot"
git push
```

---

## Opção 2: Acesso Instantâneo ao PC Local (Cloudflare Quick Tunnel)

Se quiser testar imediatamente no celular conectado direto ao seu banco SQLite e `career-ops` local (sem criar conta na nuvem, enquanto o PC estiver ligado):

1. Inicie o CertRadar em um terminal:
   ```powershell
   cd D:\Projetos\cert-radar
   uv run cert-radar serve --no-browser --port 8000
   ```
2. Em outro terminal, inicie um túnel gratuito com `cloudflared` (ou `winget install Cloudflare.cloudflared`):
   ```powershell
   cloudflared tunnel --url http://127.0.0.1:8000
   ```
3. Copie a URL `https://....trycloudflare.com` exibida e abra no navegador do seu celular!
