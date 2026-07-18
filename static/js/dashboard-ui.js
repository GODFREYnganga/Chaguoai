/**
 * Shared dashboard UI helpers (admin + provider portals).
 */
(function (global) {
  let trendChartInstance = null;
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
    el.innerHTML = `
      <div class="skeleton-row" style="opacity: 0.85;">
        <div class="skeleton skeleton-title"></div>
        <div class="skeleton skeleton-text"></div>
        <div class="skeleton skeleton-text short"></div>
      </div>
      <div class="skeleton-row" style="opacity: 0.6;">
        <div class="skeleton skeleton-text"></div>
        <div class="skeleton skeleton-text short"></div>
      </div>
    `;
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

  function renderTrendChart(container, trend) {
    if (!container) return;
    const points = trend || [];
    if (!points.length) {
      showEmpty(container, 'No registrations in this period');
      return;
    }
    if (typeof Chart === 'undefined') {
      container.innerHTML = '<p class="muted">Chart.js library is not available. Please check connection.</p>';
      return;
    }
    
    // Clear container and create canvas
    container.innerHTML = '<canvas id="trendChartCanvas" style="max-height: 220px; width: 100%;"></canvas>';
    const ctx = document.getElementById('trendChartCanvas').getContext('2d');
    
    const labels = points.map(p => p.date.slice(5));
    const counts = points.map(p => p.count);
    
    if (trendChartInstance) {
      trendChartInstance.destroy();
    }
    
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? '#334155' : '#e2e8f0';
    const textColor = isDark ? '#94a3b8' : '#64748b';
    const primaryColor = isDark ? '#60a5fa' : '#1e3a8a';
    
    trendChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Registrations',
          data: counts,
          borderColor: primaryColor,
          backgroundColor: isDark ? 'rgba(96, 165, 250, 0.1)' : 'rgba(30, 58, 138, 0.05)',
          borderWidth: 2,
          fill: true,
          tension: 0.3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            grid: { color: gridColor },
            ticks: { color: textColor, font: { family: 'Inter' } }
          },
          y: {
            beginAtZero: true,
            grid: { color: gridColor },
            ticks: { color: textColor, stepSize: 1, font: { family: 'Inter' } }
          }
        }
      }
    });
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
        return `<td data-label="${escapeHtml(c.label)}">${typeof raw === 'string' && (raw.includes('<') || raw.includes('&lt;')) ? raw : escapeHtml(raw ?? '—')}</td>`;
      }).join('');
      return `<tr${opts.rowAttrs ? opts.rowAttrs(row) : ''}>${cells}</tr>`;
    }).join('');
    container.innerHTML = `
      <div class="table-scroll">
        <table class="data-table ${opts.tableClass || ''}">
          <thead><tr>${thead}</tr></thead>
          <tbody>${tbody}</tbody>
        </table>
      </div>`;
  }

  function maskPhone(phone) {
    if (!phone) return '—';
    let clean = String(phone).replace('whatsapp:', '').trim();
    if (clean.startsWith('+')) {
      if (clean.length > 8) {
        return clean.substring(0, 7) + ' *** ' + clean.substring(clean.length - 3);
      }
    } else if (clean.startsWith('0')) {
      if (clean.length > 6) {
        return clean.substring(0, 4) + ' *** ' + clean.substring(clean.length - 3);
      }
    }
    if (clean.length > 5) {
      return clean.substring(0, 2) + ' *** ' + clean.substring(clean.length - 2);
    }
    return clean;
  }

  function maskName(name) {
    if (!name) return '—';
    const s = String(name).trim();
    if (s.startsWith('+') || (s.startsWith('0') && /^\d+$/.test(s.replace(/[\s\-]/g, '')))) {
      return maskPhone(s);
    }
    if (s.toLowerCase() === 'friend') {
      return '—';
    }
    const parts = s.split(/\s+/);
    return parts.map(p => {
      if (p.length > 2) {
        return p[0] + '*'.repeat(p.length - 2) + p[p.length - 1];
      }
      return p[0] + '*';
    }).join(' ');
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
    maskPhone,
    maskName,
  };
})(window);
