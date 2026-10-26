"""Native software fixtures exercise independent successes and deliberate defects."""

import argparse
import ctypes as c
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from inverter_interface_checks import abi
from inverter_interface_checks.cli import inspect, render_text
from inverter_interface_checks.contracts import load_adapter
from inverter_interface_checks.process import run_worker, sha256
from inverter_interface_checks.worker import GuardedBuffer
from tools.build_fixture import compile_fixture

ROOT = Path(__file__).resolve().parent.parent
SUFFIX = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"


class NativeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="interface-fixtures-")
        cls.directory = Path(cls.temporary.name)
        cls.libraries = {}
        cls.compiler = os.environ.get("CC")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def library(self, mode):
        if mode not in self.libraries:
            path = self.directory / f"{mode}{SUFFIX}"
            receipt = compile_fixture(path, mode, self.compiler)
            self.libraries[mode] = (path, receipt)
        return self.libraries[mode][0]

    def request(self, mode, adapter=None):
        library = self.library(mode)
        adapter = adapter or load_adapter("ieee-cigre-1.1")[0]
        return {"library": str(library), "library_sha256": sha256(library),
                "adapter": adapter, "timeout": 1.0, "action": "metadata"}

    def probe(self, mode, case=None, adapter=None, timeout=1.0):
        request = self.request(mode, adapter)
        metadata = run_worker(request, timeout)
        if case is None or not metadata["ok"]:
            return metadata
        request.update(action="case", metadata=metadata["metadata"], case=case)
        return run_worker(request, timeout)

    def report(self, mode="good", adapter="ieee-cigre-1.1", **changes):
        arguments = dict(library=self.library(mode), adapter=adapter, timeout=1.0,
                         total_timeout=15.0, max_cases=256, source=[], compiler=None,
                         build_receipt=None)
        arguments.update(changes)
        return inspect(argparse.Namespace(**arguments))

    def test_good_full_contract(self):
        report = self.report()
        self.assertTrue(report["summary"]["ok"], render_text(report))
        self.assertEqual(report["summary"]["cases_executed"], 24)
        self.assertEqual(report["summary"]["checks_failed"], 0)
        self.assertEqual(report["metadata"]["metadata"]["parameters"][0]["datatype"], 8)
        self.assertEqual(report["identity"]["library"]["sha256"], sha256(self.library("good")))
        self.assertEqual(len(report["skipped"]), 2)

    def test_header_and_mixed_parameter_layout(self):
        executable = self.directory / ("layout.exe" if os.name == "nt" else "layout")
        compile_fixture(executable, compiler=self.compiler, layout=True)
        result = subprocess.run([str(executable)], capture_output=True, timeout=5, check=True)
        layout = json.loads(result.stdout)
        for name in ("Signal", "Parameter", "ModelInfo", "Instance"):
            self.assertEqual(layout[name], c.sizeof(getattr(abi, name)))
        metadata = self.probe("good")["metadata"]
        parameters = abi.host_structure("MixedParameters", metadata["parameters"])
        self.assertEqual(layout["Parameters"], c.sizeof(parameters))
        self.assertEqual(layout["parameters_offsets"], [
            getattr(parameters, name).offset for name, _ in parameters._fields_
        ])

    def test_validation_defects(self):
        invalid = {"id": "nan", "kind": "invalid", "index": 0, "value": "nan"}
        low = {"id": "low", "kind": "valid", "index": 0, "value": -2.0}
        defaults = {"id": "defaults", "kind": "valid"}
        for mode, case, finding in (
            ("nan", invalid, "return_code"),
            ("bounds", low, "return_code"),
            ("return", defaults, "return_code"),
            ("message", invalid, "error_message"),
            ("parameter-write", defaults, "Parameters/unchanged"),
            ("input-write", defaults, "ExternalInputs/unchanged"),
            ("overrun", defaults, "Parameters/guards"),
            ("state-write", defaults, "IntStates/unchanged"),
            ("string-write", defaults, "parameter_string[4]/unchanged"),
            ("state-padding", defaults, "FloatStates/guards"),
            ("instance-padding", defaults, "instance_fields_unchanged"),
        ):
            with self.subTest(mode=mode):
                result = self.probe(mode, case)
                self.assertFalse(result["ok"], result)
                failed = [item["check"] for call in result["calls"]
                          for item in call["checks"] if not item["ok"]]
                self.assertIn(finding, failed)

    def test_valid_recheck_and_message_policy(self):
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["clear_error_on_success"] = True
        case = {"id": "nan", "kind": "invalid", "index": 0, "value": "nan"}
        self.assertTrue(self.probe("good", case, adapter)["ok"])
        result = self.probe("stale-message", case, adapter)
        self.assertFalse(result["ok"])
        self.assertEqual(result["calls"][1]["kind"], "valid")
        self.assertEqual(result["calls"][1]["return_code"], 0)
        self.assertIn("success_error_cleared", [item["check"] for item in
                      result["calls"][1]["checks"] if not item["ok"]])

    def test_malformed_metadata_and_missing_exports(self):
        for mode in ("metadata", "missing-export", "null-info", "metadata-pointer",
                     "sample-time", "metadata-nan", "port-width", "duplicate-name",
                     "interface-version", "text-encoding"):
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertFalse(result["ok"])
        missing = self.probe("missing-export")
        self.assertEqual(missing["missing_exports"], ["Model_Terminate"])

    def test_metadata_immutability(self):
        result = self.probe("metadata-write", {"id": "defaults", "kind": "valid"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["metadata_unchanged"])

    def test_warning_dispatch_and_inactive_diagnostics(self):
        defaults = {"id": "defaults", "kind": "valid"}
        invalid = {"id": "nan", "kind": "invalid", "index": 0, "value": "nan"}
        result = self.probe("warning", defaults)
        self.assertTrue(result["ok"], result)
        call = result["calls"][0]
        self.assertEqual(call["return_code"], 1)
        self.assertEqual(call["diagnostic_channel"], "general")
        self.assertEqual(call["general_message"], "Software warning")
        self.assertIsNone(call["error_message"])
        self.assertTrue(call["error_pointer_present"])
        self.assertFalse(self.probe("warning-message", defaults)["ok"])
        for mode, case in (("inactive-error", defaults), ("inactive-general", invalid)):
            with self.subTest(mode=mode):
                result = self.probe(mode, case)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["execution"], "completed")
        result = self.probe("inactive-unknown", defaults)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution"], "completed")
        self.assertIsNone(result["calls"][0]["diagnostic_channel"])
        self.assertIsNone(result["calls"][0]["error_message"])
        self.assertIsNone(result["calls"][0]["general_message"])

    def test_stale_pointer_clear_policy_uses_presence(self):
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["clear_error_on_success"] = True
        result = self.probe("inactive-error", {"id": "defaults", "kind": "valid"}, adapter)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution"], "completed")
        self.assertIn("success_error_cleared", [check["check"] for check in result["calls"][0]["checks"]
                                              if not check["ok"]])

    def test_instance_boundary_is_guarded(self):
        result = self.probe("instance-overrun", {"id": "defaults", "kind": "valid"})
        self.assertFalse(result["ok"])
        self.assertIn("Instance/guards", [check["check"] for check in result["calls"][0]["checks"]
                                         if not check["ok"]])

    def test_retry_policy_and_distinct_diagnostics(self):
        invalid = {"id": "nan", "kind": "invalid", "index": 0, "value": "nan"}
        result = self.probe("inactive-error", invalid)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["calls"]), 2)
        self.assertEqual(result["calls"][0]["error_message"], "Software parameter rejected")
        self.assertIsNone(result["calls"][1]["error_message"])
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["recheck_policy"] = "none"
        result = self.probe("retry-error", invalid, adapter)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["calls"]), 1)
        result = self.probe("retry-error", invalid)
        self.assertFalse(result["ok"])
        self.assertEqual([call["error_message"] for call in result["calls"]],
                         ["Software parameter rejected", "Different retry error"])

    def test_numeric_normalization_preserves_other_bytes(self):
        defaults = {"id": "defaults", "kind": "valid"}
        self.assertFalse(self.probe("normalization", defaults)["ok"])
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["parameter_mutation"] = "allow-normalization"
        result = self.probe("normalization", defaults, adapter)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["calls"][0]["parameter_mutations"][0]["parameter"], "count")
        invalid = {"id": "nan", "kind": "invalid", "index": 0, "value": "nan"}
        for mode, case in (("parameter-padding", defaults), ("parameter-pointer", defaults),
                           ("input-write", defaults), ("overrun", defaults),
                           ("parameter-write", invalid)):
            with self.subTest(mode=mode):
                self.assertFalse(self.probe(mode, case, adapter)["ok"])

    def test_raw_fixed_value_and_identifier_profiles(self):
        result = self.probe("fixed-value")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["metadata"]["parameters"][2]["fixed_value"], 7)
        self.assertTrue(result["metadata"]["parameters"][2]["fixed"])
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["fixed_value_policy"] = "zero-or-one"
        self.assertFalse(self.probe("fixed-value", adapter=adapter)["ok"])
        self.assertFalse(self.probe("identifier")["ok"])
        adapter["name_syntax"] = "nonempty"
        self.assertTrue(self.probe("identifier", adapter=adapter)["ok"])

    def test_normalized_values_follow_selected_contract(self):
        defaults = {"id": "defaults", "kind": "valid"}
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["parameter_mutation"] = "allow-normalization"
        for mode, finding in (("normalization-bounds", "parameter[2]/normalized_bounds"),
                              ("normalization-nan", "parameter[1]/normalized_finite"),
                              ("normalization-inf", "parameter[1]/normalized_finite")):
            with self.subTest(mode=mode):
                result = self.probe(mode, defaults, adapter)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["execution"], "completed")
                self.assertTrue(result["calls"][0]["parameter_mutations"])
                self.assertIn(finding, [check["check"] for check in result["calls"][0]["checks"]
                                        if not check["ok"]])
        adapter["bounds"] = "skip"
        self.assertTrue(self.probe("normalization-bounds", defaults, adapter)["ok"])
        self.assertFalse(self.probe("normalization-nan", defaults, adapter)["ok"])
        adapter["nonfinite"] = "skip"
        self.assertTrue(self.probe("normalization-nan", defaults, adapter)["ok"])
        adapter["bounds"] = "inclusive"
        self.assertFalse(self.probe("normalization-nan", defaults, adapter)["ok"])

    def test_normalization_uses_declared_char_signedness(self):
        defaults = {"id": "defaults", "kind": "valid", "index": 3, "value": -2}
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter.update(parameter_mutation="allow-normalization", char_signedness="signed")
        self.assertTrue(self.probe("signed-char", defaults, adapter)["ok"])

    def test_excluded_probe_policies_are_reported(self):
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["nonfinite"] = "skip"
        path = self.directory / "skip-nonfinite.json"
        path.write_text(json.dumps(adapter), encoding="utf-8")
        report = self.report("nan", str(path))
        self.assertTrue(report["summary"]["ok"], render_text(report))
        self.assertEqual(report["summary"]["cases_executed"], 18)
        self.assertTrue(any("nonfinite probes excluded" in row["reason"] for row in report["skipped"]))
        adapter["bounds"] = "skip"
        path = self.directory / "skip-bounds.json"
        path.write_text(json.dumps(adapter), encoding="utf-8")
        report = self.report("bounds", str(path))
        self.assertTrue(report["summary"]["ok"], render_text(report))
        self.assertEqual(report["summary"]["cases_executed"], 3)
        self.assertTrue(any("bounds probes excluded" in row["reason"] for row in report["skipped"]))

    def test_crash_timeout_and_output_bounds(self):
        case = {"id": "defaults", "kind": "valid"}
        for mode in ("crash", "timeout", "output-limit", "fast-output"):
            with self.subTest(mode=mode):
                result = self.probe(mode, case, timeout=0.4)
                self.assertFalse(result["ok"])
                self.assertIn(result["execution"], (
                    "native_crash", "worker_exit", "timeout", "output_limit"
                ))
                self.assertLess(result["elapsed_seconds"], 2.0)
                self.assertLessEqual(len(result.get("native_log", "").encode("utf-8")), 8192)
        self.assertTrue(self.probe("good", case)["ok"])

    @unittest.skipUnless(os.name == "posix", "POSIX process groups only")
    def test_completed_worker_stops_descendant(self):
        result = self.probe("descendant", {"id": "defaults", "kind": "valid"})
        self.assertTrue(result["ok"], result)
        pid = int(result["native_log"].strip().split(":")[1])
        self.assertGreater(pid, 0)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            completed = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                                       capture_output=True, timeout=1)
            state = completed.stdout.decode().strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(0.02)
        self.assertTrue(not state or state.startswith("Z"), f"descendant still running: {pid}/{state}")

    def test_library_identity_change_fails_before_load(self):
        request = self.request("good")
        request["library_sha256"] = "0" * 64
        result = run_worker(request, 1)
        self.assertFalse(result["ok"])
        self.assertIn("identity changed", result["detail"])

    def test_case_limit_does_not_silently_pass(self):
        report = self.report(max_cases=1)
        self.assertFalse(report["summary"]["ok"])
        self.assertFalse(report["summary"]["complete"])
        self.assertEqual(len(report["unexecuted_case_ids"]), 24)
        self.assertEqual(report["summary"]["cases_executed"], 0)

    def test_signed_and_unsigned_char_contracts(self):
        for mode, signedness in (("signed-char", "signed"), ("unsigned-char", "unsigned")):
            with self.subTest(mode=mode):
                adapter = load_adapter("ieee-cigre-1.1")[0]
                adapter["char_signedness"] = signedness
                path = self.directory / f"{mode}.json"
                path.write_text(json.dumps(adapter), encoding="utf-8")
                report = self.report(mode, str(path))
                self.assertTrue(report["summary"]["ok"], render_text(report))
                self.assertEqual(report["metadata"]["metadata"]["parameters"][3]["char_signedness"], signedness)
        result = self.probe("signed-char")
        self.assertFalse(result["ok"])
        self.assertIn("signedness", result["detail"])

    def test_json_cli_and_existing_output(self):
        receipt = self.libraries["good"][1] if "good" in self.libraries else None
        if receipt is None:
            self.library("good")
            receipt = self.libraries["good"][1]
        build_path = self.directory / "good-build.json"
        build_path.write_text(json.dumps(receipt), encoding="utf-8")
        output = self.directory / "good-report.json"
        command = [sys.executable, "-B", "-m", "inverter_interface_checks", "--library",
                   str(self.library("good")), "--format", "json", "--output", str(output),
                   "--build-receipt", str(build_path)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report, json.loads(output.read_text(encoding="utf-8")))
        self.assertEqual(report["identity"]["build_receipt"]["scope"], "software fixture")
        original = output.read_bytes()
        repeated = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=5)
        self.assertEqual(repeated.returncode, 2)
        self.assertEqual(output.read_bytes(), original)

    def test_malformed_build_receipt_has_no_output(self):
        build_path = self.directory / "invalid-build.json"
        output = self.directory / "invalid-report.json"
        for library in (None, [], "invalid"):
            with self.subTest(library=library):
                build_path.write_text(json.dumps({"schema": "inverter-fixture-build/1",
                                                   "library": library}), encoding="utf-8")
                command = [sys.executable, "-B", "-m", "inverter_interface_checks", "--library",
                           str(self.library("good")), "--output", str(output),
                           "--build-receipt", str(build_path)]
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=5)
                self.assertEqual(completed.returncode, 2)
                self.assertNotIn(b"Traceback", completed.stderr)
                self.assertFalse(output.exists())


