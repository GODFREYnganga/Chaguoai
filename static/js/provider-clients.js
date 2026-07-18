(function () {
    function esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function renderTimeline(items = []) {
        if (!items.length) return '<p class="muted">No journey events yet.</p>';
        return `
            <div class="journey-timeline">
                ${items.map((item) => `
                    <div class="timeline-item" style="border-left:3px solid var(--primary);padding:0 0 0.75rem 0.75rem;margin-left:0.25rem;">
                        <strong>${esc(item.label)}</strong>
                        <span class="status-pill">${esc(item.status || 'completed')}</span>
                        <div class="muted" style="font-size:0.8rem;">${esc(item.at || '')}</div>
                        ${item.detail ? `<div style="font-size:0.9rem;">${esc(item.detail)}</div>` : ''}
                    </div>
                `).join('')}
            </div>
        `;
    }

    function renderCarePlan(care = {}) {
        return `
            <div class="alert" style="background:#f8fafc;border:1px solid var(--border);">
                <strong>Care Plan:</strong> ${esc(care.care_plan_status || 'not_started')}<br>
                <span class="muted">Selected method: ${esc(care.selected_method || 'None yet')}</span><br>
                <span class="muted">Next follow-up: ${esc(care.next_followup_at || 'Not scheduled')}</span><br>
                <span class="muted">Automation: ${care.automation_enabled ? 'enabled' : 'disabled'} · Consent: ${care.followup_consent ? 'yes' : 'no'}</span>
            </div>
        `;
    }

    function renderReferrals(referrals = []) {
        if (!referrals.length) return '<p class="muted">No referrals recorded.</p>';
        return referrals.map((r) => `
            <div style="padding:0.6rem;border:1px solid var(--border);border-radius:8px;margin-bottom:0.5rem;">
                <strong>${esc(r.referral_destination || r.facility_name || 'Referral')}</strong>
                <span class="status-pill">${esc(r.status || 'pending')}</span>
                <div class="muted" style="font-size:0.85rem;">${esc(r.referral_reason || r.note || '')}</div>
                <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-top:0.5rem;">
                    ${['scheduled', 'completed', 'cancelled'].map((status) =>
                        `<button class="btn btn-secondary btn-sm" onclick='updateReferralStatus(${JSON.stringify(r.id || r.referral_id)}, ${JSON.stringify(status)})'>Mark ${esc(status)}</button>`
                    ).join('')}
                </div>
            </div>
        `).join('');
    }

    function renderAuditTrail(events = []) {
        if (!events.length) return '<p class="muted">No audit events recorded.</p>';
        return events.map((event) => `
            <div style="padding:0.5rem 0;border-bottom:1px solid var(--border);">
                <strong>${esc((event.action || 'audit_event').replace(/_/g, ' '))}</strong>
                <span class="muted" style="font-size:0.8rem;">by ${esc(event.actor || 'system')}</span>
                <div class="muted" style="font-size:0.8rem;">${esc(event.timestamp || '')}</div>
            </div>
        `).join('');
    }

    function renderClinicalReview(data = {}) {
        const packet = {
            safety_summary: { summary: 'Clinician review details' },
            recommendation_confidence: data.confidence_reasoning || {},
        };
        return `
            <div class="recommendation-packet">
                <div class="packet-section">
                    <h4>Confidence Reasoning</h4>
                    ${(data.recommended_methods || []).map((m) => {
                        const c = m.confidence || {};
                        const a = m.adherence_prediction || {};
                        const reasons = c.reasoning || c.confidence_reasons || [];
                        return `
                            <div style="margin-bottom:0.75rem;">
                                <strong>${esc(m.name)}</strong>
                                ${c.score ? `<span class="status-pill">${esc(c.level)} ${esc(c.score)}%</span>` : ''}
                                ${a.available ? `<span class="status-pill">Adherence ${Math.round((a.adherence_score || 0) * 100)}%</span>` : ''}
                                <ul>${reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
                                ${a.model_name ? `
                                    <div class="muted" style="font-size:0.82rem;">
                                        Discontinuation probability: ${a.discontinuation_probability ?? 'n/a'} ·
                                        risk: ${esc(a.adherence_risk_level || 'unknown')} ·
                                        applicability: ${esc(a.model_applicability || 'unknown')} ·
                                        version: ${esc(a.model_version || '')}
                                    </div>
                                    ${(a.adherence_reasons || []).length ? `<ul>${a.adherence_reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
                                ` : ''}
                            </div>
                        `;
                    }).join('') || '<p class="muted">No confidence details available.</p>'}
                </div>
                <div class="packet-section">
                    <h4>Excluded / Contraindicated Methods</h4>
                    ${(data.methods_excluded || []).map((m) => `<p><strong>${esc(m.method_name)}</strong> WHO MEC ${esc(m.mec_category || '')}: ${esc(m.reason || '')}</p>`).join('') || '<p class="muted">No excluded methods recorded.</p>'}
                </div>
                <div class="packet-section">
                    <h4>WHO MEC Rationale</h4>
                    <pre style="white-space:pre-wrap;font-size:0.78rem;">${esc(data.mec_rationale || '')}</pre>
                </div>
                <div class="packet-section">
                    <h4>Override History</h4>
                    ${renderAuditTrail(data.override_history || [])}
                </div>
                <div class="packet-section">
                    <h4>Referral History</h4>
                    ${renderReferrals(data.referral_history || [])}
                </div>
                <div class="packet-section">
                    <h4>Full Audit Trail</h4>
                    ${renderAuditTrail(data.audit_trail || [])}
                </div>
            </div>
        `;
    }

    window.ProviderClients = {
        renderTimeline,
        renderCarePlan,
        renderReferrals,
        renderAuditTrail,
        renderClinicalReview,
    };
})();
