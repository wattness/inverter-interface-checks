// Read report version 2. These checks describe a file; they do not run a model.
export const LIMITS = Object.freeze({
  bytes: 2 * 1024 * 1024, depth: 64, nodes: 50_000, cases: 256, text: 8192,
});

class JsonNumber {
  constructor(raw) {
    this.raw = raw;
    this.value = Number(raw);
    if (!Number.isFinite(this.value)) throw new Error("Nonfinite JSON number.");
  }
}

function need(condition, message) {
  if (!condition) throw new Error(message);
}

export function parseJSON(text) {
  need(typeof text === "string", "Expected UTF-8 JSON text.");
  need(new TextEncoder().encode(text).length <= LIMITS.bytes, "Reports must be 2 MB or smaller.");
  let at = 0;
  let nodes = 0;
  const whitespace = () => { while (/[ \t\r\n]/.test(text[at] ?? "x")) at++; };
  const string = () => {
    need(text[at] === '"', "Expected a JSON string.");
    const start = at++;
    while (at < text.length) {
      const ch = text[at++];
      if (ch === "\\") at++;
      else if (ch === '"') {
        const result = JSON.parse(text.slice(start, at));
        need(result.length <= LIMITS.text, "A JSON text field exceeds 8,192 characters.");
        return result;
      }
    }
    throw new Error("Unterminated JSON string.");
  };
  const value = (depth) => {
    whitespace();
    need(++nodes <= LIMITS.nodes, "A report exceeds 50,000 JSON values.");
    const ch = text[at];
    if (ch === "{" || ch === "[") {
      need(depth < LIMITS.depth, "JSON nesting exceeds 64 levels.");
      at++;
      const object = ch === "{";
      const end = object ? "}" : "]";
      const result = object ? Object.create(null) : [];
      const keys = new Set();
      whitespace();
      if (text[at] === end) { at++; return result; }
      for (;;) {
        if (object) {
          whitespace();
          const key = string();
          need(!keys.has(key), "Duplicate JSON object key.");
          keys.add(key);
          whitespace();
          need(text[at++] === ":", "Expected a colon after a JSON key.");
          result[key] = value(depth + 1);
        } else result.push(value(depth + 1));
        whitespace();
        if (text[at] === end) { at++; return result; }
        need(text[at++] === ",", "Expected a comma between JSON values.");
      }
    }
    if (ch === '"') return string();
    for (const [token, result] of [["true", true], ["false", false], ["null", null]]) {
      if (text.startsWith(token, at)) { at += token.length; return result; }
    }
    const number = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(at));
    need(number, "Invalid JSON value.");
    at += number[0].length;
    return new JsonNumber(number[0]);
  };
  const result = value(0);
  whitespace();
  need(at === text.length, "Unexpected text after the JSON document.");
  return result;
}

export function jsonText(value) {
  if (value instanceof JsonNumber) return value.raw;
  if (Array.isArray(value)) return "[" + value.map(jsonText).join(", ") + "]";
  if (value !== null && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((key) =>
      JSON.stringify(key) + ": " + jsonText(value[key])).join(", ") + "}";
  }
  return JSON.stringify(value);
}

function object(value, name) {
  need(value !== null && typeof value === "object" && !Array.isArray(value)
    && !(value instanceof JsonNumber), name + " must be an object.");
  return value;
}
function array(value, name, maximum = 256) {
  need(Array.isArray(value) && value.length <= maximum, name + " must be a bounded array.");
  return value;
}
function text(value, name, maximum = LIMITS.text) {
  need(typeof value === "string" && value.length <= maximum, name + " must be text.");
  return value;
}
function flag(value, name) {
  need(typeof value === "boolean", name + " must be a JSON boolean.");
  return value;
}
function integer(value, name, minimum = 0, maximum = Number.MAX_SAFE_INTEGER) {
  need(value instanceof JsonNumber && /^-?(?:0|[1-9]\d*)$/.test(value.raw)
    && Number.isSafeInteger(value.value) && value.value >= minimum && value.value <= maximum,
  name + " must be a JSON integer within its declared range.");
  return value.value;
}
function digest(value, name) {
  need(typeof value === "string" && /^[a-f0-9]{64}$/.test(value), name + " must be a SHA-256 digest.");
  return value;
}
function scalar(value) {
  return typeof value === "string" ? value : jsonText(value);
}
function optionalText(value, name) {
  return value === null || value === undefined ? "" : text(value, name);
}

