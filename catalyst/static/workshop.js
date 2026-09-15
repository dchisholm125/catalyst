"use strict";
// Real links work without JavaScript. Enhancement preserves forms and URL history.
const ideaNav = document.querySelector("[data-idea-tabs]");
if (ideaNav) {
  const tabs = [...ideaNav.querySelectorAll("[data-idea-tab]")];
  const panels = [...document.querySelectorAll("[data-idea-panel]")];
  ideaNav.setAttribute("role", "tablist");
  tabs.forEach(tab => {
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", tab.dataset.ideaTab);
  });
  panels.forEach(panel => {panel.setAttribute("role", "tabpanel"); panel.tabIndex = 0;});
  function showPanel(name, push = false) {
    if (!tabs.some(tab => tab.dataset.ideaTab === name)) name = "synthesis";
    tabs.forEach(tab => {
      const selected = tab.dataset.ideaTab === name;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      tab.removeAttribute("aria-current");
    });
    panels.forEach(panel => {
      const selected = panel.dataset.ideaPanel === name;
      panel.hidden = !selected;
      panel.classList.toggle("panel-arriving", selected);
    });
    if (push) {
      const url = new URL(window.location.href);
      url.searchParams.set("view", name); url.hash = "";
      history.pushState({}, "", url);
    }
  }
  function fromLocation() {
    const url = new URL(window.location.href);
    const legacy = url.hash.slice(1);
    const name = legacy.startsWith("contribution-") ? "discussion" :
      tabs.some(t => t.dataset.ideaTab === legacy) ? legacy : url.searchParams.get("view");
    showPanel(name || "synthesis");
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); showPanel(tab.dataset.ideaTab, true);
    });
    tab.addEventListener("keydown", event => {
      let next;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else if (event.key === " ") {event.preventDefault(); tab.click(); return;}
      else return;
      event.preventDefault(); tabs[next].focus(); showPanel(tabs[next].dataset.ideaTab, true);
    });
  });
  window.addEventListener("popstate", fromLocation);
  window.addEventListener("hashchange", fromLocation);
  fromLocation();
}
bind("#signal-form", async (form, data) => {
  form.dataset.requestKey ||= crypto.randomUUID();
  const result = await api("/api/agenda", {...Object.fromEntries(data), request_key: form.dataset.requestKey});
  window.location.assign(`/agenda/${result.id}?submitted=1`);
});
bind('#question-review', async (form, data) => {
  await api(`/api/agenda/${form.dataset.signal}/review`, {...Object.fromEntries(data), expected_event: form.dataset.event}); refresh();
});
bind('#question-clarification', async (form, data) => {
  await api(`/api/agenda/${form.dataset.signal}/clarify`, Object.fromEntries(data)); refresh();
});
bind("#develop-signal", async (form, data) => {
  const result = await api(`/api/agenda/${form.dataset.signal}/develop`, Object.fromEntries(data));
  window.location.assign(`/ideas/${result.idea_id}?view=investigations`);
});
bind(".task-review-form", async (form, data) => {
  await api(`/api/tasks/${form.dataset.task}/review`, Object.fromEntries(data)); refresh();
});
document.querySelector("#signal-support")?.addEventListener("click", async event => {
  const button = event.currentTarget; button.disabled = true;
  try {
    const channel = button.dataset.channel === 'agent' ? 'agent-questions' : 'agenda';
    await api(`/api/${channel}/${button.dataset.signal}/support`, {supported: button.dataset.supported !== "true"}, "PUT");
    refresh();
  } catch (error) {notify(error.message, true); button.disabled = false;}
});
