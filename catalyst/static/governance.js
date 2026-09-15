"use strict";
bind('.human-role', async (form, data) => {
  await api(`/api/owner/humans/${form.dataset.human}/role`, {...Object.fromEntries(data), version: Number(form.dataset.version)}, 'PUT'); refresh();
});
bind('#intake-review', async (form, data) => {
  const path = form.dataset.channel === 'human' ? 'agenda' : 'agent-questions';
  await api(`/api/${path}/${form.dataset.question}/review`, {...Object.fromEntries(data), expected_event: form.dataset.event}); refresh();
});
bind('#intake-promotion', async (form, data) => {
  await api(`/api/intake/${form.dataset.channel}/${form.dataset.question}/promote`, {promoted: data.get('promoted') === 'true', reason: data.get('reason')}); refresh();
});
bind('#intake-develop', async (form, data) => {
  const path = form.dataset.channel === 'human' ? 'agenda' : 'agent-questions';
  const result = await api(`/api/${path}/${form.dataset.question}/develop`, Object.fromEntries(data));
  window.location.assign(`/ideas/${result.idea_id}?view=investigations`);
});
bind('#agent-question-answer', async (form, data) => {
  await api(`/api/agent-questions/${form.dataset.question}/answer`, Object.fromEntries(data)); refresh();
});
