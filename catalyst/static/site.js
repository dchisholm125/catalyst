"use strict";
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const statusBox = document.querySelector("#status");
function notify(message, error = false) {
  const recovery = typeof message === 'object' ? message.recovery : [];
  statusBox.textContent = typeof message === 'object' ? message.message : message;
  for (const item of recovery || []) {
    const link = recoveryLink(item);
    if (link) statusBox.append(document.createTextNode(' '), link);
  }
  statusBox.className = error ? "visible error" : "visible";
  statusBox.focus();
}
function recoveryLink(item) {
  if (typeof item.href !== 'string' || !item.href.startsWith('/') || item.href.startsWith('//')) return null;
  const url = new URL(item.href, window.location.origin);
  if (url.origin !== window.location.origin) return null;
  const link = document.createElement('a'); link.href = url.href; link.textContent = item.label;
  return link;
}
const setupChannel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('catalyst-setup') : null;
setupChannel?.addEventListener('message', () => window.dispatchEvent(new Event('catalyst-state-changed')));
async function api(path, data, method = "POST") {
  const response = await fetch(path, {method, credentials: "same-origin", headers: {
    "Content-Type": "application/json", "X-CSRF-Token": csrf
  }, body: JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) {
    const detail = typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail);
    const error = new Error(detail || `Request failed (${response.status})`);
    error.recovery = value.recovery || (response.status === 401 ? [{label:'Sign in again',href:'/login'}] : []);
    throw error;
  }
  if (method !== 'GET') {
    window.dispatchEvent(new Event('catalyst-state-changed'));
    setupChannel?.postMessage('changed');
  }
  return value;
}
function bind(selector, handler) {
  document.querySelectorAll(selector).forEach(form => {
    form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    if (button) button.disabled = true;
    try { await handler(form, new FormData(form)); }
    catch (error) { notify(error, true); }
    finally { if (button) button.disabled = false; }
    });
    const readyButton = form.querySelector('[data-js-submit]');
    if (readyButton) readyButton.disabled = false;
  });
}
const refresh = () => window.location.reload();
bind("#new-idea", async (form, data) => {
  const result = await api("/api/ideas", {title: data.get("title"), kind: data.get("kind"),
    origin: data.get("origin"), admission_reason: data.get('admission_reason'), origin_kind: data.get("origin_kind") || "unspecified", synthesis: {summary: data.get("summary"),
    principles: data.get("principles").split("\n").map(s => s.trim()).filter(Boolean)}});
  window.location.assign(`/ideas/${result.id}`);
});
bind("#contribution-form", async (form, data) => {
  await api(`/api/ideas/${form.dataset.idea}/contributions`, {
    kind: data.get("kind"), body: data.get("body"), parent_id: data.get("parent_id") || null,
    provenance: data.get("provenance")}); refresh();
});
bind("#reaction-form", async (form, data) => {
  await api(`/api/ideas/${form.dataset.idea}/reaction`, {revision_id: form.dataset.revision,
    worth: Number(data.get("worth")), stance: data.get("stance"), explore: data.has("explore")}, "PUT"); refresh();
});
bind("#draft-form", async (form, data) => {
  const result = await api(`/api/ideas/${form.dataset.idea}/drafts`, {base_id: form.dataset.base,
    reason: data.get("reason"), synthesis: JSON.parse(data.get("synthesis"))});
  window.location.assign(`/revisions/${result.id}`);
});
bind("#review-form", async (form, data) => {
  await api(`/api/revisions/${form.dataset.revision}/review`, {decision: data.get("decision"), reason: data.get("reason")});
  window.location.assign(`/ideas/${form.dataset.idea}`);
});
bind(".recognize-form", async (form, data) => {
  await api(`/api/contributions/${form.dataset.reply}/recognize`, {reason: data.get("reason")}); refresh();
});
bind("#task-form", async (form, data) => {
  await api(`/api/ideas/${form.dataset.idea}/tasks`, {question: data.get("question"), role: data.get("role"), tier: Number(data.get("tier")), success_criteria: data.get("success_criteria") || ""}); refresh();
});
bind("#feedback-form", async (form, data) => {
  await api("/api/feedback", {category: data.get("category"), body: data.get("body")});
  form.reset(); notify("Feedback saved for the human reviewers.");
});
document.querySelectorAll(".cancel-task").forEach(button => button.addEventListener("click", async () => {
  try { await api(`/api/tasks/${button.dataset.task}/cancel`, {}); refresh(); }
  catch (error) { notify(error, true); }
}));
document.querySelector("#logout")?.addEventListener("click", async () => {
  try { await api("/api/logout", {}); window.location.assign("/"); }
  catch (error) { notify(error, true); }
});
document.querySelector("#share")?.addEventListener("input", event => {
  document.querySelector("#share-output").textContent = `${event.target.value}%`;
});
