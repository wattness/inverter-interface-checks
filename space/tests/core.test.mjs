import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { parseJSON, jsonText, readReport, compareReports, LIMITS } from "../report-core.mjs";

const root = new URL("../", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("manifest.json", root), "utf8"));
const originalText = await readFile(new URL(manifest.platforms[0].original.path, root), "utf8");
const fixedText = await readFile(new URL(manifest.platforms[0].fixed.path, root), "utf8");
const fresh = () => JSON.parse(fixedText);
const encode = (value) => JSON.stringify(value);

for (const platform of manifest.platforms) {
  test(platform.label + ": exact retained comparison", async () => {
    const reports = {};
    for (const kind of ["original", "fixed"]) {
      const asset = platform[kind];
      const bytes = await readFile(new URL(asset.path, root));
      assert.equal(bytes.length, asset.bytes);
      assert.equal(createHash("sha256").update(bytes).digest("hex"), asset.sha256);
      reports[kind] = readReport(bytes.toString("utf8"));
      assert.equal(reports[kind].library.sha256, asset.library_sha256);
      assert.equal(reports[kind].sourceCommit, manifest.sources[kind].commit);
    }
    const comparison = compareReports(reports.original, reports.fixed, manifest.expected_comparison);
    assert.equal(comparison.changed, 3);
    assert.equal(comparison.unchanged, 21);
    assert.equal(reports.original.summary.checks, 597);
    assert.equal(reports.fixed.summary.checks, 600);
    assert.equal(reports.original.summary.failedCases, 3);
    assert.equal(reports.fixed.summary.failedCases, 0);
    assert.equal(reports.fixed.cases.at(-2).calls[0].channel, null);
    assert.equal(reports.fixed.cases.at(-1).calls[0].channel, "error");
  });
}

test("released downloads retain their digests", async () => {
  for (const asset of [manifest.checker.wheel, manifest.native_validation, manifest.installation.wheel]) {
    const bytes = await readFile(new URL(asset.path, root));
    assert.equal(bytes.length, asset.bytes);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), asset.sha256);
  }
});

