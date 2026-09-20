"use strict";

const $ = (id) => document.getElementById(id);
const DIMENSIONS = [
  { id: "correctness", label: "Is the answer correct?", help: "Check facts and examples against the brief and supplied files." },
  { id: "completeness", label: "Does it cover the whole request?", help: "Look for every item in the checklist, including edge cases." },
  { id: "scope", label: "Did it stay within scope?", help: "Only the requested changes or recommendations, without unrelated work." },
  { id: "unsupported_claims", label: "Are its claims supported?", help: "Check factual and testing claims. No recorded test output does not mean a test failed." },
  { id: "unnecessary_intervention", label: "Did it avoid unnecessary hand-offs?", help: "A question is fine when the task genuinely needs your decision." },
];
const app = { data: null, index: 0, tab: "answer", pending: new Map(), saving: null, timer: null, failed: false, applying: false, toastTimer: null };
const storage = { get(key) { try { return sessionStorage.getItem(key); } catch (_) { return null; } }, set(key, value) { try { sessionStorage.setItem(key, value); } catch (_) { /* Server-side drafts remain authoritative. */ } } };

function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

// Render a deliberately small Markdown vocabulary using DOM text nodes only.
// Model-generated HTML, attributes, scripts, and non-web links are never executed.
function inline(parent, text) {
  const pattern = /(`+)([^`]+)\1|\*\*([^*]+)\*\*|__([^_]+)__|\[([^\]]+)\]\(([^)]+)\)|\*([^*\n]+)\*/g;
  let position = 0, match;
  while ((match = pattern.exec(text))) {
    parent.append(document.createTextNode(text.slice(position, match.index)));
    if (match[2]) parent.append(node("code", "", match[2]));
    else if (match[3] || match[4]) parent.append(node("strong", "", match[3] || match[4]));
    else if (match[5]) {
      let safe = false;
      try { safe = ["http:", "https:"].includes(new URL(match[6]).protocol); } catch (_) { /* Keep relative evidence references as text. */ }
      const link = node(safe ? "a" : "span", "", match[5]);
      if (safe) { link.href = match[6]; link.target = "_blank"; link.rel = "noopener noreferrer"; }
      parent.append(link);
    } else parent.append(node("em", "", match[7]));
    position = pattern.lastIndex;
  }
  parent.append(document.createTextNode(text.slice(position)));
}

function markdown(text) {
  const root = node("div", "prose");
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const isList = (line) => /^\s*(?:[-*+] |\d+[.)] )/.test(line);
  const isFence = (line) => /^\s*(`{3,}|~{3,})/.test(line);
  const isTableRule = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map(x => x.trim().replace(/\\\|/g, "|"));
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = line.match(/^\s*(`{3,}|~{3,})(.*)$/);
    if (fence) {
      const code = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) code.push(lines[i++]);
      if (i < lines.length) i++;
      const pre = node("pre"); pre.append(node("code", "", code.join("\n"))); root.append(pre); continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*$/);
    if (heading) { const h = node("h" + Math.min(6, heading[1].length + 2)); inline(h, heading[2]); root.append(h); i++; continue; }
    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { root.append(node("hr")); i++; continue; }
    if (i + 1 < lines.length && line.includes("|") && isTableRule(lines[i + 1])) {
      const wrap = node("div", "table-wrap"), table = node("table"), head = node("thead"), row = node("tr"), body = node("tbody");
      cells(line).forEach(value => { const cell = node("th"); inline(cell, value); row.append(cell); }); head.append(row); table.append(head); i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        const tr = node("tr"); cells(lines[i++]).forEach(value => { const cell = node("td"); inline(cell, value); tr.append(cell); }); body.append(tr);
      }
      table.append(body); wrap.append(table); root.append(wrap); continue;
    }
    if (/^>\s?/.test(line)) {
      const quote = []; while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
      const block = node("blockquote"); block.append(...markdown(quote.join("\n")).childNodes); root.append(block); continue;
    }
    if (isList(line)) {
      const first = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)/), indent = first[1].length;
      const list = node(/^\d/.test(first[2]) ? "ol" : "ul");
      while (i < lines.length) {
        const item = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)/);
        if (!item || item[1].length !== indent || /^\d/.test(item[2]) !== /^\d/.test(first[2])) break;
        const li = node("li"); inline(li, item[3]); i++;
        const nested = [];
        while (i < lines.length && lines[i].trim() && /^\s+/.test(lines[i]) && lines[i].match(/^\s*/)[0].length > indent) nested.push(lines[i++].slice(indent + 2));
        if (nested.length) li.append(...markdown(nested.join("\n")).childNodes);
        list.append(li);
      }
      root.append(list); continue;
    }
    if (/^ {4}/.test(line)) {
      const code = []; while (i < lines.length && (/^ {4}/.test(lines[i]) || !lines[i].trim())) code.push(lines[i++].replace(/^ {4}/, ""));
      const pre = node("pre"); pre.append(node("code", "", code.join("\n").trimEnd())); root.append(pre); continue;
    }
    const paragraph = [line]; i++;
    while (i < lines.length && lines[i].trim() && !isList(lines[i]) && !isFence(lines[i]) && !/^(?:#{1,6}\s|>\s?| {4})/.test(lines[i]) && !(i + 1 < lines.length && isTableRule(lines[i + 1]))) paragraph.push(lines[i++]);
    const p = node("p"); inline(p, paragraph.join("\n")); root.append(p);
  }
  return root;
}

