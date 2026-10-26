"""Native witnesses for guard boundaries, message reuse and raw fixed flags."""

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inverter_interface_checks.cli import inspect
from inverter_interface_checks.contracts import load_adapter
from inverter_interface_checks.process import run_worker, sha256
from tools.build_fixture import MODES, compile_fixture


SUFFIX = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"
INTEGRATION_MODES = {
    "instance-front-guard": 47,
    "shared-diagnostic": 48,
    "negative-fixed-value": 49,
    "fixed-flag-mutation": 50,
}


class NativeIntegrationControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="interface-integration-controls-")
        cls.directory = Path(cls.temporary.name)
        cls.libraries = {}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def library(self, mode):
        if mode not in self.libraries:
            output = self.directory / (mode + SUFFIX)
            with patch.dict(MODES, INTEGRATION_MODES):
                compile_fixture(output, mode, os.environ.get("CC"))
            self.libraries[mode] = output
        return self.libraries[mode]

    def probe(self, mode, case=None, adapter=None):
        library = self.library(mode)
        adapter = adapter or load_adapter("ieee-cigre-1.1")[0]
        request = {"library": str(library), "library_sha256": sha256(library),
                   "adapter": adapter, "timeout": 2.0, "action": "metadata"}
        metadata = run_worker(request, 2.0)
        if case is None or not metadata["ok"]:
            return metadata
        request.update(action="case", metadata=metadata["metadata"], case=case)
        return run_worker(request, 2.0)

    def test_default_fixture_retains_complete_reference_checks(self):
        args = argparse.Namespace(library=self.library("good"), adapter="ieee-cigre-1.1",
                                  timeout=2.0, total_timeout=60.0, max_cases=256,
                                  source=[], compiler=None, build_receipt=None)
        report = inspect(args)
        self.assertTrue(report["summary"]["ok"], report["summary"])
        self.assertEqual(report["summary"]["cases_executed"], 24)
        self.assertEqual(report["summary"]["checks_executed"], 642)
        self.assertEqual(report["summary"]["checks_failed"], 0)

    def test_native_byte_before_instance_is_detected(self):
        result = self.probe("instance-front-guard", {"id": "defaults", "kind": "valid"})
        self.assertEqual(result["execution"], "completed")
        self.assertFalse(result["ok"])
        self.assertTrue(result["metadata_unchanged"])
        failed = [check["check"] for call in result["calls"]
                  for check in call["checks"] if not check["ok"]]
        self.assertEqual(failed, ["Instance/guards"])

    def test_first_diagnostic_survives_same_storage_retry(self):
        case = {"id": "nan", "kind": "invalid", "index": 0, "value": "nan"}
        result = self.probe("shared-diagnostic", case)
        self.assertTrue(result["ok"], result)
        first, retry = result["calls"]
        self.assertEqual([first["return_code"], retry["return_code"]], [2, 1])
        self.assertEqual(first["error_message"], "First rejection in shared storage")
        self.assertEqual(retry["general_message"], "Replacement text in shared storage")
        self.assertEqual(first["diagnostic_channel"], "error")
        self.assertEqual(retry["diagnostic_channel"], "general")
        addresses = [line.split(":", 1)[1] for line in result["native_log"].splitlines()
                     if line.startswith("diagnostic_storage:")]
        self.assertEqual(len(addresses), 2)
        self.assertEqual(addresses[0], addresses[1])

    def test_negative_nonzero_flag_uses_declared_fixed_policy(self):
        metadata = self.probe("negative-fixed-value")
        self.assertTrue(metadata["ok"], metadata)
        parameter = metadata["metadata"]["parameters"][2]
        self.assertEqual(parameter["fixed_value"], -1)
        self.assertTrue(parameter["fixed"])
        defaults = {"id": "defaults", "kind": "valid"}
        self.assertTrue(self.probe("negative-fixed-value", defaults)["ok"])
        adapter = load_adapter("ieee-cigre-1.1")[0]
        adapter["fixed_value_policy"] = "zero-or-one"
        rejected = self.probe("negative-fixed-value", adapter=adapter)
        self.assertFalse(rejected["ok"])
        self.assertIn("invalid FixedValue", rejected["detail"])

    def test_raw_fixed_flag_mutation_cannot_hide_behind_boolean(self):
        metadata = self.probe("fixed-flag-mutation")
        self.assertTrue(metadata["ok"], metadata)
        parameter = metadata["metadata"]["parameters"][2]
        self.assertEqual(parameter["fixed_value"], 1)
        self.assertTrue(parameter["fixed"])
        result = self.probe("fixed-flag-mutation", {"id": "defaults", "kind": "valid"})
        self.assertEqual(result["execution"], "completed")
        self.assertFalse(result["ok"])
        self.assertFalse(result["metadata_unchanged"])
        self.assertTrue(all(check["ok"] for call in result["calls"] for check in call["checks"]))
        observed = {key: int(value) for key, value in
                    (line.split(":", 1) for line in result["native_log"].splitlines())}
        self.assertEqual(observed, {"fixed_value_before": 1, "fixed_value_after": 2})
        self.assertTrue(all(bool(value) for value in observed.values()))


if __name__ == "__main__":
    unittest.main()
