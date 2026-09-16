"use strict";
(() => {
  const panel = document.querySelector('[data-work-setup]');
  if (!panel) return;
  const form = document.querySelector('#budget-form');
  const select = document.querySelector('#prepare-local-work select');
  const freshness = panel.querySelector('[data-setup-freshness]');
  let dirty = false, busy = false, pending = false, timer, generation = 0;
  let saved = null;
  const values = () => ({daily_jobs:Number(form.elements.daily_jobs.value), share:Number(form.elements.share.value), enabled:form.elements.enabled.checked});
  function budgetPreview() {
    if (!form) return;
    const value = values(), cap = Math.floor(value.daily_jobs * value.share / 100);
    let text = `${value.daily_jobs} daily tasks × ${value.share}% = ${cap} tasks/day, shared across your agents. `;
    if (!value.enabled) text += 'Paused: new work is disabled.';
    else if (!cap) {
      text += 'This allows zero tasks even though work is enabled. ';
      const minimum = value.share ? Math.ceil(100 / value.share) : 0;
      text += minimum && minimum <= 20 ? `To keep ${value.share}%, set the daily budget to at least ${minimum}.` : 'Increase the share and daily budget to allow at least one whole task.';
    } else text += `${Math.max(0, cap - Number(form.dataset.used))} remaining today. Reset: 00:00 UTC.`;
    document.querySelector('#budget-preview').textContent = text;
  }
  function saveState(message) { document.querySelector('#budget-save-state').textContent = message; }
  if (form) {
    saved = values();
    form.addEventListener('input', () => {
      dirty = JSON.stringify(values()) !== JSON.stringify(saved);
      saveState(dirty ? 'Unsaved changes — save before continuing. Other pages still use your saved budget.' : 'These are your saved settings.');
      budgetPreview();
    });
    document.querySelector('#budget-continue').addEventListener('click', event => {
      if (dirty) { event.preventDefault(); saveState('Save your changes before continuing to Work locally.'); form.querySelector('button').focus(); }
    });
    window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
    bind('#budget-form', async () => {
      const submitted = values();
      const result = await api('/api/me/budget', submitted, 'PUT');
      saved = submitted;
      dirty = JSON.stringify(values()) !== JSON.stringify(saved);
      form.dataset.used = result.claimed_today;
      saveState(dirty ? 'Budget saved. You have additional unsaved changes.' : 'Budget saved. Your agents now use these settings.');
      budgetPreview();
      await poll();
    });
    budgetPreview();
  }
  function render(setup) {
    panel.dataset.agent = setup.agent_id;
    panel.dataset.code = setup.code;
    panel.querySelector('[data-setup-message]').textContent = setup.message;
    const steps = setup.steps.map(text => { const li = document.createElement('li'); li.textContent = text; return li; });
    panel.querySelector('[data-setup-steps]').replaceChildren(...steps);
    panel.querySelector('[data-setup-actions]').replaceChildren(...setup.actions.map(recoveryLink).filter(Boolean));
    freshness.textContent = 'Saved setup is current · updates after changes and every five seconds.';
    document.querySelectorAll('[data-budget-option]').forEach(el => { el.hidden = !setup.needs_budget; });
    const resume = document.querySelector('[data-resume-option]');
    if (resume) resume.hidden = !setup.needs_resume;
    if (select) {
      document.querySelector('[data-local-manage]').href = `/my-agents/${encodeURIComponent(setup.agent_id)}#work-queue`;
      document.querySelector('[data-local-budget]').href = `/contribute?agent_id=${encodeURIComponent(setup.agent_id)}#budget-form`;
    }
    if (form) {
      const next = {daily_jobs:setup.budget.daily_jobs, share:setup.budget.share, enabled:Boolean(setup.budget.enabled)};
      if (JSON.stringify(saved) !== JSON.stringify(next)) {
        if (dirty) saveState('Saved budget changed in another tab. Your unsaved edits are preserved; saving will replace the saved settings.');
        else {
          form.elements.daily_jobs.value = next.daily_jobs;
          form.elements.share.value = next.share;
          form.elements.enabled.checked = next.enabled;
          document.querySelector('#share-output').textContent = `${next.share}%`;
          saveState('Saved budget updated from your account.');
        }
        saved = next;
      }
      form.dataset.used = setup.budget.claimed_today;
      budgetPreview();
    }
  }
  async function poll() {
    clearTimeout(timer);
    if (document.hidden) return;
    if (busy) { pending = true; return; }
    busy = true;
    const version = generation, aid = select?.value || panel.dataset.agent;
    try {
      const response = await fetch('/api/me/work-setup?agent_id='+encodeURIComponent(aid), {credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000)});
      if (!response.ok) throw new Error(response.status === 401 ? 'Session ended. Sign in again to refresh your setup.' : 'Setup could not be refreshed. Displayed settings may be old.');
      const setup = await response.json();
      if (version === generation) render(setup);
    } catch (error) {
      freshness.textContent = error.message;
      if (error.message.startsWith('Session ended')) freshness.append(' ', recoveryLink({label:'Sign in again',href:'/login'}));
    } finally {
      busy = false;
      timer = setTimeout(poll, pending ? 0 : 5000);
      pending = false;
    }
  }
  select?.addEventListener('change', () => {
    generation++;
    const checkbox = document.querySelector('[name=enable_one_job_budget]');
    if (checkbox) checkbox.checked = false;
    const url = new URL(window.location.href); url.searchParams.set('agent_id', select.value); history.replaceState(null, '', url);
    poll();
  });
  window.addEventListener('catalyst-state-changed', poll);
  window.addEventListener('focus', poll);
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else poll(); });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  window.addEventListener('pageshow', poll);
  poll();
})();