function metadata(result) {
  if (!result.ok) return null;
  const m = object(result.metadata, "Metadata");
  const model = text(m.ModelName, "Model name", 256);
  need(model.length > 0, "Missing model name.");
  array(m.interface_version, "Interface version", 4);
  need(m.interface_version.length === 4, "Incomplete interface version.");
  const version = m.interface_version.map((v) => integer(v, "Interface version", 0, 65535)).join(".");
  need(m.sample_time instanceof JsonNumber && m.sample_time.value > 0, "Invalid declared sample time.");
  const ports = (rows, name) => array(rows, name).map((row) => {
    object(row, name + " row");
    integer(row.datatype, "Port datatype", 0, 255);
    return {
      name: text(row.name, "Port name", 256), unit: text(row.unit, "Port unit", 256),
      description: text(row.description, "Port description"),
      width: integer(row.width, "Port width", 1, 256),
    };
  });
  const parameters = array(m.parameters, "Parameters").map((p) => {
    object(p, "Parameter");
    integer(p.datatype, "Parameter datatype", 0, 255);
    flag(p.fixed, "Fixed parameter flag");
    integer(p.fixed_value, "Raw fixed parameter flag", -2147483648, 2147483647);
    for (const name of ["default", "minimum", "maximum"]) {
      need(p[name] instanceof JsonNumber || typeof p[name] === "string",
        "Parameter " + name + " must be numeric or text.");
    }
    return {
      name: text(p.name, "Parameter name", 256),
      description: text(p.description, "Parameter description"),
      unit: text(p.unit, "Parameter unit", 256),
      default: scalar(p.default), minimum: scalar(p.minimum), maximum: scalar(p.maximum), fixed: p.fixed,
    };
  });
  object(result.native_layout, "Declared native layout");
  object(result.host_layouts, "Declared host layouts");
  need(Object.keys(result.native_layout).length > 0 && Object.keys(result.host_layouts).length > 0,
    "Missing declared layout evidence.");
  return {
    model, version, sampleTime: m.sample_time.raw, parameters,
    modelVersion: optionalText(m.ModelVersion, "Model version"),
    inputs: ports(m.inputs, "Inputs"), outputs: ports(m.outputs, "Outputs"),
    information: optionalText(m.GeneralInformation, "General information"),
  };
}

