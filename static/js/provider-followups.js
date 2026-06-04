(function () {
    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function groupByClient(tasks = []) {
        const map = {};
        tasks.forEach((task) => {
            const phone = task.phone || '';
            if (!map[phone]) {
                map[phone] = {
                    phone,
                    name: task.client_name || phone,
                    method: task.method || '',
                    due: 0,
                    awaiting: 0,
                    attention: 0,
                    upcoming: 0,
                    tasks: [],
                };
            }
            map[phone].tasks.push(task);
            const status = task.status || 'due';
            if (['no_response', 'needs_chw_attention', 'client_replied'].includes(status)) map[phone].attention += 1;
            else if (status === 'sent') map[phone].awaiting += 1;
            else if (['due', 'pending'].includes(status)) map[phone].due += 1;
            else map[phone].upcoming += 1;
        });
        return Object.values(map).sort((a, b) => (b.attention - a.attention) || (b.due - a.due));
    }

    function renderClientRows(groups = []) {
        if (!groups.length) {
            return '<p class="empty-state">No follow-up clients yet. Follow-ups appear after you select a method for a client.</p>';
        }
        return groups.map((g) => `
            <div class="followup-client-row" style="display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:0.75rem 0;border-bottom:1px solid var(--border);flex-wrap:wrap;">
                <div>
                    <strong>${esc(g.name)}</strong>
                    <div class="muted mono" style="font-size:0.8rem;">${esc(g.phone)}</div>
                    <div class="muted" style="font-size:0.8rem;">${esc(g.method || '-')} · ${g.due} due · ${g.awaiting} awaiting · ${g.attention} needs CHW</div>
                </div>
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                    <button class="btn btn-primary btn-sm" onclick='sendComposedFollowup(${JSON.stringify(g.phone)}, ${JSON.stringify(g.name)}, ${JSON.stringify(g.method)})'>Send follow-up</button>
                    <button class="btn btn-secondary btn-sm" onclick='openFollowupComposeForClient(${JSON.stringify(g.phone)}, ${JSON.stringify(g.name)}, ${JSON.stringify(g.method)})'>Edit message</button>
                    <button class="btn btn-secondary btn-sm" onclick='openClientDrawer(${JSON.stringify(g.phone)})'>Open client</button>
                </div>
            </div>
        `).join('');
    }

    window.ProviderFollowups = {
        groupByClient,
        renderClientRows,
    };
})();
