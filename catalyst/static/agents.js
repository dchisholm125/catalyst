"use strict";
bind("#register-agent", async (form, data) => {
  const result = await api("/api/me/agents", {name: data.get("name"), purpose: data.get("purpose")});
  window.location.assign(`/my-agents/${result.id}`);
});
(() => {
  const manager = document.querySelector("#agent-manager");
  if (!manager) return;
  const base = `/api/me/agents/${manager.dataset.agent}`;
  const action = (selector, handler) => document.querySelectorAll(selector).forEach(button => button.addEventListener("click", async () => {
    button.disabled = true;
    try { await handler(button); } catch (error) { notify(error.message, true); }
    finally { button.disabled = false; }
  }));
  action(".agent-state", async button => { await api(`${base}/state`, {action: button.dataset.action}); refresh(); });
  action(".queue-action", async button => { await api(`${base}/queue/${button.dataset.entry}`, {action: button.dataset.action}); refresh(); });
  bind("#agent-settings", async (form, data) => {
    if (!data.getAll("roles").length) throw new Error("Choose at least one permitted role.");
    await api(base, {purpose: data.get("purpose"), mode: data.get("mode"), roles: data.getAll("roles"), version: Number(form.dataset.version), allow_questions: data.has('allow_questions')}, "PUT");
    refresh();
  });
  action("#rotate-agent-token", async button => {
    const result = await api(`${base}/credential`, {});
    document.querySelector("#agent-token").value = result.token;
    document.querySelector("#agent-token-result").hidden = false;
    document.querySelector("#agent-token").focus();
    button.textContent = "Rotate connection token";
  });
  const hideToken = () => {
    const field = document.querySelector("#agent-token");
    if (field) { field.value = ""; document.querySelector("#agent-token-result").hidden = true; }
  };
  document.querySelector("#hide-agent-token")?.addEventListener("click", hideToken);
  window.addEventListener("pagehide", hideToken);
  const dialog = document.querySelector("#retire-dialog");
  document.querySelector("#retire-agent")?.addEventListener("click", () => dialog.showModal());
  document.querySelector("#cancel-retire")?.addEventListener("click", () => dialog.close());

  const form = document.querySelector("#enqueue-agent-work");
  if (!form) return;
  const search = document.querySelector("#idea-search"), choice = document.querySelector("#idea-choice");
  const tasks = document.querySelector("#task-choice"), target = document.querySelector("#work-target");
  const role = document.querySelector("#queue-role");
  const status = document.querySelector("#search-status");
  let searchSequence = 0, taskSequence = 0, timer, requestKey = crypto.randomUUID();
  const read = async params => {
    const response = await fetch(`/api/me/agent-work-options?${new URLSearchParams(params)}`, {credentials: "same-origin"});
    if (!response.ok) throw new Error("Could not load work choices. Check your sign-in and try again.");
    return response.json();
  };
  const clearSelection = () => {
    taskSequence++;
    tasks.replaceChildren(new Option("Next eligible investigation on this idea", ""));
    document.querySelector("#investigation-choices").hidden = true;
    role.disabled = false;
  };
  const lookup = async () => {
    const seq = ++searchSequence;
    try {
      const data = await read({q: search.value});
      if (seq !== searchSequence) return;
      choice.replaceChildren(...data.ideas.map(idea => new Option(`${idea.title} · ${idea.kind} · ${idea.id.slice(0,6)}`, idea.id)));
      choice.selectedIndex = -1;
      status.textContent = data.ideas.length ? `${data.ideas.length} matching Living Ideas. Choose one below.${data.ideas.length === data.limit ? " Refine your search for more specific results." : ""}` : "No matching Living Ideas. Try another title.";
    } catch (error) { if (seq === searchSequence) status.textContent = error.message; }
  };
  search.addEventListener("input", () => {
    clearTimeout(timer); searchSequence++; clearSelection(); choice.replaceChildren();
    status.textContent = "Searching…"; timer = setTimeout(lookup, 200);
  });
  choice.addEventListener("change", async () => {
    clearSelection();
    if (!choice.value) return;
    const seq = ++taskSequence, idea = choice.value;
    try {
      const data = await read({idea_id: idea});
      if (seq !== taskSequence || choice.value !== idea) return;
      data.tasks.forEach(task => { const option = new Option(`${task.role}: ${task.question} (${task.status})`, task.id); option.dataset.role = task.role; tasks.add(option); });
      document.querySelector("#idea-investigations").href = `/ideas/${idea}?view=investigations`;
      document.querySelector("#investigation-choices").hidden = false;
    } catch (error) { notify(error.message, true); }
  });
  target.addEventListener("change", () => {
    const isIdea = target.value === "idea";
    document.querySelector("#idea-work-fields").hidden = !isIdea;
    document.querySelector("#topic-work-fields").hidden = isIdea;
    choice.required = isIdea;
    role.disabled = isIdea && Boolean(tasks.value);
  });
  tasks.addEventListener("change", () => {
    const selected = tasks.selectedOptions[0];
    role.disabled = Boolean(tasks.value);
    if (selected?.dataset.role) role.value = selected.dataset.role;
  });
  form.addEventListener("input", () => { requestKey = crypto.randomUUID(); });
  form.addEventListener("change", () => { requestKey = crypto.randomUUID(); });
  bind("#enqueue-agent-work", async () => {
    const isIdea = target.value === "idea", isTask = isIdea && Boolean(tasks.value);
    const id = isIdea ? (isTask ? tasks.value : choice.value) : document.querySelector("#topic-choice").value;
    if (!id) throw new Error("Choose a Living Idea from the matching results first.");
    await api(`${base}/queue`, {target_kind: isTask ? "task" : target.value, target_id: id,
      role: isTask ? tasks.selectedOptions[0].dataset.role : (role.value || null), request_key: requestKey});
    refresh();
  });
  lookup();
})();
