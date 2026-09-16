"use strict";
// Render only observed state, without reloading forms or injecting worker HTML.
(() => {
  const panels = [...document.querySelectorAll('[data-activity-agent]')];
  if (!panels.length) return;
  const notice = document.querySelector('#activity-refresh');
  let timer, busy = false, stopped = false;
  function element(tag, text, href) {
    const node = document.createElement(tag); node.textContent = text;
    if (href) node.href = href;
    return node;
  }
  const when = timestamp => new Date(timestamp * 1000).toLocaleString();
  function render(panel, live) {
    panel.dataset.state = live.state;
    const set = (key, text) => {panel.querySelector(`[data-live="${key}"]`).textContent = text;};
    set('label', live.label); set('reason', live.reason);
    set('connection', live.worker.seen ? `Last check-in ${when(live.worker.last_seen)} · ${live.worker.runtime} worker` : 'No check-in with the current token');
    set('model', live.worker.runtime === 'simulation' ? 'Simulation only · no model inference' : live.worker.model_label ?
      `Worker-reported model: ${live.worker.model_label} · not independently verified` : 'Model connection: not reported');
    set('queue', `${live.queued} queued instructions · ${live.budget.claimed_today} / ${live.budget.effective_daily_jobs} task starts today`);
    const local = panel.querySelector('[data-live="local-work"]');
    if (local) local.replaceChildren(...(live.local_work ? [element('a', live.local_work.status === 'staged' ? 'Review local draft' : 'Open local brief', `/local-work?packet_id=${encodeURIComponent(live.local_work.id)}`), element('p', 'Activity in your own tool is unknown')] : []));
    const assignment = panel.querySelector('[data-live="assignment"]');
    const task = live.task;
    set('elapsed', task?.elapsed_seconds == null ? '' : `${task.elapsed_seconds}s since assignment · elapsed time is not a completion estimate`);
    const nodes = [];
    if (task) {
      nodes.push(element('a', task.question, `/ideas/${encodeURIComponent(task.idea_id)}?view=investigations`));
      nodes.push(element('p', `Last reported stage: ${task.stage_label} · ${task.role}`));
      if (task.excerpt) {
        nodes.push(element('p', 'Draft response excerpt · unreviewed'));
        nodes.push(element('blockquote', task.excerpt));
      }
    }
    const signature = JSON.stringify(task ? {...task, elapsed_seconds: null} : null);
    if (assignment.dataset.signature !== signature) {assignment.replaceChildren(...nodes); assignment.dataset.signature = signature;}
    const recent = panel.querySelector('[data-live="recent"]');
    const entries = live.recent.filter(item => !task || item.task_id !== task.id).slice(0, 2);
    const latest = JSON.stringify(entries);
    if (recent.dataset.signature !== latest) {
      const output = [];
      if (!entries.length) output.push(element('p', 'No recent attempts recorded.'));
      for (const entry of entries) {
        output.push(element('p', `Latest attempt: ${entry.stage_label} · ${when(entry.updated)}`));
        output.push(element('a', entry.question, `/ideas/${encodeURIComponent(entry.idea_id)}?view=investigations`));
        if (entry.excerpt) output.push(element('blockquote', entry.excerpt));
        if (entry.feedback) output.push(element('p', `Human review: ${entry.feedback}`));
      }
      recent.replaceChildren(...output); recent.dataset.signature = latest;
    }
    const button = document.querySelector(`.dashboard-state[data-agent="${live.id}"]`);
    if (button) {
      button.hidden = live.handler_status === 'retired';
      button.dataset.action = live.handler_status === 'ready' ? 'pause' : 'resume';
      button.textContent = `${live.handler_status === 'ready' ? 'Pause' : 'Resume'} ${live.name}`;
    }
  }
  async function poll() {
    clearTimeout(timer);
    if (busy || stopped || document.hidden) return;
    busy = true;
    try {
      const response = await fetch('/api/me/agent-activity', {credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(8000)});
      if (!response.ok) throw new Error(response.status === 401 ? 'Your session expired. Sign in to resume activity updates.' : 'Activity refresh failed. Displayed information may be old.');
      const result = await response.json();
      const total = document.querySelector('#activity-totals');
      if (total) {
        const working = result.agents.filter(a => a.state === 'working').length;
        const waiting = result.agents.filter(a => a.state === 'waiting' || a.state === 'blocked').length;
        const local = result.agents.filter(a => a.state === 'local-prepared' || a.state === 'local-review').length;
        total.textContent = `${result.agents.length} agents · ${working} working · ${waiting} waiting · ${local} local briefs or drafts · ${result.agents.length-working-waiting-local} paused, stopped, or disconnected`;
      }
      if (result.agents.length) document.querySelectorAll('[data-shared-budget]').forEach(node => {
        const budget = result.agents[0].budget;
        node.textContent = `${budget.claimed_today} / ${budget.effective_daily_jobs} task starts today across your agents. ${budget.enabled ? 'Budget enabled.' : 'Budget paused.'}`;
      });
      panels.forEach(panel => {
        const live = result.agents.find(item => item.id === panel.dataset.activityAgent);
        if (live) render(panel, live);
      });
      notice.textContent = `Updated ${new Date().toLocaleTimeString()} · refreshes every five seconds. Model reports are not subscription verification.`;
    } catch (error) {
      const total = document.querySelector('#activity-totals');
      if (total) total.textContent = 'Live activity unavailable; last observations may be old.';
      panels.forEach(panel => {panel.dataset.state = 'stale'; panel.querySelector('[data-live="label"]').textContent = 'Activity unavailable';});
      notice.textContent = error.name === 'TimeoutError' ? 'Activity request timed out. Last observations may be old.' : error.message;
    } finally {busy = false; if (!stopped && !document.hidden) timer = setTimeout(poll, 5000);}
  }
  document.querySelectorAll('.dashboard-state').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {await api(`/api/me/agents/${button.dataset.agent}/state`, {action: button.dataset.action}); await poll();}
    catch (error) {notify(error, true);}
    finally {button.disabled = false;}
  }));
  document.addEventListener('visibilitychange', () => {if (document.hidden) clearTimeout(timer); else poll();});
  window.addEventListener('catalyst-state-changed', poll);
  window.addEventListener('focus', poll);
  window.addEventListener('pagehide', () => {stopped = true; clearTimeout(timer);});
  window.addEventListener('pageshow', () => {stopped = false; poll();});
  poll();
})();