for (const input of ['{"x":1,"x":2}', '{"x":1,"\\u0078":2}', '{"nested":{"a":0,"a":1}}']) {
  test("duplicate keys are refused: " + input, () => assert.throws(() => parseJSON(input), /Duplicate/));
}
for (const input of ["NaN", "Infinity", "-Infinity", "1e400", "-1e400", '{"a":1e400}']) {
  test("nonfinite values are refused: " + input, () => assert.throws(() => parseJSON(input)));
}
for (const input of ["01", "1.", "1e", "+1", "[1,]", '{"x":0,}', '{"x":}', '"bad\\x"', '"unterminated', "{} []"]) {
  test("malformed JSON is refused: " + input, () => assert.throws(() => parseJSON(input)));
}
for (const [open, close] of [["[", "]"], ['{"x":', "}"]]) {
  test("nesting boundary " + open, () => {
    assert.doesNotThrow(() => parseJSON(open.repeat(LIMITS.depth) + "0" + close.repeat(LIMITS.depth)));
    assert.throws(() => parseJSON(open.repeat(LIMITS.depth + 1) + "0" + close.repeat(LIMITS.depth + 1)), /nesting/);
  });
}
test("brackets in strings do not consume nesting", () => {
  assert.equal(jsonText(parseJSON(encode("[[".repeat(100) + "]]".repeat(100)))), encode("[[".repeat(100) + "]]".repeat(100)));
});
test("numeric lexemes retain large integers, precision, signed zero and underflow", () => {
  for (const input of ["9007199254740993", "1.234567890123456789", "-0", "-5e-324", "1e-4000"]) {
    assert.equal(jsonText(parseJSON(input)), input);
  }
});
test("object keys cannot change the parser's prototype", () => {
  const parsed = parseJSON('{"__proto__":{"polluted":true},"constructor":{"prototype":{"polluted":true}}}');
  assert.equal(Object.getPrototypeOf(parsed), null);
  assert.equal({}.polluted, undefined);
  assert.match(jsonText(parsed), /"__proto__"/);
});
test("byte limit accepts its boundary and rejects the next byte", () => {
  const atLimit = "0" + " ".repeat(LIMITS.bytes - 1);
  assert.doesNotThrow(() => parseJSON(atLimit));
  assert.throws(() => parseJSON(atLimit + " "), /2 MB/);
  assert.throws(() => parseJSON(encode("é".repeat(LIMITS.bytes / 2))), /2 MB/);
});
test("value and text limits are explicit", () => {
  assert.doesNotThrow(() => parseJSON("[" + Array(LIMITS.nodes - 1).fill("0").join(",") + "]"));
  assert.throws(() => parseJSON("[" + Array(LIMITS.nodes).fill("0").join(",") + "]"), /50,000/);
  assert.doesNotThrow(() => parseJSON(encode("a".repeat(LIMITS.text))));
  assert.throws(() => parseJSON(encode("a".repeat(LIMITS.text + 1))), /8,192/);
});
test("report version 1 is not silently reinterpreted", () => {
  const report = fresh();
  report.schema = "inverter-interface-report/1";
  assert.throws(() => readReport(encode(report)), /report\/2/);
});
test("an empty success packet is not a report", () => {
  assert.throws(() => readReport('{"ok":true}'));
  const report = fresh();
  report.cases = [];
  Object.assign(report.summary, { cases_executed: 0, cases_failed: 0, checks_executed: 0, checks_failed: 0 });
  assert.throws(() => readReport(encode(report)), /complete report/);
});
test("zero-check successful cases are refused", () => {
  const report = fresh();
  const removed = report.cases[0].calls[0].checks.length;
  report.cases[0].calls[0].checks = [];
  report.summary.checks_executed -= removed;
  assert.throws(() => readReport(encode(report)), /passing case/);
});
test("every reported summary count must match observations", () => {
  for (const key of ["cases_executed", "cases_failed", "checks_executed", "checks_failed"]) {
    const report = fresh();
    report.summary[key]++;
    assert.throws(() => readReport(encode(report)), /Summary/);
  }
});
test("booleans and numeric lookalikes cannot replace integer return codes", () => {
  const report = fresh();
  report.cases[0].calls[0].return_code = true;
  assert.throws(() => readReport(encode(report)), /JSON integer/);
  assert.throws(() => readReport(fixedText.replace('"return_code": 0', '"return_code": 0.0')), /JSON integer/);
});
test("a positive check cannot disguise an unexpected return", () => {
  const report = fresh();
  report.cases[0].calls[0].return_code = 2;
  assert.throws(() => readReport(encode(report)), /contradicts/);
});
test("passing cases need the requested recheck", () => {
  const report = fresh();
  const c = report.cases.find((c) => c.case.kind === "invalid");
  report.summary.checks_executed -= c.calls.at(-1).checks.length;
  c.calls.pop();
  assert.throws(() => readReport(encode(report)), /complete passing-case/);
});
test("duplicate cases and checks are refused", () => {
  const report = fresh();
  report.cases[1].case.id = report.cases[0].case.id;
  assert.throws(() => readReport(encode(report)), /duplicate case/);
  const other = fresh();
  other.cases[0].calls[0].checks.push(other.cases[0].calls[0].checks[0]);
  other.summary.checks_executed++;
  assert.throws(() => readReport(encode(other)), /Duplicate check/);
});
test("diagnostic channels follow the observed return", () => {
  const report = fresh();
  const call = report.cases.find((c) => c.case.kind === "invalid").calls[0];
  call.diagnostic_channel = "general";
  assert.throws(() => readReport(encode(report)), /Diagnostic channel/);
  const inactive = fresh();
  inactive.cases[0].calls[0].error_message = "unobserved stale text";
  assert.throws(() => readReport(encode(inactive)), /inactive error/);
});
test("native metadata failure stays an incomplete observation", () => {
  const report = fresh();
  report.metadata = { ok: false, execution: "missing_exports", detail: "Model_GetInfo missing" };
  report.cases = [];
  Object.assign(report.summary, { ok: false, complete: false, cases_executed: 0, cases_failed: 0, checks_executed: 0, checks_failed: 0 });
  const parsed = readReport(encode(report));
  assert.equal(parsed.summary.complete, false);
  assert.equal(parsed.metadata, null);
  assert.equal(parsed.metadataFailure, "Model_GetInfo missing");
});
test("unexecuted cases cannot be relabelled as complete", () => {
  const report = fresh();
  report.unexecuted_case_ids = report.cases.map((c) => c.case.id);
  report.cases = [];
  Object.assign(report.summary, { ok: false, complete: false, cases_executed: 0, cases_failed: 0, checks_executed: 0, checks_failed: 0 });
  assert.equal(readReport(encode(report)).summary.pending, 24);
  report.summary.complete = true;
  assert.throws(() => readReport(encode(report)), /completeness/);
});
test("case process failures retain their original detail", () => {
  const report = fresh();
  const checks = report.cases[0].calls[0].checks.length;
  Object.assign(report.cases[0], { ok: false, calls: [], execution: "worker_timeout", detail: "worker exceeded its limit" });
  Object.assign(report.summary, { ok: false, cases_failed: 1, checks_executed: report.summary.checks_executed - checks });
  const parsed = readReport(encode(report));
  assert.equal(parsed.summary.complete, true);
  assert.equal(parsed.summary.failedCases, 1);
  assert.equal(parsed.cases[0].detail, "worker exceeded its limit");
});
test("release comparison refuses a changed control, policy or source request", () => {
  const original = readReport(originalText);
  const report = fixedText.replace('"general_pointer_present": false', '"general_pointer_present": true');
  assert.throws(() => compareReports(original, readReport(report), manifest.expected_comparison), /release comparison/);
  const metadataChanged = fixedText.replace('"description": "Inertia constant"', '"description": "different"');
  assert.throws(() => compareReports(original, readReport(metadataChanged), manifest.expected_comparison), /metadata changed/);
  const policyChanged = fixedText.replace('"bounds": "inclusive"', '"bounds": "skip"');
  assert.throws(() => compareReports(original, readReport(policyChanged), manifest.expected_comparison), /policy changed/);
});