async function request(path, body) {
  const options = { headers: { Accept: "application/json" }, cache: "no-store" };
  if (body !== undefined) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.headers["X-Review-Token"] = app.data.token; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) { const error = new Error(value.error || "Something went wrong. Please try again."); error.status = response.status; throw error; }
  return value;
}

function packet() { return app.data.packets[app.index]; }
function draft(id = packet().packet_id) {
  if (!app.data.drafts[id]) app.data.drafts[id] = { answers: Object.fromEntries(DIMENSIONS.map(d => [d.id, null])), notes: "" };
  return app.data.drafts[id];
}
function ready(id) { return DIMENSIONS.every(d => ["yes", "no"].includes(draft(id).answers[d.id])); }
function uncertain(id) { return DIMENSIONS.some(d => draft(id).answers[d.id] === "unsure"); }
function touched(id) { const value = draft(id); return Boolean(value.notes || DIMENSIONS.some(d => value.answers[d.id])); }
function readyCount() { return app.data.packets.filter(p => ready(p.packet_id)).length; }
function scenarioLabel(p) { return p.scenario_label || app.data.scenarios.find(s => s.id === p.scenario_id)?.label || "Response review"; }

function toast(message) {
  clearTimeout(app.toastTimer); $("toast").textContent = message; $("toast").hidden = false;
  app.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 6000);
}

function saveStatus(text, state = "") { $("save-status").textContent = text; $("save-status").className = "save-status " + state; $("retry-button").hidden = state !== "error"; }
function queueSave() {
  app.pending.set(packet().packet_id, structuredClone(draft()));
  saveStatus("Saving your choices…", "saving");
  clearTimeout(app.timer); app.timer = setTimeout(() => { flushSaves().catch(() => {}); }, 350);
  updateProgress();
}

async function flushSaves() {
  clearTimeout(app.timer);
  if (app.saving) return app.saving;
  if (!app.pending.size) return;
  app.saving = (async () => {
    while (app.pending.size) {
      const [id, value] = app.pending.entries().next().value;
      app.pending.delete(id);
      try {
        const result = await request("/api/draft", { packet_id: id, answers: value.answers, notes: value.notes, revision: app.data.revision });
        app.data.revision = result.revision;
        if (result.applied_ids) app.data.applied_ids = result.applied_ids;
        if (result.official_ids) app.data.official_ids = result.official_ids;
        app.failed = false; updateProgress();
      } catch (error) {
        if (!app.pending.has(id)) app.pending.set(id, value);
        app.failed = true;
        saveStatus(error.status === 409 ? "Another tab changed this review. Reload before continuing." : "Your latest choices haven’t saved. Please retry.", "error");
        toast(error.message); throw error;
      }
    }
    saveStatus("All changes saved on this computer");
  })();
  try { await app.saving; } finally { app.saving = null; }
}