export function readReport(textInput) {
  const raw = parseJSON(textInput);
  object(raw, "Report");
  need(raw.schema === "inverter-interface-report/2", "Choose an inverter-interface-report/2 JSON report.");
  const identity = object(raw.identity, "Identity");
  const library = object(identity.library, "Library identity");
  const adapter = object(identity.adapter, "Adapter identity");
  const engine = object(identity.engine, "Checker identity");
  const host = object(identity.host, "Host identity");
  const policy = object(adapter.resolved_policy, "Resolved adapter policy");
  need(policy.schema === "inverter-interface-adapter/1", "Unsupported adapter policy schema.");
  need(["same-instance", "none"].includes(policy.recheck_policy), "Unsupported recheck policy.");
  const validCodes = array(policy.valid_returns, "Valid returns", 32).map((v) =>
    integer(v, "Return code", -2147483648, 2147483647));
  need(validCodes.length > 0, "Missing valid return codes.");
  const invalidCode = integer(policy.invalid_return, "Invalid return code", -2147483648, 2147483647);
  const nullInstanceCode = integer(policy.null_instance_return, "Null-instance return", -2147483648, 2147483647);
  const nullParametersCode = integer(policy.null_parameters_return, "Null-parameters return", -2147483648, 2147483647);
  const metaResult = object(raw.metadata, "Metadata observation");
  flag(metaResult.ok, "Metadata result");
  const meta = metadata(metaResult);
  const summary = object(raw.summary, "Summary");
  const pending = array(raw.unexecuted_case_ids, "Unexecuted cases", 65536);
  const skipped = array(raw.skipped, "Skipped probes", 65536);
  const results = array(raw.cases, "Cases", LIMITS.cases);
  const seen = new Set();
  let checkCount = 0;
  let failedChecks = 0;
  let failedCases = 0;
  const cases = results.map((r) => {
    object(r, "Case result");
    const c = object(r.case, "Requested case");
    const id = text(c.id, "Case identifier", 256);
    need(id && !seen.has(id), "Missing or duplicate case identifier.");
    seen.add(id);
    need(["valid", "invalid", "null_instance", "null_parameters"].includes(c.kind), "Invalid requested case kind.");
    flag(r.ok, "Case result");
    if (!r.ok) failedCases++;
    const execution = text(r.execution, "Case execution", 128);
    if (c.index !== undefined) {
      const index = integer(c.index, "Parameter index", 0, 255);
      need(meta && meta.parameters[index]?.name === c.parameter, "Case parameter does not match metadata.");
    }
    const kinds = [c.kind];
    if (c.kind === "invalid" && policy.recheck_policy === "same-instance") kinds.push("valid");
    const calls = array(r.calls ?? [], "Calls", 4).map((call, index) => {
      object(call, "Call");
      need(typeof call.kind === "string" && call.kind === kinds[index], "Call kind disagrees with the requested sequence.");
      const code = integer(call.return_code, "Observed return code", -2147483648, 2147483647);
      const checks = array(call.checks, "Call checks", 2048).map((check) => {
        object(check, "Check");
        flag(check.ok, "Check result");
        checkCount++;
        if (!check.ok) failedChecks++;
        return { name: text(check.check, "Check name", 256), ok: check.ok };
      });
      const names = new Set(checks.map((check) => check.name));
      need(names.size === checks.length, "Duplicate check in one call.");
      if (r.ok) need(checks.length > 0 && checks.every((check) => check.ok), "Incomplete or contradictory passing case.");
      const expected = call.kind === "valid" ? validCodes
        : call.kind === "invalid" ? [invalidCode]
          : call.kind === "null_instance" ? [nullInstanceCode] : [nullParametersCode];
      const returned = checks.find((check) => check.name === "return_code");
      if (returned) need(returned.ok === expected.includes(code), "Return-code check contradicts the observed return.");
      if (r.ok) need(returned && returned.ok, "Missing return-code evidence.");
      if (c.kind === "null_instance") {
        need(call.error_pointer_present === null && call.general_pointer_present === null,
          "A null Instance cannot supply diagnostic pointer observations.");
      } else {
        flag(call.error_pointer_present, "Error pointer presence");
        flag(call.general_pointer_present, "General pointer presence");
      }
      const channel = call.diagnostic_channel;
      const expectedChannel = c.kind === "null_instance" ? null
        : code === 1 ? "general" : code === 2 ? "error" : null;
      need(channel === expectedChannel, "Diagnostic channel disagrees with the observed call.");
      const error = optionalText(call.error_message, "Error diagnostic");
      const general = optionalText(call.general_message, "General diagnostic");
      if (channel !== "error") need(error === "", "An inactive error diagnostic has text.");
      if (channel !== "general") need(general === "", "An inactive general diagnostic has text.");
      return {
        kind: call.kind, code, checks, channel, error, general,
        mutations: jsonText(call.parameter_mutations ?? []),
        expected: expected.join(" or "),
      };
    });
    if (r.ok) {
      need(execution === "completed" && r.metadata_unchanged === true
        && r.recheck_policy === policy.recheck_policy && calls.length === kinds.length,
      "Missing complete passing-case evidence.");
    }
    need(r.ok || !calls.length || calls.some((call) => call.checks.some((check) => !check.ok))
      || r.metadata_unchanged !== true || execution !== "completed",
    "A failed case has no reported failure.");
    const parameter = c.parameter === undefined ? "" : text(c.parameter, "Case parameter", 256);
    const variant = id.split("/").at(-1).replaceAll("_", " ");
    const title = parameter ? parameter + " · " + variant : id.replaceAll("_", " ");
    return {
      id, title, parameter, kind: c.kind, input: c.value === undefined ? "—" : scalar(c.value),
      ok: r.ok, execution, calls, metadataUnchanged: r.metadata_unchanged === true,
      detail: optionalText(r.detail, "Case failure detail"),
      canonical: jsonText(Object.fromEntries(Object.entries(r).filter(([key]) => key !== "elapsed_seconds"))),
    };
  });
  const complete = metaResult.ok && pending.length === 0;
  if (complete) need(["defaults", "null_instance", "null_parameters"].every((id) => seen.has(id)),
    "A complete report is missing its default or null-pointer cases.");
  flag(summary.ok, "Summary result");
  flag(summary.complete, "Summary completeness");
  need(summary.complete === complete, "Summary completeness contradicts metadata or unexecuted cases.");
  need(summary.ok === (complete && failedCases === 0), "Summary result contradicts its cases.");
  for (const [name, value] of [
    ["cases_executed", cases.length], ["cases_failed", failedCases],
    ["checks_executed", checkCount], ["checks_failed", failedChecks],
  ]) need(integer(summary[name], "Summary " + name, 0) === value, "Summary " + name + " does not match its observations.");
  return {
    raw, metadata: meta, cases,
    library: { name: text(library.name, "Library name", 256), sha256: digest(library.sha256, "Library hash") },
    adapter: { id: text(adapter.id, "Adapter name", 256), sha256: digest(adapter.sha256, "Adapter hash") },
    checkerVersion: text(engine.version, "Checker version", 128),
    host: { os: text(host.os, "Host OS", 128), architecture: text(host.architecture, "Host architecture", 128),
      python: text(host.python, "Host Python", 128) },
    scope: text(raw.scope, "Report scope"),
    sourceCommit: optionalText(identity.build_receipt?.source_commit, "Supplied build source commit"),
    summary: { ok: summary.ok, complete, cases: cases.length, failedCases, checks: checkCount, failedChecks,
      skipped: skipped.length, pending: pending.length },
    metadataFailure: metaResult.ok ? "" : optionalText(metaResult.detail ?? metaResult.execution, "Metadata failure"),
  };
}

