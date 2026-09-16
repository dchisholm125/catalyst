"use strict";
(() => {
  const root = document.querySelector('#local-work');
  if (!root) return;
  const pid = root.dataset.packet;
  const packetPage = id => `/local-work?packet_id=${encodeURIComponent(id)}`;
  let requestKey = crypto.randomUUID();
  bind('#prepare-local-work', async (form, data) => {
    const result = await api(`/api/me/agents/${encodeURIComponent(data.get('agent_id'))}/local-work`, {
      request_key: requestKey, resume: data.has('resume'), enable_one_job_budget: data.has('enable_one_job_budget')
    });
    window.location.assign(packetPage(result.id));
  });
  document.querySelector('#prepare-local-work select')?.addEventListener('change', () => { requestKey = crypto.randomUUID(); });
  bind('#upload-local-answer', async (form, data) => {
    const file = data.get('answer');
    if (file.size > 64000) throw Error('Use an answer JSON file smaller than 64 KiB.');
    let answer;
    try { answer = JSON.parse(await file.text()); } catch { throw Error('This file is not valid JSON. Ask your tool for the completed answer template.'); }
    await api(`/api/local-work/${pid}/answer`, answer); refresh();
  });
  bind('#approve-local-answer', async () => {
    await api(`/api/local-work/${pid}/submit`, {answer_hash: root.dataset.answerHash, reviewed: true}); refresh();
  });
  function click(id, action) {
    document.querySelector(id)?.addEventListener('click', async event => {
      const button = event.currentTarget; button.disabled = true;
      try { await action(); } catch(error) { notify(error, true); }
      finally { button.disabled = false; }
    });
  }
  click('#local-transfer-code', async () => {
    const result = await api(`/api/local-work/${pid}/transfer-code`, {});
    document.querySelector('#local-code').value = result.code;
    document.querySelector('#local-code-result').hidden = false;
    document.querySelector('#local-transfer-code').textContent = 'Replace transfer code';
  });
  click('#cancel-local-work', async () => { await api(`/api/local-work/${pid}/cancel`, {}); refresh(); });
  root.querySelectorAll('[data-local-copy]').forEach(button => button.addEventListener('click', async () => {
    const source = document.getElementById(button.dataset.localCopy);
    try { await navigator.clipboard.writeText(source.value || source.textContent); notify('Copied.'); }
    catch { notify('Select and copy the text above.'); }
  }));
  if (document.querySelector('#local-pull-command')) {
    const origin = window.location.origin.replace(/'/g, "'\\''"), folder = `../catalyst-work/${pid}`;
    document.querySelector('#local-pull-command').textContent = `catalyst work pull --server '${origin}' --out '${folder}'`;
    document.querySelector('#local-push-command').textContent = `catalyst work push '${folder}/answer.json' --server '${origin}'`;
  }
})();
