"use strict";
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const statusBox = document.querySelector("#status");
function notify(message, error = false) {
  statusBox.textContent = message;
  statusBox.className = error ? "visible error" : "visible";
  statusBox.focus();
}
async function api(path, data, method = "POST") {
  const response = await fetch(path, {method, credentials: "same-origin", headers: {
    "Content-Type": "application/json", "X-CSRF-Token": csrf
  }, body: JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) {
    const detail = typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail);
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return value;
}
function bind(selector, handler) {
  document.querySelectorAll(selector).forEach(form => form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    if (button) button.disabled = true;
    try { await handler(form, new FormData(form)); }
    catch (error) { notify(error.message, true); }
    finally { if (button) button.disabled = false; }
  }));
}
const refresh = () => window.location.reload();
bind("#new-idea", async (form, data) => {
  const result = await api("/api/ideas", {title: data.get("title"), kind: data.get("kind"),
    origin: data.get("origin"), synthesis: {summary: data.get("summary"),
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
  await api(`/api/ideas/${form.dataset.idea}/tasks`, {question: data.get("question")}); refresh();
});
bind("#budget-form", async (form, data) => {
  await api("/api/me/budget", {share: Number(data.get("share")), daily_jobs: Number(data.get("daily_jobs")), enabled: data.has("enabled")}, "PUT"); refresh();
});
bind("#feedback-form", async (form, data) => {
  await api("/api/feedback", {category: data.get("category"), body: data.get("body")});
  form.reset(); notify("Feedback saved for the human reviewers.");
});
document.querySelectorAll(".cancel-task").forEach(button => button.addEventListener("click", async () => {
  try { await api(`/api/tasks/${button.dataset.task}/cancel`, {}); refresh(); }
  catch (error) { notify(error.message, true); }
}));
document.querySelector("#logout")?.addEventListener("click", async () => {
  try { await api("/api/logout", {}); window.location.assign("/"); }
  catch (error) { notify(error.message, true); }
});
document.querySelector("#share")?.addEventListener("input", event => {
  document.querySelector("#share-output").textContent = `${event.target.value}%`;
});
