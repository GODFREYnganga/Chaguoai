/**
 * ChaguoAI Admin Dashboard — table-first analytics, cohort filters, CSV export.
 */
(function () {
  const UI = window.DashboardUI;
  let currentCohort = 'all';

  function showSection(sectionId, navEl) {
    document.querySelectorAll('.content-section').forEach((el) => {
      el.style.display = 'none';
    });
    document.querySelectorAll('.nav-item').forEach((el) => el.classList.remove('active'));
    const target = document.getElementById(sectionId);
    if (target) target.style.display = 'block';
    if (navEl) navEl.classList.add('active');
    if (sectionId === 'approvals') loadApprovals();
    if (sectionId === 'dashboard') loadStats();
  }

  window.showSection = function (sectionId) {
    const navEl = typeof event !== 'undefined' ? event.currentTarget : null;
    showSection(sectionId, navEl);
  };

  function setCohort(cohort, btn) {
    currentCohort = cohort;
    document.querySelectorAll('.cohort-tab').forEach((t) => t.classList.remove('active'));
    if (btn) btn.classList.add('active');
    if (window.currentAdminEventSource) window.currentAdminEventSource.close();
    loadStats();
    connectRealtime();
  }

  window.setCohort = setCohort;

  async function loadStats() {
    const errBox = document.getElementById('dashboard-error');
    if (errBox) errBox.style.display = 'none';

    const panels = ['kpi-strip', 'health-list', 'trend-chart', 'channel-bars', 'language-bars',
      'completion-panel', 'method-bars', 'geo-table', 'completions-table', 'safety-table'];
    panels.forEach((id) => {
      const el = document.getElementById(id);
      if (el) UI.showLoading(el, 'Loading…');
    });

    try {
      const res = await fetch(`/api/admin/stats?cohort=${encodeURIComponent(currentCohort)}`);
      if (res.status === 401) {
        window.location.href = '/admin/login';
        return;
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to load stats');

      renderStats(data);
    } catch (e) {
      console.error(e);
      if (errBox) {
        errBox.className = 'alert alert-error';
        errBox.textContent = e.message || 'Failed to load dashboard';
        errBox.style.display = 'block';
      }
    }
  }

  function renderStats(data) {
    renderKpis(data.kpis || {}, data.pending_providers_count);
    renderHealth(data.health_checks || {});
    UI.renderTrendChart(document.getElementById('trend-chart'), data.registration_trend);
    UI.renderMetricBars(document.getElementById('channel-bars'), data.channels, {
      emptyMessage: 'No channel data',
      maxRows: 8,
    });
    UI.renderMetricBars(document.getElementById('language-bars'), data.languages, {
      emptyMessage: 'No language data',
      maxRows: 8,
    });
    renderCompletion(data.completion || {});
    UI.renderMetricBars(document.getElementById('method-bars'), data.method_distribution, {
      emptyMessage: 'No completed Method Matches in this cohort',
      maxRows: 10,
    });
    renderGeoTable(data.geography_all_time || data.geography || {});
    renderCompletions(data.recent_completions || []);
    renderSafety(data.safety_inbox || []);

    const gen = document.getElementById('generated-at');
    if (gen) gen.textContent = `Live ${UI.formatDate(data.generated_at)} · cohort: ${data.cohort || 'all'}`;
    const badge = document.getElementById('nav-pending-badge');
    const pending = data.pending_providers_count || 0;
    if (badge) {
      badge.textContent = pending;
      badge.style.display = pending > 0 ? 'inline-flex' : 'none';
    }
  }

  function renderKpis(kpis, pendingApprovals) {
    const el = document.getElementById('kpi-strip');
    if (!el) return;
    const items = [
      { label: 'Total clients', value: kpis.total_clients ?? 0, hint: 'Firestore contraceptive_users' },
      { label: 'Matches this week', value: kpis.matches_this_week ?? 0, hint: 'method_match_completed_at' },
      { label: 'Pending approvals', value: pendingApprovals ?? kpis.pending_provider_approvals ?? 0, hint: 'providers.status=pending' },
      { label: 'Active CHWs', value: kpis.active_chws ?? 0, hint: 'approved CHW role' },
      { label: 'System', value: (kpis.system_health || '—'), hint: '/health checks' },
    ];
    el.innerHTML = items.map((i) => `
      <div class="kpi-strip-item" title="${UI.escapeHtml(i.hint)}">
        <span class="kpi-strip-label">${UI.escapeHtml(i.label)}</span>
        <span class="kpi-strip-value">${UI.escapeHtml(String(i.value))}</span>
      </div>`).join('');
  }

  function renderHealth(checks) {
    const el = document.getElementById('health-list');
    if (!el) return;
    const skip = new Set(['overall']);
    const rows = Object.entries(checks).filter(([k]) => !skip.has(k));
    if (!rows.length) {
      UI.showEmpty(el, 'Health checks unavailable');
      return;
    }
    el.innerHTML = rows.map(([name, info]) => {
      const ok = info && info.ok;
      const pill = ok ? '<span class="status-pill status-ok">OK</span>' : '<span class="status-pill status-error">Issue</span>';
      return `<div class="health-row">
        <span><strong>${UI.escapeHtml(name)}</strong><br><small class="muted">${UI.escapeHtml(info?.detail || '')}</small></span>
        ${pill}
      </div>`;
    }).join('');
  }

  function renderCompletion(c) {
    const el = document.getElementById('completion-panel');
    if (!el) return;
    el.innerHTML = `
      <div class="completion-grid">
        <div><span class="muted">Started</span><strong>${c.started ?? 0}</strong></div>
        <div><span class="muted">Completed</span><strong>${c.completed ?? 0}</strong></div>
        <div><span class="muted">Failed</span><strong>${c.failed ?? 0}</strong></div>
        <div><span class="muted">In progress</span><strong>${c.pending ?? 0}</strong></div>
      </div>
      <p class="completion-rate">Completion rate: <strong>${c.completion_rate_percent ?? 0}%</strong></p>
      <div class="donut-wrap" aria-hidden="true">
        <div class="donut" style="--pct:${c.completion_rate_percent || 0}"></div>
        <span class="donut-label">${c.completion_rate_percent ?? 0}%</span>
      </div>`;
  }

  function renderGeoTable(geo) {
    const el = document.getElementById('geo-table');
    const foot = document.getElementById('geo-footnote');
    const rows = Object.entries(geo.by_country || {}).map(([country, count]) => ({
      country,
      count,
    }));
    UI.renderSimpleTable(el, [
      { key: 'country', label: 'Country' },
      { key: 'count', label: 'Clients' },
    ], rows, { emptyMessage: 'No geography captured yet' });
    if (foot) {
      foot.textContent = `Located clients: ${geo.clients_with_location || 0}. Unmatched: ${geo.unmatched_country_count || 0} (${geo.unmatched_rate_percent || 0}%).`;
    }
  }

  function renderCompletions(rows) {
    const el = document.getElementById('completions-table');
    UI.renderSimpleTable(el, [
      { key: 'name', label: 'Client' },
      { key: 'channel', label: 'Channel' },
      { key: 'method_category_primary', label: 'Primary method' },
      { key: 'country', label: 'Country' },
      { key: 'completed_at', label: 'Completed', render: (r) => UI.formatShortDate(r.completed_at) },
      { key: 'status', label: 'Status', render: (r) => UI.statusPill(r.status) },
    ], rows, { emptyMessage: 'No completions in this cohort' });
  }

  function renderSafety(items) {
    const el = document.getElementById('safety-table');
    UI.renderSimpleTable(el, [
      { key: 'type', label: 'Type', render: (r) => UI.escapeHtml((r.type || '').replace(/_/g, ' ')) },
      { key: 'phone', label: 'Phone' },
      { key: 'source', label: 'Source' },
      { key: 'at', label: 'When', render: (r) => UI.formatDate(r.at) },
      { key: 'report', label: 'Summary', render: (r) => UI.escapeHtml((r.report || '').slice(0, 120)) },
    ], items, { emptyMessage: 'No safety items — good news' });
  }

  async function loadApprovals() {
    const tbody = document.getElementById('approvals-table');
    try {
      const res = await fetch('/api/admin/pending_providers');
      if (res.status === 401) {
        window.location.href = '/admin/login';
        return;
      }
      const data = await res.json();
      tbody.innerHTML = '';
      if (!data.providers || !data.providers.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">No pending applications.</td></tr>';
        return;
      }
      data.providers.forEach((p) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${UI.escapeHtml(p.fullName)}</strong></td>
          <td><span class="badge ${p.role === 'chw' ? 'badge-chw' : 'badge-clinician'}">${UI.escapeHtml((p.role || '').toUpperCase())}</span></td>
          <td>${UI.escapeHtml(p.credentials)}</td>
          <td>${UI.escapeHtml(p.email)}<br><small>${UI.escapeHtml(p.phone)}</small></td>
          <td><button class="btn btn-primary btn-sm" data-id="${UI.escapeHtml(p.id)}">Approve</button></td>`;
        tr.querySelector('button').addEventListener('click', () => approveProvider(p.id));
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="5" class="error-state">Failed to load applications</td></tr>';
    }
  }

  async function approveProvider(id) {
    const alertBox = document.getElementById('alert-box');
    alertBox.style.display = 'none';
    try {
      const res = await fetch(`/api/admin/approve_provider/${id}`, { method: 'POST' });
      if (!res.ok) throw new Error('Approve failed');
      alertBox.className = 'alert alert-success';
      alertBox.textContent = 'Provider approved.';
      alertBox.style.display = 'block';
      loadApprovals();
      loadStats();
    } catch (e) {
      alertBox.className = 'alert alert-error';
      alertBox.textContent = e.message;
      alertBox.style.display = 'block';
    }
  }

  window.exportClientsCsv = function () {
    window.location.href = '/api/admin/export/clients.csv';
  };

  function connectRealtime() {
    if (!window.EventSource) return;
    const source = new EventSource(`/api/admin/events?cohort=${encodeURIComponent(currentCohort)}`);
    source.addEventListener('stats', (event) => {
      try {
        renderStats(JSON.parse(event.data));
      } catch (e) {
        console.warn('Could not parse admin event', e);
      }
    });
    source.addEventListener('error', () => {
      source.close();
      setTimeout(loadStats, 10000);
    });
    window.currentAdminEventSource = source;
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    connectRealtime();
  });
})();