export function compareReports(original, fixed, expected) {
  need(original.summary.complete && fixed.summary.complete, "The comparison needs two complete reports.");
  need(jsonText(original.raw.metadata.metadata) === jsonText(fixed.raw.metadata.metadata), "Model metadata changed.");
  need(jsonText(original.raw.identity.adapter) === jsonText(fixed.raw.identity.adapter), "Adapter or policy changed.");
  need(jsonText(original.host) === jsonText(fixed.host), "Reports were produced on different hosts.");
  need(original.cases.length === fixed.cases.length, "Case lists differ.");
  const rows = original.cases.map((before, index) => {
    const after = fixed.cases[index];
    need(before.id === after.id, "Case order differs.");
    need(jsonText(original.raw.cases[index].case) === jsonText(fixed.raw.cases[index].case), "Requested case changed.");
    return { id: before.id, title: before.title, before, after, changed: before.canonical !== after.canonical };
  });
  const changed = rows.filter((row) => row.changed);
  need(rows.length === expected.cases && changed.length === expected.changed_cases
    && rows.length - changed.length === expected.unchanged_cases
    && changed.every((row, index) => row.id === expected.changed_ids[index]),
  "Reports do not match the recorded release comparison.");
  need(original.summary.failedCases === 3 && fixed.summary.failedCases === 0,
    "Unexpected release outcomes.");
  need(changed.every((row) => row.before.input === "nan" && row.before.calls[0].code === 0
    && row.after.calls[0].code === 2 && !row.before.ok && row.after.ok),
  "The changed cases do not show the recorded NaN correction.");
  return { rows, changed: changed.length, unchanged: rows.length - changed.length };
}

export function displayReport(report) {
  const { raw, ...display } = report;
  return display;
}
