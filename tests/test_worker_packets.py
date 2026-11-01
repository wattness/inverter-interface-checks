"""Independent passive worker packets; no model library is loaded."""

import argparse
import copy
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inverter_interface_checks import abi, cli, packets
from inverter_interface_checks.contracts import load_adapter
from inverter_interface_checks.process import run_worker


BASE_CHECKS = (
    "return_code", "Instance/guards", "instance_fields_unchanged",
    "ExternalInputs/guards", "ExternalInputs/unchanged",
    "ExternalOutputs/guards", "ExternalOutputs/unchanged",
    "Parameters/guards", "Parameters/unchanged",
    "IntStates/guards", "IntStates/unchanged",
    "FloatStates/guards", "FloatStates/unchanged",
    "DoubleStates/guards", "DoubleStates/unchanged",
)


class WorkerPackets(unittest.TestCase):
    def setUp(self):
        self.adapter = load_adapter("ieee-cigre-1.1")[0]
        self.metadata = dict.fromkeys(abi.MODEL_TEXT)
        self.metadata.update(ModelName="PassiveFixture", ModelVersion="1", interface_version=[1, 1, 0, 0],
                             sample_time=0.001, mode=1, inputs=[], outputs=[], parameters=[],
                             states={"NumIntStates": 0, "NumFloatStates": 0, "NumDoubleStates": 0})

    def call(self, kind="valid", returned=0, extra=()):
        channel = None if kind == "null_instance" else "error" if returned == 2 else "general" if returned == 1 else None
        return {"kind": kind, "return_code": returned, "diagnostic_channel": channel,
                "error_message": "Rejected" if channel == "error" else None,
                "general_message": "Continue" if channel == "general" else None,
                "error_pointer_present": None if kind == "null_instance" else channel == "error",
                "general_pointer_present": None if kind == "null_instance" else channel == "general",
                "parameter_mutations": [], "checks": [{"check": name, "ok": True} for name in (*BASE_CHECKS, *extra)]}

    def case_packet(self, calls=None):
        return {"ok": True, "calls": calls if calls is not None else [self.call()],
                "metadata_unchanged": True, "recheck_policy": "same-instance"}

    def metadata_packet(self):
        return {"ok": True, "metadata": self.metadata, "native_layout": abi.native_layout(),
                "native_layout_scope": "ctypes declarations; not producer-library attestation",
                "host_layouts": abi.host_layouts(self.metadata)}

    def request(self, action="case", kind="valid"):
        return {"action": action, "metadata": self.metadata, "adapter": self.adapter,
                "case": {"id": "passive", "kind": kind}}

    def emit(self, packet, action="case", kind="valid"):
        original = subprocess.Popen
        script = "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')"

        def passive_process(command, **options):
            return original([sys.executable, "-I", "-S", "-B", "-c", script, command[-1], json.dumps(packet)], **options)

        with patch("inverter_interface_checks.process.subprocess.Popen", passive_process):
            return run_worker(self.request(action, kind), 2.0)

    def rejected(self, packet, action="case", kind="valid"):
        result = self.emit(packet, action, kind)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["execution"], "invalid_worker_result")
        return result

    def test_complete_default_call_and_metadata_are_preserved(self):
        for packet, action in ((self.case_packet(), "case"), (self.metadata_packet(), "metadata")):
            with self.subTest(action=action):
                result = self.emit(packet, action)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["execution"], "completed")
                for key, value in packet.items():
                    self.assertEqual(result[key], value)

    def test_success_without_requested_calls_is_rejected(self):
        for packet in ({"ok": True}, self.case_packet([]), self.case_packet([self.call(), self.call()])):
            with self.subTest(packet=packet):
                self.rejected(packet)

    def test_success_requires_each_declared_buffer_and_instance_observation(self):
        for name in BASE_CHECKS:
            with self.subTest(check=name):
                packet = self.case_packet()
                packet["calls"][0]["checks"] = [check for check in packet["calls"][0]["checks"] if check["check"] != name]
                self.rejected(packet)

    def test_duplicate_false_or_nonboolean_checks_cannot_support_success(self):
        for change in ("duplicate", "false", "integer"):
            with self.subTest(change=change):
                packet = self.case_packet()
                checks = packet["calls"][0]["checks"]
                if change == "duplicate":
                    checks.append(copy.deepcopy(checks[0]))
                else:
                    checks[0]["ok"] = False if change == "false" else 1
                self.rejected(packet)

    def test_missing_return_and_diagnostic_fields_are_not_inferred(self):
        for key in ("return_code", "diagnostic_channel", "error_pointer_present", "general_message", "parameter_mutations"):
            with self.subTest(key=key):
                packet = self.case_packet()
                del packet["calls"][0][key]
                self.rejected(packet)

    def test_metadata_recheck_and_selected_call_kind_are_required(self):
        for key in ("metadata_unchanged", "recheck_policy"):
            with self.subTest(key=key):
                packet = self.case_packet()
                del packet[key]
                self.rejected(packet)
        self.rejected(self.case_packet([self.call("null_instance", 2)]))
        packet = self.case_packet()
        packet["calls"][0]["return_code"] = True
        self.rejected(packet)

    def test_same_instance_recheck_is_complete_and_cannot_be_omitted_or_reordered(self):
        calls = [self.call("invalid", 2, ("error_message",)), self.call()]
        complete = self.case_packet(calls)
        self.assertTrue(self.emit(complete, kind="invalid")["ok"])
        self.rejected(self.case_packet(calls[:1]), kind="invalid")
        self.rejected(self.case_packet(calls[::-1]), kind="invalid")
        self.adapter["recheck_policy"] = "none"
        one = self.case_packet(calls[:1])
        one["recheck_policy"] = "none"
        self.assertTrue(self.emit(one, kind="invalid")["ok"])

    def test_nonfatal_and_error_messages_require_observed_active_text(self):
        complete = self.case_packet([self.call(returned=1, extra=("general_message",))])
        self.assertTrue(self.emit(complete)["ok"])
        complete["calls"][0]["general_message"] = None
        self.rejected(complete)
        error = self.case_packet([self.call("null_parameters", 2, ("error_message",))])
        self.assertTrue(self.emit(error, kind="null_parameters")["ok"])
        error["calls"][0]["error_message"] = " "
        self.rejected(error, kind="null_parameters")

    def test_inactive_or_inconsistent_diagnostic_evidence_is_rejected(self):
        for key, value in (("error_message", "stale"), ("diagnostic_channel", "error"), ("error_pointer_present", 0)):
            with self.subTest(key=key):
                packet = self.case_packet()
                packet["calls"][0][key] = value
                self.rejected(packet)

    def test_partial_or_mismatched_metadata_and_layouts_are_rejected(self):
        for key in ("metadata", "host_layouts", "native_layout", "native_layout_scope"):
            with self.subTest(key=key):
                packet = self.metadata_packet()
                del packet[key]
                self.rejected(packet, "metadata")
        packet = self.metadata_packet()
        packet["host_layouts"] = {}
        self.rejected(packet, "metadata")
        packet = self.metadata_packet()
        packet["metadata"] = dict(self.metadata, states={})
        self.rejected(packet, "metadata")

    def test_unbounded_port_width_is_refused_before_layout_construction(self):
        packet = self.metadata_packet()
        packet["metadata"] = copy.deepcopy(self.metadata)
        packet["metadata"]["inputs"] = [{"name": "oversized", "datatype": 9, "width": 10**9, "description": None, "unit": None}]
        with patch.object(packets.abi, "host_layouts", side_effect=AssertionError("unsafe layout construction")) as layouts:
            self.rejected(packet, "metadata")
            layouts.assert_not_called()

    def test_numeric_normalization_requires_its_selected_value_checks(self):
        self.adapter["parameter_mutation"] = "allow-normalization"
        self.metadata["parameters"] = [{"name": "value", "datatype": 9, "description": None, "unit": None,
                                        "group": None, "fixed": False, "fixed_value": 0,
                                        "default": 0.5, "minimum": 0.0, "maximum": 1.0}]
        call = self.call(extra=("Parameters/protected_bytes_unchanged", "parameter[0]/normalized_finite", "parameter[0]/normalized_bounds"))
        call["checks"] = [check for check in call["checks"] if check["check"] != "Parameters/unchanged"]
        packet = self.case_packet([call])
        self.assertTrue(self.emit(packet)["ok"])
        for label in ("parameter[0]/normalized_finite", "parameter[0]/normalized_bounds", "Parameters/protected_bytes_unchanged"):
            with self.subTest(label=label):
                incomplete = copy.deepcopy(packet)
                incomplete["calls"][0]["checks"] = [check for check in call["checks"] if check["check"] != label]
                self.rejected(incomplete)

    def test_string_pointee_guards_and_bytes_cannot_be_omitted(self):
        self.metadata["parameters"] = [{"name": "text", "datatype": 10, "description": None, "unit": None,
                                        "group": None, "fixed": False, "fixed_value": 0, "default": "fixture"}]
        packet = self.case_packet([self.call(extra=("parameter_string[0]/guards", "parameter_string[0]/unchanged"))])
        self.assertTrue(self.emit(packet)["ok"])
        for label in ("parameter_string[0]/guards", "parameter_string[0]/unchanged"):
            with self.subTest(label=label):
                incomplete = copy.deepcopy(packet)
                incomplete["calls"][0]["checks"] = [check for check in packet["calls"][0]["checks"] if check["check"] != label]
                self.rejected(incomplete)

    def test_mutations_cannot_contradict_unchanged_parameters_or_selected_policy(self):
        self.metadata["parameters"] = [{"name": "value", "datatype": 9, "description": None, "unit": None,
                                        "group": None, "fixed": False, "fixed_value": 0,
                                        "default": 0.5, "minimum": 0.0, "maximum": 1.0}]
        mutation = {"parameter": "value", "index": 0, "before_hex": struct.pack("d", 0.5).hex(),
                    "after_hex": struct.pack("d", 0.75).hex(), "policy": "allow-normalization"}
        packet = self.case_packet()
        packet["calls"][0]["parameter_mutations"] = [mutation]
        self.rejected(packet)
        self.adapter["parameter_mutation"] = "allow-normalization"
        packet["calls"][0]["checks"] += [{"check": name, "ok": True} for name in (
            "Parameters/protected_bytes_unchanged", "parameter[0]/normalized_finite", "parameter[0]/normalized_bounds")]
        self.rejected(packet)
        packet = self.case_packet([self.call("null_parameters", 2)])
        packet["calls"][0]["parameter_mutations"] = [mutation]
        self.rejected(packet, kind="null_parameters")

    def test_normalization_observations_have_consistent_subject_bytes_and_values(self):
        self.adapter["parameter_mutation"] = "allow-normalization"
        self.metadata["parameters"] = [{"name": "value", "datatype": 9, "description": None, "unit": None,
                                        "group": None, "fixed": False, "fixed_value": 0,
                                        "default": 0.5, "minimum": 0.0, "maximum": 1.0}]
        call = self.call(extra=("Parameters/protected_bytes_unchanged", "parameter[0]/normalized_finite",
                                "parameter[0]/normalized_bounds"))
        call["checks"] = [check for check in call["checks"] if check["check"] != "Parameters/unchanged"]
        call["parameter_mutations"] = [{"parameter": "value", "index": 0, "before_hex": struct.pack("d", 0.5).hex(),
                                        "after_hex": struct.pack("d", 0.75).hex(), "policy": "allow-normalization"}]
        packet = self.case_packet([call])
        self.assertTrue(self.emit(packet)["ok"])
        changes = (("index", True), ("index", 1), ("parameter", "other"), ("policy", "forbid"),
                   ("after_hex", "00"), ("after_hex", "z" * 16),
                   ("after_hex", struct.pack("d", 0.5).hex()), ("after_hex", struct.pack("d", 1.5).hex()),
                   ("after_hex", struct.pack("d", float("nan")).hex()))
        for key, value in changes:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(packet)
                changed["calls"][0]["parameter_mutations"][0][key] = value
                self.rejected(changed)
        duplicate = copy.deepcopy(packet)
        duplicate["calls"][0]["parameter_mutations"] *= 2
        self.rejected(duplicate)

    def test_existing_failed_native_observations_are_retained(self):
        packet = self.case_packet()
        packet["ok"] = False
        packet["metadata_unchanged"] = False
        packet["calls"][0]["checks"][0]["ok"] = False
        result = self.emit(packet)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution"], "completed")
        self.assertEqual(result["calls"], packet["calls"])
        self.assertFalse(result["metadata_unchanged"])

    def test_incomplete_case_packets_cannot_produce_a_passing_report(self):
        original = subprocess.Popen
        meta = json.dumps(self.metadata_packet())
        script = """from pathlib import Path
import json, sys
request = json.loads(Path(sys.argv[1]).read_text())
result = json.loads(sys.argv[3]) if request["action"] == "metadata" else {"ok": True}
Path(sys.argv[2]).write_text(json.dumps(result))
"""

        def passive_process(command, **options):
            return original([sys.executable, "-I", "-S", "-B", "-c", script, command[-2], command[-1], meta], **options)

        with tempfile.TemporaryDirectory(prefix="checker-packet-cli-") as directory:
            library = Path(directory) / "never-loaded.bin"
            library.write_bytes(b"Passive placeholder; no native code")
            args = argparse.Namespace(library=library, adapter="ieee-cigre-1.1", timeout=2.0, total_timeout=5.0,
                                      max_cases=10, source=[], compiler=None, build_receipt=None, abi_probe=None)
            with patch("inverter_interface_checks.process.subprocess.Popen", passive_process):
                report = cli.inspect(args)
        self.assertFalse(report["summary"]["ok"])
        self.assertEqual(report["summary"]["cases_failed"], 3)
        self.assertEqual(report["summary"]["checks_executed"], 0)
        self.assertTrue(all(case["execution"] == "invalid_worker_result" for case in report["cases"]))


if __name__ == "__main__":
    unittest.main()