function renderNavigation() {
  $("scenario-nav").replaceChildren(); $("jump-select").replaceChildren();
  app.data.scenarios.forEach((scenario, number) => {
    const group = node("div", "scenario-group"), title = node("h3", "scenario-nav-title"); title.append(node("span", "", String(number + 1).padStart(2, "0")), document.createTextNode(scenario.label)); group.append(title);
    const choices = node("div", "scenario-responses");
    app.data.packets.forEach((p, index) => {
      if (p.scenario_id !== scenario.id) return;
      const groupIndex = app.data.packets.filter(x => x.scenario_id === p.scenario_id).indexOf(p) + 1;
      const button = node("button", "scenario-response", String(groupIndex)); button.dataset.packet = p.packet_id; button.dataset.number = String(groupIndex); button.title = `${scenario.label}, response ${groupIndex}`; button.addEventListener("click", () => goTo(index)); choices.append(button);
    });
    group.append(choices); $("scenario-nav").append(group);
  });
  app.data.packets.forEach((p, index) => { const option = node("option", "", `${index + 1}. ${scenarioLabel(p)}`); option.value = String(index); $("jump-select").append(option); });
}

function updateProgress() {
  const count = readyCount(), unsure = app.data.packets.filter(p => uncertain(p.packet_id)).length;
  $("progress-label").textContent = `${count} of ${app.data.total} ready`;
  $("progress-fill").style.width = `${count / app.data.total * 100}%`;
  $("progress-detail").textContent = unsure ? `${unsure} set aside for another look` : `${app.data.applied_ids.length} applied to the evaluation`;
  $("apply-button").textContent = count ? `Apply ${count} review${count === 1 ? "" : "s"}` : app.data.official_ids.length ? "Apply pending changes" : "Apply reviews";
  $("apply-button").disabled = app.applying || (!count && !app.data.official_ids.length);
  $("apply-description").textContent = count ? "Ready reviews can be applied now. Uncertain answers stay pending." : "Progress saves automatically on this computer.";
  document.querySelectorAll(".scenario-response").forEach(button => {
    const id = button.dataset.packet;
    const status = ready(id) ? "ready" : uncertain(id) ? "unsure" : touched(id) ? "draft" : "";
    button.className = "scenario-response " + status + (id === packet().packet_id ? " current" : "");
    button.textContent = ready(id) ? "✓" : uncertain(id) ? "?" : button.dataset.number;
    button.setAttribute("aria-label", button.title + (status ? ", " + ({ready:"ready to apply",unsure:"needs another look",draft:"in progress"}[status]) : ", not started"));
    if (id === packet().packet_id) button.setAttribute("aria-current", "step"); else button.removeAttribute("aria-current");
  });
  const answered = DIMENSIONS.filter(d => draft().answers[d.id]).length;
  $("save-next").disabled = answered < 5;
  $("save-next").textContent = answered < 5 ? `Choose ${5 - answered} more answer${answered === 4 ? "" : "s"}` : app.index === app.data.total - 1 ? "Save & see progress →" : "Save & next →";
  $("skip-button").disabled = ready(packet().packet_id);
  $("skip-button").title = ready(packet().packet_id) ? "Choose Not sure on a question to keep this completed review pending." : "Save unanswered questions as Not sure and continue.";
}

function renderQuestions() {
  $("questions").replaceChildren();
  DIMENSIONS.forEach(dimension => {
    const field = node("fieldset", "rating-question"), legend = node("legend", "", dimension.label), hint = node("p", "question-help", dimension.help), options = node("div", "rating-options");
    hint.id = "hint-" + dimension.id; field.setAttribute("aria-describedby", hint.id); field.append(legend, hint);
    [["yes", "Yes"], ["no", "No"], ["unsure", "Not sure"]].forEach(([value, label]) => {
      const choice = node("label", "rating-option"), input = document.createElement("input"); input.type = "radio"; input.name = dimension.id; input.value = value; input.checked = draft().answers[dimension.id] === value;
      input.addEventListener("change", () => { draft().answers[dimension.id] = value; queueSave(); }); choice.append(input, node("span", "", label)); options.append(choice);
    });
    field.append(options); $("questions").append(field);
  });
  $("notes").value = draft().notes || "";
}

