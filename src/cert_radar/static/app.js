/**
 * CertRadar SPA — Client Application Logic
 * Anti-slop dev-tool aesthetic with Linear/Raycast style interactions.
 */

// Application State
const state = {
  profile: null,
  certs: [],
  filteredCerts: [],
  selectedId: null,
  currentTab: 'all',
  searchQuery: '',
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initApp();
  setupKeyboardShortcuts();
});

async function initApp() {
  await Promise.all([loadProfile(), loadCerts()]);
}

async function loadProfile() {
  try {
    const res = await fetch('/api/profile');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.profile = data;

    const brandMeta = document.getElementById('brandMeta');
    const roles = (data.target_roles || []).slice(0, 2).join(' / ') || 'AI Specialist';
    const gapsCount = data.gaps_count || (data.gaps || []).length || 0;
    brandMeta.innerHTML = `Perfil: <strong style="color:var(--text-main)">${escapeHtml(data.full_name || 'Candidato')}</strong> (${escapeHtml(roles)}) • ${gapsCount} Gaps mapeados via <code class="mono">career-ops</code>`;
  } catch (err) {
    console.error('Failed to load profile:', err);
    document.getElementById('brandMeta').innerText = 'Modo Offline / Perfil local';
  }
}

async function loadCerts() {
  try {
    const res = await fetch('/api/certs');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.certs = Array.isArray(data) ? data : data.certifications || [];
    applyFilters();
    updateMetrics();

    if (state.certs.length > 0) {
      selectCert(state.certs[0].id);
    }
  } catch (err) {
    console.error('Failed to load certs:', err);
    const tbody = document.getElementById('certTableBody');
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Erro ao conectar à API local (/api/certs). Verifique se o servidor está ativo.</td></tr>`;
  }
}

// --- Metrics & HUD ---
function updateMetrics() {
  const certs = state.certs;

  // 1. Vouchers Ativos
  const vouchers = certs.filter(c => c.is_voucher_active || c.track === 'official_voucher' || c.discount_pct > 0);
  document.getElementById('metricVouchers').innerText = vouchers.length;

  // 2. Prazo Crítico (< 48h)
  const now = new Date();
  let urgentCount = 0;
  let nearestTitle = '';
  certs.forEach(c => {
    if (c.deadline_at) {
      const deadline = new Date(c.deadline_at);
      const diffHours = (deadline - now) / (1000 * 60 * 60);
      if (diffHours > 0 && diffHours <= 48) {
        urgentCount++;
        if (!nearestTitle) nearestTitle = `${c.exam_code || c.title} (< 48h)`;
      }
    }
  });
  document.getElementById('metricUrgent').innerText = urgentCount;
  if (urgentCount > 0 && nearestTitle) {
    document.getElementById('metricUrgentDesc').innerText = nearestTitle;
  } else {
    document.getElementById('metricUrgentDesc').innerText = 'Nenhum prazo expirando hoje';
  }

  // 3. Micro-credenciais gratuitas
  const free = certs.filter(c => c.cost_type === 'free' || c.track === 'free_continuous' || c.discount_pct === 100);
  document.getElementById('metricFree').innerText = free.length;

  // 4. Fit Médio
  if (certs.length > 0) {
    const sum = certs.reduce((acc, c) => acc + (c.score || 0), 0);
    const avg = Math.round(sum / certs.length);
    document.getElementById('metricFit').innerText = `${avg}%`;
  } else {
    document.getElementById('metricFit').innerText = '--';
  }

  // Tab counters
  document.getElementById('countAll').innerText = certs.length;
  document.getElementById('countVouchers').innerText = vouchers.length;
  document.getElementById('countFree').innerText = certs.filter(c => c.cost_type === 'free' || c.track === 'free_continuous').length;
  document.getElementById('countSaved').innerText = certs.filter(c => c.user_progress && c.user_progress.status === 'saved').length;
}

// --- Filtering & Searching ---
function setFilter(tab, btn) {
  state.currentTab = tab;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}

function filterSearch(val) {
  state.searchQuery = val.trim().toLowerCase();
  applyFilters();
}

function applyFilters() {
  const query = state.searchQuery;
  const tab = state.currentTab;

  state.filteredCerts = state.certs.filter(cert => {
    // Tab match
    let tabMatch = true;
    if (tab === 'voucher') {
      tabMatch = cert.track === 'official_voucher' || cert.is_voucher_active || cert.discount_pct > 0;
    } else if (tab === 'free') {
      tabMatch = cert.track === 'free_continuous' || cert.cost_type === 'free';
    } else if (tab === 'saved') {
      tabMatch = cert.user_progress && cert.user_progress.status === 'saved';
    }

    if (!tabMatch) return false;

    // Search query match
    if (!query) return true;
    const searchable = [
      cert.title,
      cert.provider,
      cert.exam_code,
      cert.track,
      ...(cert.skills_covered || []),
      ...(cert.target_roles || []),
    ].filter(Boolean).join(' ').toLowerCase();

    return searchable.includes(query);
  });

  renderTable();
}

// --- Table Rendering ---
function renderTable() {
  const tbody = document.getElementById('certTableBody');
  if (state.filteredCerts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Nenhuma certificação encontrada para este filtro.</td></tr>`;
    return;
  }

  let html = '';
  state.filteredCerts.forEach(cert => {
    const isSelected = cert.id === state.selectedId;
    const isSaved = cert.user_progress && cert.user_progress.status === 'saved';

    // Score badge class
    let scoreClass = 'score-low';
    if (cert.score >= 85) scoreClass = 'score-high';
    else if (cert.score >= 70) scoreClass = 'score-medium';

    // Track pill
    let trackPill = '';
    if (cert.discount_pct === 100) {
      trackPill = `<span class="status-pill pill-voucher-100">100% OFF</span>`;
    } else if (cert.discount_pct > 0) {
      trackPill = `<span class="status-pill pill-voucher-50">${cert.discount_pct}% OFF</span>`;
    } else if (cert.cost_type === 'free') {
      trackPill = `<span class="status-pill pill-free">Gratuita</span>`;
    } else {
      trackPill = `<span class="status-pill pill-voucher-50">${escapeHtml(cert.track)}</span>`;
    }

    // Deadline pill / text
    const deadlineText = formatDeadline(cert);

    // Gaps chips
    const gapsHtml = (cert.skills_covered || []).slice(0, 3)
      .map(s => `<span class="gap-tag">${escapeHtml(s)}</span>`)
      .join('');

    html += `
      <tr class="${isSelected ? 'selected' : ''}" data-id="${escapeHtml(cert.id)}" onclick="selectCert('${escapeHtml(cert.id)}')">
        <td>
          <span class="score-badge ${scoreClass}">${cert.score || 0}%</span>
        </td>
        <td>
          <div class="exam-title-cell">
            <div class="exam-title-row">
              <span class="exam-name">${escapeHtml(cert.title)}</span>
              ${cert.exam_code ? `<span class="exam-code-tag">${escapeHtml(cert.exam_code)}</span>` : ''}
            </div>
            <div class="gaps-list">
              <span>Alinhamento:</span>
              ${gapsHtml}
            </div>
          </div>
        </td>
        <td>${escapeHtml(cert.provider)}</td>
        <td>${trackPill}</td>
        <td>${deadlineText}</td>
        <td style="text-align: right;">
          <button class="btn-action-small ${isSaved ? 'saved' : ''}" title="Salvar / Remover dos favoritos" onclick="toggleSave('${escapeHtml(cert.id)}', event)">
            ${isSaved ? '★' : '⭐'}
          </button>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

function formatDeadline(cert) {
  if (!cert.deadline_at) {
    return `<span style="color:var(--accent-emerald); font-family:var(--font-mono); font-size:11px;">Sem expiração</span>`;
  }

  const now = new Date();
  const deadline = new Date(cert.deadline_at);
  const diffHours = (deadline - now) / (1000 * 60 * 60);

  if (diffHours <= 0) {
    return `<span style="color:var(--text-dim); font-family:var(--font-mono); font-size:11px;">Expirado</span>`;
  }
  if (diffHours <= 48) {
    return `<span class="status-pill pill-urgent">⏳ ${Math.round(diffHours)}h restantes</span>`;
  }
  const diffDays = Math.ceil(diffHours / 24);
  return `<span style="color:var(--text-muted); font-family:var(--font-mono); font-size:11px;">${diffDays} dias</span>`;
}

// --- Selection & Inspector Drawer ---
function selectCert(certId) {
  state.selectedId = certId;
  const cert = state.certs.find(c => c.id === certId);
  if (!cert) return;

  // Highlight row in table
  document.querySelectorAll('#certTableBody tr').forEach(tr => {
    if (tr.getAttribute('data-id') === certId) {
      tr.classList.add('selected');
    } else {
      tr.classList.remove('selected');
    }
  });

  // Populate drawer
  document.getElementById('dTitle').innerText = cert.title;
  document.getElementById('dCode').innerText = `${cert.exam_code ? `Exame ${cert.exam_code} • ` : ''}Provedor: ${cert.provider} • Nível: ${cert.level || 'Associate'}`;

  // Voucher Badge
  const vBadge = document.getElementById('dVoucherBadge');
  if (cert.discount_pct === 100) {
    vBadge.innerText = '100% OFF';
    vBadge.className = 'status-pill pill-voucher-100';
  } else if (cert.discount_pct > 0) {
    vBadge.innerText = `${cert.discount_pct}% OFF`;
    vBadge.className = 'status-pill pill-voucher-50';
  } else {
    vBadge.innerText = 'Gratuita';
    vBadge.className = 'status-pill pill-free';
  }

  // Score breakdown
  const bd = cert.score_breakdown || {};
  document.getElementById('dScoreRole').innerText = `${bd.role_score ?? '--'} / 35`;
  document.getElementById('dScoreGap').innerText = `${bd.gap_score ?? '--'} / 25`;
  document.getElementById('dScoreSignal').innerText = `${bd.signal_score ?? '--'} / 20`;
  document.getElementById('dScoreCost').innerText = `${bd.cost_score ?? '--'} / 20`;

  // Justification
  const justBox = document.getElementById('dJustification');
  let reasonsText = (cert.match_reasons || []).join(' • ');
  if (!reasonsText) {
    reasonsText = `Certificação com excelente fit curricular para ${cert.provider}, fechando competências em ${(cert.skills_covered || []).join(', ')}.`;
  }
  if (cert.redundancy_warning) {
    reasonsText += `\n\n⚠️ ${cert.redundancy_warning}`;
  }
  justBox.innerText = reasonsText;

  // Status buttons
  const currentStatus = (cert.user_progress && cert.user_progress.status) || 'radar';
  document.querySelectorAll('.status-btn').forEach(btn => {
    if (btn.getAttribute('data-status') === currentStatus) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Official link
  const linkEl = document.getElementById('dLink');
  linkEl.href = cert.voucher_program_url || cert.url || '#';
}

// --- Status Updates & Progress ---
async function updateCurrentStatus(newStatus) {
  if (!state.selectedId) return;

  const cert = state.certs.find(c => c.id === state.selectedId);
  if (!cert) return;

  try {
    const res = await fetch('/api/progress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cert_id: cert.id, status: newStatus }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    if (!cert.user_progress) cert.user_progress = {};
    cert.user_progress.status = newStatus;

    selectCert(cert.id);
    updateMetrics();
    applyFilters();
    showToast(`Status atualizado para: ${newStatus.toUpperCase()}`);
  } catch (err) {
    console.error('Error updating status:', err);
    showToast('Falha ao atualizar status.', true);
  }
}

async function toggleSave(certId, event) {
  if (event) event.stopPropagation();

  const cert = state.certs.find(c => c.id === certId);
  if (!cert) return;

  const current = cert.user_progress && cert.user_progress.status;
  const nextStatus = current === 'saved' ? 'radar' : 'saved';

  try {
    const res = await fetch('/api/progress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cert_id: certId, status: nextStatus }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    if (!cert.user_progress) cert.user_progress = {};
    cert.user_progress.status = nextStatus;

    if (state.selectedId === certId) {
      selectCert(certId);
    }
    updateMetrics();
    applyFilters();
    showToast(nextStatus === 'saved' ? '⭐ Salvo nos favoritos' : 'Removido dos favoritos');
  } catch (err) {
    console.error('Error toggling save:', err);
    showToast('Falha ao atualizar favorito.', true);
  }
}

// --- Snippet Generation & Clipboard ---
async function generateAndCopySnippet(type) {
  if (!state.selectedId) {
    showToast('Selecione uma certificação primeiro.', true);
    return;
  }

  try {
    const res = await fetch('/api/generate-snippet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cert_id: state.selectedId }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const textToCopy = type === 'cv' ? data.cv_snippet : data.obsidian_snippet;
    await navigator.clipboard.writeText(textToCopy);

    const targetLabel = type === 'cv' ? 'cv.md' : 'Segundo Cérebro';
    showToast(`📋 Snippet copiado para colar no ${targetLabel}!`);
  } catch (err) {
    console.error('Error generating snippet:', err);
    showToast('Falha ao gerar snippet.', true);
  }
}

// --- Add URL Modal ---
function openAddModal() {
  document.getElementById('addModal').classList.add('open');
  document.getElementById('addTitle').focus();
}

function closeAddModal() {
  document.getElementById('addModal').classList.remove('open');
}

async function submitAddUrl() {
  const title = document.getElementById('addTitle').value.trim();
  const url = document.getElementById('addUrl').value.trim();
  const provider = document.getElementById('addProvider').value.trim() || 'Custom';
  const examCode = document.getElementById('addExamCode').value.trim() || null;
  const track = document.getElementById('addTrack').value;
  const discountPct = parseInt(document.getElementById('addDiscount').value, 10) || 0;
  const skillsInput = document.getElementById('addSkills').value.trim();
  const skills = skillsInput ? skillsInput.split(',').map(s => s.trim()).filter(Boolean) : [];

  if (!title || !url) {
    showToast('Preencha título e URL obrigatórios.', true);
    return;
  }

  try {
    const payload = {
      title,
      url,
      provider,
      exam_code: examCode,
      track,
      discount_pct: discountPct,
      skills_covered: skills,
      cost_type: discountPct === 100 ? 'voucher_100' : (discountPct > 0 ? 'voucher_discount' : 'free'),
    };

    const res = await fetch('/api/add-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const newCert = await res.json();

    closeAddModal();
    showToast(`✅ "${newCert.title}" cadastrada com sucesso!`);

    // Reload certs and select newly created
    await loadCerts();
    if (newCert.id) {
      selectCert(newCert.id);
    }
  } catch (err) {
    console.error('Error adding url:', err);
    showToast('Falha ao cadastrar URL.', true);
  }
}

// --- Keyboard Shortcuts (Linear style) ---
function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // If inside input or modal, only handle Escape
    const activeEl = document.activeElement;
    const isInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'SELECT');

    if (e.key === 'Escape') {
      closeAddModal();
      return;
    }

    if (isInput) return;

    const visibleRows = Array.from(document.querySelectorAll('#certTableBody tr[data-id]'));
    if (visibleRows.length === 0) return;

    let currentIndex = visibleRows.findIndex(tr => tr.classList.contains('selected'));

    if (e.key === 'j') {
      e.preventDefault();
      const nextIndex = currentIndex < visibleRows.length - 1 ? currentIndex + 1 : 0;
      const nextId = visibleRows[nextIndex].getAttribute('data-id');
      selectCert(nextId);
      visibleRows[nextIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'k') {
      e.preventDefault();
      const prevIndex = currentIndex > 0 ? currentIndex - 1 : visibleRows.length - 1;
      const prevId = visibleRows[prevIndex].getAttribute('data-id');
      selectCert(prevId);
      visibleRows[prevIndex].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'o') {
      e.preventDefault();
      const link = document.getElementById('dLink').href;
      if (link && link !== '#') {
        window.open(link, '_blank');
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      document.getElementById('inspectorDrawer').scrollIntoView({ behavior: 'smooth' });
    }
  });
}

// --- Utilities ---
function showToast(message, isError = false) {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = 'toast';
  if (isError) toast.style.borderColor = 'var(--accent-red)';
  toast.innerText = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
