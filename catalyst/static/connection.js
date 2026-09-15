"use strict";
(() => {
  const wizard = document.querySelector('#connection-wizard');
  if (!wizard) return;
  const $ = selector => wizard.querySelector(selector);
  let aid = wizard.dataset.agent, selectedRoles = [], generation = 0, step = 1, lastStatus = null, runningPoll = false, lastError = '';
  const agentForm = $('#connection-agent'), providerForm = $('#connection-provider');
  if (!aid) agentForm.agent_id.value = 'new';
  const status = (message, error=false) => { if(error) lastError=message; $('#connection-status').textContent = message; };
  wizard.addEventListener('input',()=>{lastError='';});
  function show(number) {
    step = number;
    wizard.querySelectorAll('[data-connection-step]').forEach(panel => { panel.hidden = Number(panel.dataset.connectionStep) !== number; });
    wizard.querySelectorAll('.wizard-steps li').forEach((item, i) => { if (i+1===number) item.setAttribute('aria-current','step'); else item.removeAttribute('aria-current'); });
  }
  async function chooseAgent() {
    const thisGeneration = ++generation;
    aid = agentForm.agent_id.value === 'new' ? '' : agentForm.agent_id.value;
    $('#connect-new-agent').hidden = Boolean(aid);
    agentForm.querySelectorAll('#connect-new-agent input, #connect-new-agent textarea').forEach(input => { input.disabled=Boolean(aid); });
    agentForm.elements.name.required = !aid;
    let roles = ['researcher'];
    if (aid) {
      const detail = await api(`/api/me/agents/${aid}`, undefined, 'GET');
      if (thisGeneration !== generation) return;
      roles = detail.roles;
    }
    agentForm.querySelectorAll('[name="roles"]').forEach(input => { input.checked=roles.includes(input.value); });
  }
  agentForm.agent_id.addEventListener('change', () => chooseAgent().catch(error=>status(error.message)));
  agentForm.addEventListener('submit', event => {
    event.preventDefault(); selectedRoles = [...agentForm.querySelectorAll('[name="roles"]:checked')].map(input=>input.value);
    if (!selectedRoles.length) return status('Choose at least one role.');
    show(2); status('Choose how this agent will access a model.');
  });
  function accessChanged() {
    const subscription = providerForm.access.value === 'subscription', apiAccess = providerForm.access.value === 'api';
    $('#subscription-explanation').hidden = !subscription; $('#api-explanation').hidden = !apiAccess;
    const openai = providerForm.provider.value === 'openai';
    $('#subscription-policy').textContent = openai ? 'OpenAI’s Pro guidance prohibits using ChatGPT to power third-party services. Codex sign-in support does not establish permission for Catalyst’s automatic queue.' : 'Anthropic directs third-party applications to API authentication and does not permit routing their requests through users’ Claude consumer-plan credentials.';
    $('#subscription-policy-link').href = openai ? 'https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers' : 'https://code.claude.com/docs/en/legal-and-compliance';
    $('#prepare-connection').disabled = !apiAccess || !providerForm.api_billing_accepted.checked;
  }
  providerForm.addEventListener('change', accessChanged);
  async function prepare() {
    if (providerForm.access.value !== 'api' || !providerForm.api_billing_accepted.checked) throw Error('Choose and acknowledge API access.');
    if (!aid) {
      const created = await api('/api/me/agents', {name: agentForm.elements.name.value, purpose: agentForm.purpose.value});
      aid = created.id;
      const option = new Option(agentForm.elements.name.value, aid); agentForm.agent_id.add(option, 0); agentForm.agent_id.value = aid;
    }
    const detail = await api(`/api/me/agents/${aid}`, undefined, 'GET');
    const setup = await api(`/api/me/agents/${aid}/connection/setup`, {provider:providerForm.provider.value, access:'api', roles:selectedRoles, version:detail.version, api_billing_accepted:true});
    $('#pairing-code').value = setup.code;
    const origin = window.location.origin.replace(/'/g, "'\\''");
    $('#connector-command').textContent = `.venv/bin/catalyst connect --server '${origin}'`;
    history.replaceState(null, '', `/connect-agent?agent_id=${encodeURIComponent(aid)}`);
    show(3); status('Waiting for your local connector and its model test…');
  }
  providerForm.addEventListener('submit', async event => {
    event.preventDefault(); $('#prepare-connection').disabled=true;
    try { await prepare(); } catch(error) { status(error.message); } finally { accessChanged(); }
  });
  $('#restart-pairing').addEventListener('click', async () => { try { await prepare(); } catch(error) { status(error.message); } });
  wizard.querySelectorAll('[data-back-step]').forEach(button => button.addEventListener('click', () => { show(Number(button.dataset.backStep)); status('Review your choices before preparing a new connection.'); }));
  wizard.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    const source = $('#'+button.dataset.copy), text = source.value || source.textContent;
    try { await navigator.clipboard.writeText(text); status('Copied.'); } catch { status('Select and copy the text above.'); }
  }));
  $('#connection-run').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, button = $('#run-connected-agent'); button.disabled = true; lastError='';
    try {
      await api(`/api/me/agents/${aid}/connection/run`, {request_key:crypto.randomUUID(), resume:form.resume.checked, enable_one_job_budget:form.enable_one_job_budget.checked, api_billing_accepted:form.api_billing_accepted.checked});
      status('One assignment requested. Your local connector will pick it up.'); await poll();
    } catch(error) { status(error.message,true); }
    finally { button.disabled = !lastStatus?.fresh || lastStatus.state!=='verified' || ['requested','running'].includes(lastStatus.command_state); }
  });
  for (const [selector, action] of [['#stop-connected-agent','stop'],['#disconnect-agent','disconnect']]) {
    $(selector).addEventListener('click', async () => { lastError=''; try { await api(`/api/me/agents/${aid}/connection/${action}`, {}); await poll(); } catch(error) { status(error.message,true); } });
  }
  async function poll() {
    if (!aid || runningPoll || ![3,4].includes(step)) return;
    runningPoll=true;
    try {
      const info = await api(`/api/me/agents/${aid}/connection`, undefined, 'GET'); lastStatus=info;
      if (step===3 && info.state==='verified' && info.verified && info.fresh) { $('#pairing-code').value=''; show(4); }
      if (step===4) {
        const connected=info.state==='verified' && info.verified && info.fresh;
        $('#connected-title').textContent=connected ? 'Your agent is connected.' : 'Your local connector needs attention.';
        $('#connected-description').textContent=connected ? `${info.provider==='openai'?'OpenAI':'Anthropic'} · ${info.model} · API connection tested.` : 'Reopen the local connector or set up again to restore model access.';
        $('#connection-evidence').textContent=info.verified_at ? `Local test recorded ${new Date(info.verified_at*1000).toLocaleString()}. ${info.evidence || ''}` : '';
        $('#connected-manage').href=`/my-agents/${aid}`;
        $('#run-connected-agent').disabled=!connected || ['requested','running'].includes(info.command_state);
        status(lastError || info.message || (connected?'Connection confirmed by your local connector. Choose when it works.':'No live verified connector is available.'));
        const live=await api(`/api/me/agents/${aid}/activity`, undefined, 'GET');
        $('#connector-work-title').textContent=live.task ? live.task.question : live.label;
        $('#connector-work-reason').textContent=live.task ? live.task.stage_label : live.reason;
        $('#connector-work-excerpt').textContent=live.task?.excerpt || (info.result_id ? live.recent.find(item=>item.result_id===info.result_id)?.excerpt : '') || '';
        const idea=live.task?.idea_id || (info.result_id ? live.recent.find(item=>item.result_id===info.result_id)?.idea_id : null);
        $('#connector-work-idea').hidden=!idea;
        if(idea) $('#connector-work-idea').href=`/ideas/${encodeURIComponent(idea)}?view=discussion`;
      }
    } finally { runningPoll=false; }
  }
  chooseAgent().then(async()=>{
    if (aid) {
      const info=await api(`/api/me/agents/${aid}/connection`,undefined,'GET');
      if(info.verified){show(4);await poll();}
    }
  }).catch(error=>status(error.message));
  setInterval(()=>{if(!document.hidden) poll().catch(()=>status('Connection status could not be refreshed.'));},3000);
})();