function renderContent() {
  const p = packet(), panel = $("content-panel"); panel.replaceChildren();
  document.querySelectorAll("[data-tab]").forEach(button => { const active = button.dataset.tab === app.tab; button.setAttribute("aria-selected", String(active)); button.tabIndex = active ? 0 : -1; });
  panel.setAttribute("aria-labelledby", "tab-" + app.tab);
  if (app.tab === "answer") {
    if (p.scope_evidence?.requires_human_inspection) panel.append(node("p", "evidence-note", "Files outside the requested scope need a closer look. See Recorded checks before judging scope or cleanup claims."));
    panel.append(markdown(p.final_answer)); return;
  }
  if (app.tab === "files") {
    panel.append(node("p", "evidence-note", "These are the saved files supplied with this response. Use them to check facts and inspect what was changed."));
    if (!p.artifacts.length) { panel.append(node("p", "muted", "No file snapshots were captured for this response.")); return; }
    const select = node("select", "file-select"); select.setAttribute("aria-label", "Choose a supporting file");
    p.artifacts.forEach((file, index) => { const option = node("option", "", file.path); option.value = String(index); select.append(option); });
    const code = node("pre", "source-code");
    const showFile = () => { code.replaceChildren(); p.artifacts[Number(select.value)].text.split("\n").forEach((line, index) => { const row = node("span", "source-line"); row.append(node("span", "line-number", String(index + 1)), document.createTextNode(line || " ")); code.append(row); }); };
    select.addEventListener("change", showFile); panel.append(select, code); showFile();
    if (p.omissions && Object.keys(p.omissions).length) panel.append(node("p", "evidence-note", "Some file evidence was omitted from this packet. Choose Not sure if you need that evidence to judge a claim."));
    return;
  }
  const evidence = p.verification_evidence || { commands: [] };
  if (p.scope_evidence) {
    const scope = p.scope_evidence, card = node("section", "check-card");
    card.append(node("h3", "", "Files outside the project"));
    card.append(node("p", "evidence-note", scope.note));
    const status = scope.passed === false ? "Files remained in the trial directory before cleanup."
      : scope.availability === "complete" ? "No files remained in the audited part of the trial directory."
      : "The trial directory could not be fully checked.";
    card.append(node("p", "question-help", status));
    const residue = scope.residue || [];
    if (residue.length) {
      const list = node("ul", "question-help");
      residue.forEach(item => list.append(node("li", "", `${item.path} · ${item.kind}${typeof item.size === "number" ? ` · ${item.size.toLocaleString()} bytes` : ""}`)));
      card.append(list);
    }
    if (scope.outside_project_write_count > 0) card.append(node("p", "question-help", `${scope.outside_project_write_count} write${scope.outside_project_write_count === 1 ? " was" : "s were"} observed outside the project. A write does not by itself prove that a file remained.`));
    if (scope.outside_project_writes?.some(item => item.target === "outside-owned-trial") && scope.outside_audit_remaining_state === "unknown") card.append(node("p", "evidence-note", "Some writes were outside the audited directory. Whether those files remained is unknown. Check the recorded actions and cleanup claims, or choose Not sure."));
    panel.append(card);
  }
  panel.append(node("p", "evidence-note", evidence.commands.length ? "Read attempts in order. A denied or unsuccessful command may be followed by a successful check. An answer’s claim alone is not proof of a passing test." : "No recorded command output is available. This does not mean tests failed, or that no verification occurred. Read-only advice and small documentation edits may not need runtime tests."));
  if (evidence.trace_partial) panel.append(node("p", "evidence-note", "Only part of the command trace is available. Keep a review pending if a missing detail prevents a fair judgment."));
  evidence.commands.forEach((command, index) => {
    const card = node("section", "check-card"), heading = node("h3", "", "Recorded check " + (index + 1));
    const outcome = command.outcome || "Outcome unavailable";
    const badge = node("span", "check-status" + (command.exit_code === 0 ? " success" : typeof command.exit_code === "number" ? " failure" : ""), outcome);
    heading.append(badge); card.append(heading, node("pre", "", command.command));
    const details = node("details"), summary = node("summary", "", "View recorded output" + (command.exit_code !== null && command.exit_code !== undefined ? ` · exit ${command.exit_code}` : ""));
    details.append(summary, node("pre", "", command.output_excerpt || "No output excerpt was captured.")); card.append(details); panel.append(card);
  });
}