class Contracts(unittest.TestCase):
    def test_guard_padding_is_protected(self):
        buffer = GuardedBuffer(c.c_float * 1)
        c.c_ubyte.from_address(buffer.pointer + buffer.size).value ^= 1
        self.assertFalse(buffer.intact())

    def test_unknown_adapter_fields_rejected(self):
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["arbitrary_native_call"] = "Model_Initialize"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapter.json"
            path.write_text(json.dumps(adapter), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown fields"):
                load_adapter(str(path))

    def test_adapter_return_types_and_policy_values(self):
        adapter = load_adapter("ieee-cigre-1.1")[0]
        invalid = [("valid_returns", [False]), ("valid_returns", [0.0]),
                   ("valid_returns", [0, True]), ("invalid_return", 2.0),
                   ("null_instance_return", 2.0), ("null_parameters_return", 2.0),
                   ("recheck_policy", True), ("parameter_mutation", "anything"),
                   ("nonfinite", None), ("name_syntax", "unicode"),
                   ("fixed_value_policy", []), ("bounds", "exclusive"),
                   ("expected_model_name", [])]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapter.json"
            for key, value in invalid:
                with self.subTest(key=key, value=value):
                    path.write_text(json.dumps({**adapter, key: value}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_adapter(str(path))

    def test_legacy_adapter_defaults_are_preserved(self):
        from inverter_interface_checks.contracts import POLICY_DEFAULTS
        adapter = load_adapter("ieee-cigre-1.1")[0]
        for key in POLICY_DEFAULTS:
            adapter.pop(key)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapter.json"
            path.write_text(json.dumps(adapter), encoding="utf-8")
            resolved = load_adapter(str(path))[0]
        for key, expected in POLICY_DEFAULTS.items():
            self.assertEqual(resolved[key], expected)


if __name__ == "__main__":
    unittest.main()
