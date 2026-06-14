(function () {
    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function pill(label, kind = '') {
        return `<span class="status-pill ${kind}">${esc(label)}</span>`;
    }

    function renderSnapshot(snapshot = {}) {
        const items = [
            ['Age', snapshot.age || '-'],
            ['Postpartum', snapshot.postpartum_status || 'Unknown'],
            ['Breastfeeding', snapshot.breastfeeding_status || 'Unknown'],
            ['Preferences', snapshot.client_preferences || 'None recorded'],
            ['Location', [snapshot.country, snapshot.admin_area].filter(Boolean).join(', ') || '-'],
            ['Channel', snapshot.communication_channel || '-'],
        ];
        return `
            <div class="packet-section">
                <h4>Client Snapshot</h4>
                <div class="packet-grid">
                    ${items.map(([k, v]) => `<div><small class="muted">${esc(k)}</small><strong>${esc(v)}</strong></div>`).join('')}
                </div>
            </div>
        `;
    }

    function renderRiskFlags(flags = []) {
        return `
            <div class="packet-section">
                <h4>Risk Flags</h4>
                ${flags.length ? flags.map((f) => `
                    <div class="alert" style="margin:0.35rem 0;padding:0.55rem;background:#fff7ed;border:1px solid #fed7aa;">
                        <strong>${esc(f.label)}</strong><br><span class="muted">${esc(f.detail)}</span>
                    </div>
                `).join('') : '<p class="muted">No major risk flags detected from recorded answers.</p>'}
            </div>
        `;
    }

    function renderSafety(packet = {}) {
        const summary = packet.safety_summary || {};
        const confidence = packet.recommendation_confidence || {};
        const reasons = confidence.confidence_reasons || confidence.reasons || [];
        const adherence = packet.adherence_model || {};
        return `
            <div class="packet-section">
                <h4>Safety Summary</h4>
                <p>${esc(summary.summary || 'WHO MEC safety assessment completed.')}</p>
                <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
                    ${pill(`Confidence: ${confidence.score || 0}% (${confidence.level || 'Low'})`, 'status-ok')}
                    ${pill(`${summary.safe_method_count || 0} safe option(s)`)}
                    ${pill(`${summary.contraindicated_count || 0} not recommended`, summary.contraindicated_count ? 'status-warn' : '')}
                </div>
                ${reasons.length ? `<ul style="margin:0.75rem 0 0;">${reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
                ${adherence.model_name ? `
                    <p class="muted" style="font-size:0.85rem;margin-top:0.75rem;">
                        Adherence model: ${adherence.available ? 'available' : 'not available'} · mode: ${esc(adherence.mode || 'shadow')} · applicability: ${esc(adherence.applicability || 'unknown')}
                    </p>
                ` : ''}
            </div>
        `;
    }

    function renderMissing(items = []) {
        return `
            <div class="packet-section">
                <h4>Missing Information</h4>
                ${items.length ? `
                    <p class="muted">Additional information may improve recommendation accuracy.</p>
                    <ul>${items.map((m) => `<li><strong>${esc(m.label)}</strong>: ${esc(m.question)}</li>`).join('')}</ul>
                ` : '<p class="muted">No major information gaps detected.</p>'}
            </div>
        `;
    }

    function renderMethodsNotRecommended(items = []) {
        return `
            <div class="packet-section">
                <h4>Methods Not Recommended</h4>
                ${items.length ? items.map((m) => `
                    <div style="padding:0.55rem;border:1px solid var(--border);border-radius:8px;margin:0.35rem 0;">
                        <strong>${esc(m.method_name)}</strong>
                        ${pill(`WHO MEC ${m.mec_category}`, m.severity === 'contraindicated' ? 'status-warn' : '')}
                        <div class="muted" style="font-size:0.85rem;">${esc(m.reason)}</div>
                    </div>
                `).join('') : '<p class="muted">No methods were explicitly excluded by the safety assessment.</p>'}
            </div>
        `;
    }

    function renderCounseling(notes = []) {
        return `
            <div class="packet-section">
                <h4>Counseling Checklist</h4>
                <ul>${(notes || []).map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
            </div>
        `;
    }

    function renderPacket(packet) {
        if (!packet) return '';
        return `
            <div class="recommendation-packet">
                ${renderSnapshot(packet.client_snapshot)}
                ${renderRiskFlags(packet.risk_flags)}
                ${renderSafety(packet)}
                ${renderMissing(packet.missing_information)}
                ${renderMethodsNotRecommended(packet.methods_not_recommended)}
                ${renderCounseling(packet.counseling_notes)}
            </div>
        `;
    }

    window.ProviderRecommendations = {
        renderPacket,
    };
})();