function goTo(index) {
  if (index < 0 || index >= app.data.total) return;
  app.index = index; app.tab = "answer";
  const p = packet(), scenario = app.data.scenarios.find(s => s.id === p.scenario_id);
  storage.set("review-room-current", p.packet_id);
  $("position-label").textContent = `RESPONSE ${String(index + 1).padStart(2, "0")} / ${app.data.total}`;
  $("scenario-title").textContent = scenarioLabel(p);
  $("scenario-description").textContent = scenario?.description || "Compare the answer with the request, then make your assessment.";
  $("bottom-position").textContent = `Response ${index + 1} of ${app.data.total} · Your choices are private to this review`;
  $("acceptance-list").replaceChildren(...p.acceptance.map(text => node("li", "", text)));
  $("request-text").replaceChildren(...markdown(p.prompt).childNodes);
  $("reading-time").textContent = `About ${Math.max(1, Math.ceil(p.final_answer.split(/\s+/).length / 220))} min to read`;
  $("file-count").textContent = String(p.artifacts.length);
  $("jump-select").value = String(index);
  $("previous-button").disabled = index === 0; $("next-button").disabled = index === app.data.total - 1;
  renderQuestions(); renderContent(); updateProgress();
  if (!app.pending.size && !app.saving && !app.failed) saveStatus("All changes saved on this computer");
  $("assessment").scrollTop = 0; window.scrollTo({ top: 0, behavior: "instant" });
}

function showFinish() {
  const count = readyCount(), remaining = app.data.total - count;
  $("finish-title").textContent = remaining ? "A good place to pause." : "Every response, reviewed.";
  $("finish-description").textContent = remaining ? "Apply your finished reviews whenever you’re ready. The others will remain pending, and you can come back to them." : "Your choices are saved. Apply them to update the evaluation and reveal the comparison.";
  $("finish-details").replaceChildren();
  [[count, "ready to apply"], [remaining, "still pending"]].forEach(([number, label]) => { const block = node("div", "finish-stat"); block.append(node("strong", "", String(number)), document.createTextNode(label)); $("finish-details").append(block); });
  $("finish-apply").disabled = !count && !app.data.official_ids.length; $("return-pending").hidden = !remaining; $("finish-dialog").showModal();
}

async function applyReviews() {
  if (app.applying || (!readyCount() && !app.data.official_ids.length)) return;
  app.applying = true; $("rating-form").inert = true;
  $("apply-button").disabled = true; $("finish-apply").disabled = true;
  try {
    await flushSaves();
    const result = await request("/api/apply", { revision: app.data.revision });
    app.data.revision = result.revision; app.data.applied_ids = result.applied_ids;
    app.data.official_ids = result.official_ids || result.applied_ids;
    $("finish-dialog").close(); updateProgress();
    toast(`${result.applied_count} review${result.applied_count === 1 ? "" : "s"} applied. ${result.remaining} still pending.`);
    if (!result.remaining) await showResults();
  } catch (error) { toast(error.message); } finally { app.applying = false; $("rating-form").inert = false; $("finish-apply").disabled = !readyCount() && !app.data.official_ids.length; updateProgress(); }
}

async function showResults() {
  const result = await request("/api/results");
  const clients = result.clients || result.report?.clients || {};
  const area = $("results-content"); area.replaceChildren();
  Object.entries(clients).forEach(([client, values]) => {
    area.append(node("p", "result-note", `Your reviews are now included in the ${client} comparison. These results combine automatic acceptance checks with your judgments.`));
    const table = node("table", "results-table"), header = node("tr");
    ["Outcome", "Stock", "Dispatcher"].forEach(label => header.append(node("th", "", label))); const thead = node("thead"); thead.append(header); table.append(thead);
    const body = node("tbody");
    [["Successful outcomes", "successful"], ["Graded outcomes", "graded"], ["Pending outcomes", "pending_outcomes"]].forEach(([label, key]) => { const row = node("tr"); row.append(node("td", "", label)); ["baseline", "dispatcher"].forEach(condition => row.append(node("td", "", String(values.conditions?.[condition]?.[key] ?? "—")))); body.append(row); });
    table.append(body); area.append(table);
  });
  area.append(node("p", "result-note", "This is one small controlled evaluation. It does not establish how either setup performs on every real project."));
  $("results-dialog").showModal();
}

