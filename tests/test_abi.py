"""Native host-header probes and independent, deliberate representation mismatches."""

import copy
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from inverter_interface_checks import abi
from tools.probe_abi import compile_probe, run_probe
from inverter_interface_checks.cli import inspect
from tools.build_fixture import compile_fixture
from inverter_interface_checks.process import sha256


class NativeABIProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="software-abi-probe-")
        cls.directory = Path(cls.temporary.name)
        cls.compiler = os.environ.get("CC")
        cls.receipts = {}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def probe(self, mode="ordinary", extra_flags=()):
        if mode not in self.receipts:
            path = self.directory / (mode + (".exe" if os.name == "nt" else ""))
            receipt = compile_probe(path, self.compiler, packed=mode == "packed", extra_flags=extra_flags)
            self.receipts[mode] = run_probe(path, receipt)
        return self.receipts[mode]

    def test_ordinary_complete_probe_matches(self):
        receipt = self.probe()
        self.assertTrue(receipt["comparison"]["matches"], receipt["comparison"])
        native = receipt["observation"]
        expected = {**abi.native_layout(), **abi.mixed_probe_layouts()}
        self.assertEqual(set(native["aggregates"]), set(expected))
        for name, layout in expected.items():
            self.assertEqual(native["aggregates"][name]["fields"], layout["fields"])
        self.assertEqual(native["datatype_ids"], list(range(1, 11)))
        self.assertEqual(native["endianness"], sys.byteorder)
        self.assertFalse(receipt["producer_library_attestation"])
        self.assertFalse(receipt["observation"]["producer_library_attestation"])
        self.assertEqual(receipt["compile_timeout_seconds"], 90)
        self.assertEqual(receipt["compiler_identity_timeout_seconds"], 30)
        self.assertEqual(receipt["probe_timeout_seconds"], 5)
        self.assertEqual(len(receipt["sources"]), 3)
        self.assertEqual(receipt["sources"], abi.PROBE_SOURCES)
        self.assertTrue(receipt["flags"])

    def test_pinned_probe_sources_match_checkout(self):
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(abi.PROBE_SOURCES, {name: sha256(root / name) for name in abi.PROBE_SOURCES})

    def test_packed_profile_rejected_even_when_signal_size_matches(self):
        ordinary = self.probe()["observation"]["aggregates"]
        receipt = self.probe("packed")
        packed = receipt["observation"]["aggregates"]
        self.assertFalse(receipt["comparison"]["matches"])
        self.assertEqual(packed["Signal"]["size"], ordinary["Signal"]["size"])
        self.assertNotEqual(packed["Signal"]["alignment"], ordinary["Signal"]["alignment"])
        self.assertEqual(packed["ModelInfo"]["size"], 141)
        self.assertEqual(packed["Instance"]["size"], 73)
        paths = {row["path"] for row in receipt["comparison"]["mismatches"]}
        self.assertIn("aggregates/Signal/alignment", paths)
        self.assertIn("aggregates/Instance/fields", paths)

    def test_offset_drift_rejected_without_size_change(self):
        native = copy.deepcopy(self.probe()["observation"])
        original_size = native["aggregates"]["ModelInfo"]["size"]
        native["aggregates"]["ModelInfo"]["fields"]["ParametersInfo"]["offset"] += 8
        result = abi.compare_native_probe(native)
        self.assertFalse(result["matches"])
        self.assertEqual(native["aggregates"]["ModelInfo"]["size"], original_size)
        self.assertIn("aggregates/ModelInfo/fields", {row["path"] for row in result["mismatches"]})

    def test_union_member_width_drift_rejected_without_union_size_change(self):
        native = copy.deepcopy(self.probe()["observation"])
        native["aggregates"]["DefaultValue"]["fields"]["Uint8_Val"]["size"] = 4
        result = abi.compare_native_probe(native)
        self.assertFalse(result["matches"])
        self.assertIn("aggregates/DefaultValue/fields", {row["path"] for row in result["mismatches"]})

    def test_scalar_signedness_endianness_and_missing_field_rejected(self):
        mutations = (
            (lambda value: value["scalars"]["int8_t"].update(signedness="unsigned"),
             "scalars/int8_t/signedness"),
            (lambda value: value.update(endianness="big" if sys.byteorder == "little" else "little"),
             "endianness"),
            (lambda value: value["aggregates"]["MinMaxValue"]["fields"].pop("Real64_Val"),
             "aggregates/MinMaxValue/fields"),
            (lambda value: value["datatype_ids"].__setitem__(8, 99), "datatype_ids"),
        )
        for mutate, path in mutations:
            with self.subTest(path=path):
                native = copy.deepcopy(self.probe()["observation"])
                mutate(native)
                result = abi.compare_native_probe(native)
                self.assertFalse(result["matches"])
                self.assertIn(path, {row["path"] for row in result["mismatches"]})

    def test_char_signedness_remains_explicit_adapter_policy(self):
        native = self.probe()["observation"]
        actual = native["scalars"]["char"]["signedness"]
        opposite = "unsigned" if actual == "signed" else "signed"
        self.assertTrue(abi.compare_native_probe(native, actual)["matches"])
        self.assertFalse(abi.compare_native_probe(native, opposite)["matches"])

    def test_short_enums_do_not_shrink_openibr_int_fields(self):
        ordinary = self.probe()
        driver = Path(ordinary["compiler"]["executable"]).stem.lower()
        if driver == "cl":
            self.skipTest("MSVC cl does not provide GCC short-enum flag")
        flags = ("/clang:-fshort-enums",) if driver == "clang-cl" else ("-fshort-enums",)
        receipt = self.probe("short-enums", flags)
        native = receipt["observation"]
        self.assertTrue(receipt["comparison"]["matches"], receipt["comparison"])
        self.assertEqual(native["aggregates"]["Signal"]["fields"]["DataType"]["size"], 4)
        self.assertEqual(native["aggregates"]["Parameter"]["fields"]["DataType"]["size"], 4)
        self.assertEqual(native["aggregates"], ordinary["observation"]["aggregates"])

    def test_probe_cannot_claim_producer_library_attestation(self):
        native = copy.deepcopy(self.probe()["observation"])
        native["producer_library_attestation"] = True
        self.assertFalse(abi.compare_native_probe(native)["matches"])

    def test_enum_observations_are_required_but_widths_are_descriptive(self):
        for enums in (None, {}, {"DataType": {"size": True, "alignment": 1, "signedness": "signed"}},
                      {"DataType": {"size": 1, "alignment": 0, "signedness": "unsigned"}}):
            with self.subTest(enums=enums):
                native = copy.deepcopy(self.probe()["observation"])
                native["enums"] = enums
                result = abi.compare_native_probe(native)
                self.assertFalse(result["matches"])
                self.assertTrue(any(row["path"].startswith("enums/") for row in result["mismatches"]))

    def test_executable_identity_change_rejected_before_probe_execution(self):
        output = self.directory / ("identity.exe" if os.name == "nt" else "identity")
        receipt = compile_probe(output, self.compiler)
        receipt["executable"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity changed before execution"):
            run_probe(output, receipt)

    def test_receipt_round_trips_as_strict_json(self):
        receipt = self.probe()
        self.assertEqual(json.loads(json.dumps(receipt, allow_nan=False)), receipt)

    def test_invalid_receipt_types_do_not_alias_native_numbers(self):
        for value in (True, 4.0):
            with self.subTest(value=value):
                observation = copy.deepcopy(self.probe()["observation"])
                observation["aggregates"]["Parameter"]["fields"]["DataType"]["size"] = value
                self.assertFalse(abi.compare_native_probe(observation)["matches"])
        for field in ("scalars", "aggregates"):
            observation = copy.deepcopy(self.probe()["observation"])
            observation[field] = []
            with self.assertRaises(ValueError):
                abi.compare_native_probe(observation)

    def test_matching_receipt_attaches_and_mismatch_refuses_before_load(self):
        suffix = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"
        library = self.directory / ("receipt-fixture" + suffix)
        compile_fixture(library, compiler=self.compiler)
        path = self.directory / "probe-receipt.json"
        path.write_text(json.dumps(self.probe()), encoding="utf-8")
        args = argparse.Namespace(library=library, adapter="ieee-cigre-1.1", timeout=2.0,
                                  total_timeout=30.0, max_cases=256, source=[], compiler=None,
                                  build_receipt=None, abi_probe=path)
        report = inspect(args)
        self.assertTrue(report["summary"]["ok"])
        self.assertFalse(report["identity"]["abi_probe"]["comparison"]["producer_library_attestation"])
        for label, receipt in (("packed", self.probe("packed")),
                               ("source", {**self.probe(), "sources": {}}),
                               ("host", {**self.probe(), "host": {}}),
                               ("failed", {**self.probe(), "probe_exit_code": 7}),
                               ("float", {**self.probe(), "probe_exit_code": 0.0}),
                               ("bool", {**self.probe(), "probe_exit_code": False}),
                               ("incomplete", {**self.probe(), "probe_exit_code": None}),
                               ("malformed", [])):
            with self.subTest(label=label):
                path.write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaises(ValueError):
                    inspect(args)

    def test_receipt_works_with_python_package_only(self):
        root = Path(__file__).resolve().parent.parent
        package_root = self.directory / "package-only"
        shutil.copytree(root / "inverter_interface_checks", package_root / "inverter_interface_checks",
                        ignore=shutil.ignore_patterns("__pycache__"))
        suffix = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"
        library = self.directory / ("package-fixture" + suffix)
        compile_fixture(library, compiler=self.compiler)
        path = self.directory / "package-probe.json"
        path.write_text(json.dumps(self.probe()), encoding="utf-8")
        environment = {**os.environ, "PYTHONPATH": str(package_root)}
        result = subprocess.run([sys.executable, "-B", "-m", "inverter_interface_checks", "--library",
                                 str(library), "--abi-probe", str(path), "--format", "json"],
                                cwd=package_root, env=environment, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["ok"])
        self.assertFalse((package_root / "third_party").exists())


if __name__ == "__main__":
    unittest.main()
