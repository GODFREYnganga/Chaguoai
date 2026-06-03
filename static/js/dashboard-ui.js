/**
 * Shared dashboard UI helpers (admin + provider portals).
 */
(function (global) {
  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
  }

  function formatShortDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
  }

  function showLoading(el, message) {
    if (!el) return;
    el.innerHTML = `<div class="loading-state"><span class="spinner"></span>${escapeHtml(message || 'Loading…')}</div>`;
  }

  function showError(el, message) {
    if (!el) return;
    el.innerHTML = `<div class="error-state">${escapeHtml(message || 'Something went wrong.')}</div>`;
  }

  function showEmpty(el, message) {
    if (!el) return;
    el.innerHTML = `<div class="empty-state">${escapeHtml(message || 'No data yet.')}</div>`;
  }

  /**
   * Render horizontal bar metrics into a scrollable container (not cards).
   */
  function renderMetricBars(container, counts, options) {
    if (!container) return;
    const opts = options || {};
    const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) {
      showEmpty(container, opts.emptyMessage || 'No data');
      return;
    }
    const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
    const maxRows = opts.maxRows || 12;
    container.innerHTML = '';
    entries.slice(0, maxRows).forEach(([label, count]) => {
      const pct = Math.round((count / total) * 100);
      const row = document.createElement('div');
      row.className = 'metric-bar-row';
      row.innerHTML = `
        <div class="metric-bar-meta">
          <span>${escapeHtml(label)}</span>
          <span class="mono">${count} <span class="muted">(${pct}%)</span></span>
        </div>
        <div class="metric-bar-track">
          <div class="metric-bar-fill" style="width:${Math.max(pct, 2)}%"></div>
        </div>`;
      container.appendChild(row);
    });
    if (entries.length > maxRows) {
      const more = document.createElement('p');
      more.className = 'table-footnote';
      more.textContent = `+ ${entries.length - maxRows} more (export CSV for full list)`;
      container.appendChild(more);
    }
  }

  /**
   * 30-day registration trend as CSS column chart.
   */
  function renderTrendChart(container, trend) {
    if (!container) return;
    const points = trend || [];
    if (!points.length) {
      showEmpty(container, 'No registrations in this period');
      return;
    }
    const max = Math.max(...points.map((p) => p.count), 1);
    container.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'trend-chart';
    points.forEach((p) => {
      const h = Math.round((p.count / max) * 100);
      const col = document.createElement('div');
      col.className = 'trend-col';
      col.title = `${p.date}: ${p.count}`;
      col.innerHTML = `
        <div class="trend-bar" style="height:${Math.max(h, 2)}%"></div>
        <span class="trend-label">${escapeHtml(p.date.slice(5))}</span>`;
      wrap.appendChild(col);
    });
    container.appendChild(wrap);
  }

  function renderSimpleTable(container, columns, rows, options) {
    if (!container) return;
    const opts = options || {};
    if (!rows || !rows.length) {
      showEmpty(container, opts.emptyMessage || 'No rows');
      return;
    }
    const thead = columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join('');
    const tbody = rows.map((row) => {
      const cells = columns.map((c) => {
        const raw = typeof c.render === 'function' ? c.render(row) : row[c.key];
        return `<td>${typeof raw === 'string' && raw.includes('<') ? raw : escapeHtml(raw ?? '—')}</td>`;
      }).join('');
      return `<tr${opts.rowAttrs ? opts.rowAttrs(row) : ''}>${cells}</tr>`;
    }).join('');
    container.innerHTML = `
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr>${thead}</tr></thead>
          <tbody>${tbody}</tbody>
        </table>
      </div>`;
  }

  function statusPill(status) {
    const s = String(status || '').toLowerCase();
    let cls = 'status-pill status-warn';
    if (s === 'completed' || s === 'ok') cls = 'status-pill status-ok';
    if (s === 'failed' || s === 'error') cls = 'status-pill status-error';
    return `<span class="${cls}">${escapeHtml(status)}</span>`;
  }

  global.DashboardUI = {
    escapeHtml,
    formatDate,
    formatShortDate,
    showLoading,
    showError,
    showEmpty,
    renderMetricBars,
    renderTrendChart,
    renderSimpleTable,
    statusPill,
  };
})(window);