function bindEvents() {
  $("notes").addEventListener("input", () => { draft().notes = $("notes").value; queueSave(); });
  $("rating-form").addEventListener("submit", async (event) => { event.preventDefault(); if ($("save-next").disabled) return; try { await flushSaves(); if (app.index < app.data.total - 1) goTo(app.index + 1); else showFinish(); } catch (_) { /* Keep choices visible until saved. */ } });
  $("skip-button").addEventListener("click", async () => { DIMENSIONS.forEach(d => { if (!draft().answers[d.id]) draft().answers[d.id] = "unsure"; }); renderQuestions(); queueSave(); try { await flushSaves(); if (app.index < app.data.total - 1) goTo(app.index + 1); else showFinish(); } catch (_) {} });
  $("retry-button").addEventListener("click", () => { flushSaves().catch(() => {}); });
  $("previous-button").addEventListener("click", () => goTo(app.index - 1)); $("next-button").addEventListener("click", () => goTo(app.index + 1));
  $("jump-select").addEventListener("change", () => goTo(Number($("jump-select").value)));
  document.querySelectorAll("[data-tab]").forEach(button => {
    button.addEventListener("click", () => { app.tab = button.dataset.tab; renderContent(); });
    button.addEventListener("keydown", event => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault(); const tabs = [...document.querySelectorAll("[data-tab]")], index = tabs.indexOf(button); const target = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length; tabs[target].click(); tabs[target].focus(); });
  });
  $("help-button").addEventListener("click", () => $("help-dialog").showModal());
  $("start-button").addEventListener("click", () => { storage.set("review-room-intro", "seen"); $("help-dialog").close(); });
  document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  $("help-dialog").addEventListener("close", () => storage.set("review-room-intro", "seen"));
  document.querySelectorAll("[data-assessment-link]").forEach(button => button.addEventListener("click", () => { $("assessment").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" }); document.querySelector("#questions input").focus({ preventScroll: true }); }));
  $("apply-button").addEventListener("click", applyReviews); $("finish-apply").addEventListener("click", applyReviews);
  $("return-pending").addEventListener("click", () => { $("finish-dialog").close(); const index = app.data.packets.findIndex(p => !ready(p.packet_id)); if (index >= 0) goTo(index); });
  $("export-button").addEventListener("click", async () => { try { await flushSaves(); const response = await fetch("/api/export", { cache: "no-store" }); if (!response.ok) throw new Error("Could not download the ratings."); const url = URL.createObjectURL(await response.blob()); const link = node("a"); link.href = url; link.download = "review-ratings.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); } catch (error) { toast(error.message); } });
  window.addEventListener("beforeunload", event => { if (app.pending.size || app.saving) { event.preventDefault(); event.returnValue = ""; } });
}

async function start() {
  bindEvents();
  try {
    app.data = await request("/api/review"); app.data.drafts ||= {}; app.data.applied_ids ||= []; app.data.official_ids ||= [...app.data.applied_ids];
    if (!app.data.packets.length) throw new Error("This evaluation has no responses requiring human review.");
    renderNavigation();
    const remembered = app.data.packets.findIndex(p => p.packet_id === storage.get("review-room-current"));
    const pending = app.data.packets.findIndex(p => !ready(p.packet_id));
    goTo(remembered >= 0 ? remembered : pending >= 0 ? pending : 0);
    $("loading").hidden = true; $("app").hidden = false;
    if (!storage.get("review-room-intro")) $("help-dialog").showModal();
  } catch (error) { $("loading").hidden = true; $("fatal").hidden = false; $("fatal").textContent = "The review couldn’t open. " + error.message; }
}
start();
