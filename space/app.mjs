const byId = (id) => document.getElementById(id);
const jobs = new Map();
let manifest;
let comparison;
let comparisonBytes;
let localReport;
let localBytes;
let comparisonGeneration = 0;
let localGeneration = 0;

function element(tag, content, className) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (Array.isArray(content)) result.append(...content);
  else if (content !== undefined) result.textContent = String(content);
  return result;
}
function showError(id, error) {
  byId(id).textContent = error instanceof Error ? error.message : String(error);
  byId(id).hidden = false;
}
function cancelled() {
  const error = new Error("Reading cancelled.");
  error.name = "AbortError";
  return error;
}
function cancelJob(operation) {
  jobs.get(operation)?.cancel();
}
function runWorker(operation, payload) {
  cancelJob(operation);
  return new Promise((resolve, reject) => {
    const worker = new Worker("./report-worker.mjs", { type: "module" });
    const finish = (callback, value) => {
      clearTimeout(timer);
      worker.terminate();
      if (jobs.get(operation)?.worker === worker) jobs.delete(operation);
      callback(value);
    };
    const timer = setTimeout(() => finish(reject, new Error("The viewer stopped reading after five seconds.")), 5000);
    jobs.set(operation, { worker, cancel: () => finish(reject, cancelled()) });
    worker.onmessage = ({ data }) => data.ok ? finish(resolve, data) : finish(reject, new Error(data.message));
    worker.onerror = () => finish(reject, new Error("The report reader could not start. Reload this page to try again."));
    worker.postMessage({ operation, ...payload });
  });
}
async function sha256(bytes) {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
async function fetchPinned(asset) {
  if (!/^(reports|downloads)\/[a-zA-Z0-9._-]+$/.test(asset.path) || !/^[a-f0-9]{64}$/.test(asset.sha256)) {
    throw new Error("Invalid release asset identity.");
  }
  const response = await fetch("./" + asset.path, { cache: "no-store", credentials: "omit" });
  if (!response.ok) throw new Error("A retained release report is unavailable.");
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== asset.bytes || await sha256(bytes) !== asset.sha256) {
    throw new Error("A retained report does not match its recorded SHA-256. Reload to try again.");
  }
  return bytes;
}
function activateTab(name, focus = false) {
  for (const id of ["comparison", "report", "local"]) {
    const active = id === name;
    byId("tab-" + id).setAttribute("aria-selected", String(active));
    byId("tab-" + id).tabIndex = active ? 0 : -1;
    byId("pane-" + id).hidden = !active;
  }
  if (focus) byId("tab-" + name).focus();
}
function observed(call) {
  if (!call) return "Not observed";
  return ({ 0: "Accepted", 1: "Accepted with message", 2: "Rejected" }[call.code] ?? "Return") + " · " + call.code;
}
function status(label, ok) {
  return element("span", label, "status " + (ok ? "good" : "bad"));
}
function rowCell(content, label) {
  const td = element("td", Array.isArray(content) ? content : [content]);
  td.dataset.label = label;
  return td;
}
function caseTitle(c, meta) {
  const parameter = meta?.parameters.find((p) => p.name === c.parameter);
  const variant = c.id.split("/").at(-1).replaceAll("_", " ");
  const label = variant === "nan" ? "NaN" : variant;
  return parameter ? parameter.description + " (" + parameter.name + ") · " + label : c.title;
}
function caseButton(c, meta, onClick) {
  const button = element("button", caseTitle(c, meta), "case-button");
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}
function renderComparisonRows() {
  const mode = byId("case-filter").value;
  const rows = comparison.comparison.rows.filter((row) =>
    mode === "all" || (mode === "changed" ? row.changed : !row.changed));
  const tbody = byId("comparison-table").querySelector("tbody");
  tbody.replaceChildren(...rows.map((row) => {
    const tr = element("tr");
    tr.dataset.case = row.id;
    const button = caseButton(row.before, comparison.original.metadata, () => {
      for (const other of tbody.children) other.classList.toggle("selected", other === tr);
      renderDetail("comparison-detail", row.before, comparison.original.metadata, row.after);
    });
    tr.append(
      rowCell([button, element("span", row.before.input === "nan" ? "Input: NaN" : "Input: " + row.before.input, "secondary")], "Parameter / input"),
      rowCell(status(observed(row.before.calls[0]), row.before.ok), "Original build"),
      rowCell(status(observed(row.after.calls[0]), row.after.ok), "Proposed correction"),
      rowCell(element("span", row.changed ? "Corrected" : "Unchanged", "observation" + (row.changed ? " changed" : "")), "Observation"),
    );
    return tr;
  }));
  byId("comparison-detail").hidden = true;
}
const checkNames = {
  return_code: "Return code",
  metadata_unchanged: "Model metadata unchanged",
  instance_fields_unchanged: "Instance fields unchanged",
  error_message: "Active error diagnostic",
  general_message: "Active general diagnostic",
};
function checkName(name) {
  return checkNames[name] ?? name.replaceAll("/", " · ").replaceAll("_", " ");
}
function callView(call, index) {
  const result = element("div", undefined, "call");
  const failed = call.checks.filter((check) => !check.ok);
  result.append(element("div", [
    element("span", index === 0 ? "Parameter validation" : "Same-instance valid recheck"),
    status(observed(call), !failed.length),
  ], "call-head"));
  result.append(element("p", "Expected return: " + call.expected + ". Recorded checks: " + call.checks.length + ".", "muted"));
  if (failed.length) result.append(element("ul", failed.map((check) => element("li", checkName(check.name))), "check-list"));
  if (call.channel) {
    const message = call.channel === "error" ? call.error : call.general;
    result.append(element("p", "Active diagnostic: " + (call.channel === "error" ? "LastErrorMessage" : "LastGeneralMessage") + ".", "muted"));
    if (message) result.append(element("pre", message, "diagnostic"));
  }
  return result;
}
function caseColumn(c, title) {
  const column = element("div", [element("h4", title)], "detail-column");
  if (c.calls.length) column.append(...c.calls.map(callView));
  else column.append(element("p", c.detail || c.execution, "muted"));
  column.append(element("p", "Metadata recheck: " + (c.metadataUnchanged ? "unchanged" : "not confirmed") + ".", "small muted"));
  return column;
}
function renderDetail(id, before, meta, after) {
  const container = byId(id);
  const close = element("button", "Close", "button");
  close.type = "button";
  close.addEventListener("click", () => { container.hidden = true; });
  container.replaceChildren(
    element("div", [element("h3", caseTitle(before, meta)), close], "toolbar"),
    element("p", "Case: " + before.id + " · Input: " + before.input, "small muted"),
    element("div", after ? [caseColumn(before, "Original build"), caseColumn(after, "Proposed correction")]
      : [caseColumn(before, "Reported observations")], "detail-columns"),
  );
  container.hidden = false;
}
function descriptionList(items) {
  const dl = element("dl", undefined, "identity-grid");
  for (const [label, value] of items) dl.append(element("dt", label), element("dd", value || "Not supplied"));
  return dl;
}
function dataTable(headers, rows) {
  const table = element("table");
  const head = element("tr", headers.map((title) => {
    const th = element("th", title); th.scope = "col"; return th;
  }));
  table.append(element("thead", [head]), element("tbody", rows.map((row) =>
    element("tr", row.map((value) => element("td", String(value)))))));
  return element("div", [table], "table-wrap");
}
function renderMetadata(id, report, reportHash, second) {
  const container = byId(id);
  const identity = (r, hash) => [
    ["Library", r.library.name], ["Library SHA-256", r.library.sha256], ["Report SHA-256", hash],
    ["Adapter", r.adapter.id], ["Adapter SHA-256", r.adapter.sha256],
    ["Checker", r.checkerVersion], ["Recorded host", r.host.os + " / " + r.host.architecture + " / Python " + r.host.python],
    ["Supplied build source", r.sourceCommit],
  ];
  container.replaceChildren(descriptionList(identity(report, reportHash)));
  if (second) container.append(element("h4", "Proposed correction"), descriptionList(identity(second.report, second.hash)));
  const m = report.metadata;
  if (!m) { container.append(element("p", report.metadataFailure, "muted")); return; }
  container.append(element("h4", "Declared model metadata"),
    descriptionList([["Model", m.model], ["Model version", m.modelVersion],
      ["Interface version", m.version], ["Declared sample time", m.sampleTime + " s"]]));
  container.append(element("h4", "Parameters"), dataTable(["Parameter", "Default", "Minimum", "Maximum", "Fixed"],
    m.parameters.map((p) => [p.description + " (" + p.name + ")", p.default, p.minimum, p.maximum, p.fixed ? "Yes" : "No"])));
  for (const [title, rows] of [["Inputs", m.inputs], ["Outputs", m.outputs]]) {
    container.append(element("h4", title), dataTable(["Name", "Description", "Width", "Unit"],
      rows.map((p) => [p.name, p.description, p.width, p.unit])));
  }
  if (m.information) container.append(element("p", m.information, "small muted"));
}
async function loadComparison() {
  if (!manifest) return;
  const generation = ++comparisonGeneration;
  cancelJob("compare");
  comparison = null;
  comparisonBytes = null;
  byId("comparison-content").hidden = true;
  byId("comparison-error").hidden = true;
  byId("comparison-loading").hidden = false;
  const platform = manifest.platforms.find((item) => item.id === byId("platform").value);
  try {
    const [original, fixed] = await Promise.all([fetchPinned(platform.original), fetchPinned(platform.fixed)]);
    if (generation !== comparisonGeneration) return;
    const result = await runWorker("compare", { original, fixed, expected: manifest.expected_comparison, sources: manifest.sources });
    if (generation !== comparisonGeneration) return;
    comparison = result;
    comparisonBytes = { original, fixed, platform };
    byId("changed-count").textContent = String(result.comparison.changed);
    byId("unchanged-count").textContent = String(result.comparison.unchanged);
    byId("case-count").textContent = String(result.comparison.rows.length);
    renderComparisonRows();
    renderMetadata("comparison-metadata", result.original, platform.original.sha256,
      { report: result.fixed, hash: platform.fixed.sha256 });
    byId("comparison-content").hidden = false;
  } catch (error) {
    if (generation === comparisonGeneration && error.name !== "AbortError") showError("comparison-error", error);
  } finally {
    if (generation === comparisonGeneration) byId("comparison-loading").hidden = true;
  }
}
function resetLocal() {
  localGeneration++;
  cancelJob("open");
  localReport = null;
  localBytes = null;
  byId("report-content").hidden = true;
  byId("report-loading").hidden = true;
  byId("report-error").hidden = true;
}
async function openBytes(bytes, name, generation) {
  try {
    const [result, hash] = await Promise.all([runWorker("open", { buffer: bytes }), sha256(bytes)]);
    if (generation !== localGeneration) return;
    localReport = result.report;
    localBytes = bytes;
    const s = localReport.summary;
    byId("report-name").textContent = name;
    byId("report-outcome").replaceChildren(status(s.ok ? "Reported pass" : s.complete ? "Reported failures" : "Incomplete report", s.ok));
    byId("report-metrics").replaceChildren(...[[s.cases, "Cases recorded"], [s.failedCases, "Cases failed"], [s.checks, "Checks recorded"]]
      .map(([count, label]) => element("div", [element("strong", count), element("span", label)])));
    byId("report-scope").textContent = "Recorded scope: " + localReport.scope;
    const extra = [];
    if (localReport.metadataFailure) extra.push("Metadata: " + localReport.metadataFailure);
    if (s.pending) extra.push(s.pending + " cases not executed.");
    if (s.skipped) extra.push(s.skipped + " probes excluded by the selected profile.");
    byId("report-extra").textContent = extra.join(" ");
    byId("report-extra").hidden = !extra.length;
    const tbody = byId("report-table").querySelector("tbody");
    tbody.replaceChildren(...localReport.cases.map((c) => {
      const tr = element("tr");
      tr.append(rowCell(caseButton(c, localReport.metadata, () => renderDetail("report-detail", c, localReport.metadata)), "Case"),
        rowCell(element("span", observed(c.calls[0]), "small"), "Observed return"),
        rowCell(status(c.ok ? "Matched" : "Failed", c.ok), "Reported outcome"),
        rowCell(element("span", c.calls.reduce((n, call) => n + call.checks.length, 0), "small"), "Checks"));
      return tr;
    }));
    byId("report-detail").hidden = true;
    renderMetadata("report-metadata", localReport, hash);
    byId("report-content").hidden = false;
  } catch (error) {
    if (generation === localGeneration && error.name !== "AbortError") showError("report-error", error);
  } finally {
    if (generation === localGeneration) byId("report-loading").hidden = true;
  }
}
async function openFile(file) {
  resetLocal();
  const generation = localGeneration;
  if (!file || !file.name.toLowerCase().endsWith(".json")) {
    showError("report-error", new Error("Choose a JSON report generated by the checker."));
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showError("report-error", new Error("Reports must be 2 MB or smaller."));
    return;
  }
  byId("report-loading").hidden = false;
  try {
    const bytes = await file.arrayBuffer();
    if (generation === localGeneration) await openBytes(bytes, file.name, generation);
  } catch {
    if (generation === localGeneration) {
      byId("report-loading").hidden = true;
      showError("report-error", new Error("This file could not be read."));
    }
  }
}
function download(bytes, name) {
  if (!bytes) return;
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/json" }));
  const anchor = element("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderCommands() {
  const wheel = "https://github.com/wattness/inverter-interface-checks/releases/download/v0.2.3/inverter_interface_checks-0.2.3-py3-none-any.whl";
  const windows = byId("command-platform").value === "windows";
  const python = windows ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";
  byId("local-commands").textContent = [
    windows ? "py -3.12 -m venv .venv" : "python3.12 -m venv .venv",
    python + " -m pip install " + wheel,
    python + " -m inverter_interface_checks --library " + (windows ? "C:\\path\\GFM_Battery_OpenIBR.dll" : "/path/to/GFM_Battery_OpenIBR.so")
      + " --adapter openibr-1.1 --output report.json",
  ].join("\n");
  byId("copy-status").textContent = "";
}
for (const name of ["comparison", "report", "local"]) {
  byId("tab-" + name).addEventListener("click", () => activateTab(name));
  byId("tab-" + name).addEventListener("keydown", (event) => {
    const names = ["comparison", "report", "local"];
    const index = names.indexOf(name);
    const next = { ArrowRight: (index + 1) % 3, ArrowLeft: (index + 2) % 3, Home: 0, End: 2 }[event.key];
    if (next !== undefined) { event.preventDefault(); activateTab(names[next], true); }
  });
}
byId("platform").addEventListener("change", loadComparison);
byId("case-filter").addEventListener("change", renderComparisonRows);
byId("report-file").addEventListener("change", (event) => openFile(event.target.files[0]));
byId("inspect-text").addEventListener("click", () => {
  resetLocal();
  byId("report-loading").hidden = false;
  openBytes(new TextEncoder().encode(byId("report-text").value).buffer, "Pasted report JSON", localGeneration);
});
byId("clear-report").addEventListener("click", () => {
  resetLocal(); byId("report-file").value = ""; byId("report-text").value = "";
});
for (const event of ["dragenter", "dragover", "dragleave", "drop"]) {
  byId("drop-zone").addEventListener(event, (e) => {
    e.preventDefault();
    byId("drop-zone").classList.toggle("over", event === "dragenter" || event === "dragover");
    if (event === "drop") {
      if (e.dataTransfer.files.length === 1) openFile(e.dataTransfer.files[0]);
      else { resetLocal(); showError("report-error", new Error("Choose one JSON report at a time.")); }
    }
  });
}
byId("download-original").addEventListener("click", () => download(comparisonBytes?.original, "openibr-" + comparisonBytes?.platform.id + "-original.json"));
byId("download-fixed").addEventListener("click", () => download(comparisonBytes?.fixed, "openibr-" + comparisonBytes?.platform.id + "-corrected.json"));
byId("download-user").addEventListener("click", () => download(localBytes, "inverter-interface-report.json"));
byId("command-platform").addEventListener("change", renderCommands);
byId("go-report").addEventListener("click", () => activateTab("report", true));
byId("copy-commands").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(byId("local-commands").textContent);
    byId("copy-status").textContent = "Copied.";
  } catch {
    byId("copy-status").textContent = "Select the commands above to copy them.";
  }
});
window.addEventListener("pagehide", () => {
  for (const operation of jobs.keys()) cancelJob(operation);
  localBytes = null; comparisonBytes = null;
});
renderCommands();
async function boot() {
  const response = await fetch("./manifest.json", { cache: "no-store", credentials: "omit" });
  if (!response.ok) throw new Error("The release manifest is unavailable.");
  manifest = await response.json();
  if (manifest.schema !== "inverter-interface-space/1" || manifest.checker.version !== "0.2.3"
    || manifest.platforms.map((p) => p.id).join(",") !== "linux-x64,macos-arm64,windows-x64") {
    throw new Error("Unsupported release manifest.");
  }
  for (const [id, source] of [["original", manifest.sources.original], ["fixed", manifest.sources.fixed]]) {
    if (!/^[a-f0-9]{40}$/.test(source.commit) || !/^https:\/\/github\.com\/(wattness|HeronPower)\/OpenIBR$/.test(source.repository)) {
      throw new Error("Invalid pinned build source.");
    }
    byId(id + "-source").href = source.repository + "/commit/" + source.commit;
    byId(id + "-source").textContent = (id === "original" ? "Original " : "Proposed ") + source.commit.slice(0, 7);
  }
  byId("download-wheel").href = "./" + manifest.checker.wheel.path;
  byId("wheel-hash").textContent = manifest.checker.wheel.sha256;
  await loadComparison();
}
boot().catch((error) => {
  byId("comparison-loading").hidden = true;
  showError("comparison-error", error);
});
