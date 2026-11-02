import { readReport, compareReports, displayReport, LIMITS } from "./report-core.mjs";

function decode(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength > LIMITS.bytes) {
    throw new Error("Reports must be 2 MB or smaller.");
  }
  return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(buffer);
}

self.onmessage = async ({ data }) => {
  try {
    if (data.operation === "compare") {
      const original = readReport(decode(data.original));
      const fixed = readReport(decode(data.fixed));
      const comparison = compareReports(original, fixed, data.expected);
      if (original.sourceCommit !== data.sources.original.commit
        || fixed.sourceCommit !== data.sources.fixed.commit) {
        throw new Error("Report build sources do not match the release pins.");
      }
      self.postMessage({
        ok: true, operation: "compare", comparison,
        original: displayReport(original), fixed: displayReport(fixed),
      });
    } else if (data.operation === "open") {
      self.postMessage({ ok: true, operation: "open", report: displayReport(readReport(decode(data.buffer))) });
    } else throw new Error("Unsupported viewer operation.");
  } catch (error) {
    self.postMessage({ ok: false, message: error instanceof Error ? error.message : "The report could not be read." });
  }
};
