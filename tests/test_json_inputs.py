"""Passive input and worker-packet controls; no native library is loaded."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inverter_interface_checks import cli
from inverter_interface_checks.contracts import load_adapter
from inverter_interface_checks.process import run_worker


class JSONInputs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="checker-json-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.library = self.directory / "passive-library.bin"
        self.library.write_bytes(b"source-free placeholder; never loaded")
        self.library_sha = hashlib.sha256(self.library.read_bytes()).hexdigest()

    def write(self, name, text):
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def arguments(self, **changes):
        values = dict(library=self.library, adapter="ieee-cigre-1.1", timeout=2.0,
                      total_timeout=2.0, max_cases=3, source=[], compiler=None,
                      build_receipt=None, abi_probe=None)
        values.update(changes)
        return argparse.Namespace(**values)

    def build_receipt(self):
        return {"schema": "inverter-fixture-build/1", "fixture": "passive",
                "library": {"sha256": self.library_sha}}

    def probe_receipt(self):
        return {"schema": "inverter-native-abi-probe-build/1",
                "scope": "host-header-software-probe", "producer_library_attestation": False,
                "probe_exit_code": 0, "sources": cli.PROBE_SOURCES,
                "host": {"os": platform.system(), "architecture": platform.machine()},
                "observation": {}}

    def assert_before_worker(self, error, **changes):
        with patch.object(cli, "run_worker", return_value={"ok": False, "execution": "passive"}) as worker:
            with self.assertRaisesRegex(ValueError, error):
                cli.inspect(self.arguments(**changes))
            worker.assert_not_called()

    def test_duplicate_adapter_fields_are_rejected_at_every_depth(self):
        adapter = load_adapter("ieee-cigre-1.1")[0]
        text = json.dumps(adapter)
        for policy in ('"bounds": "skip", "bounds": "inclusive"',
                       '"bounds": "inclusive", "bounds": "inclusive"'):
            with self.subTest(policy=policy):
                path = self.write("adapter.json", text.replace('"bounds": "inclusive"', policy))
                self.assert_before_worker("duplicate JSON", adapter=str(path))
        adapter["expected_parameters"] = [{"name": "fixture", "datatype": 9}]
        nested = json.dumps(adapter).replace('"datatype": 9', '"datatype": 8, "datatype": 9')
        path = self.write("nested-adapter.json", nested)
        self.assert_before_worker("duplicate JSON", adapter=str(path))

    def test_ordinary_adapters_preserve_original_bytes(self):
        for name in ("ieee-cigre-1.1", "openibr-1.1"):
            with self.subTest(name=name):
                adapter, path, data = load_adapter(name)
                self.assertEqual(data, path.read_bytes())
                self.assertEqual(adapter["bounds"], "inclusive")

    def test_duplicate_build_identity_is_rejected_before_worker(self):
        text = json.dumps(self.build_receipt())
        key = '"sha256": "' + self.library_sha + '"'
        for first in ("0" * 64, self.library_sha):
            with self.subTest(first=first):
                duplicate = '"sha256": "' + first + '", ' + key
                path = self.write("build.json", text.replace(key, duplicate))
                self.assert_before_worker("duplicate JSON", build_receipt=path)

    def test_duplicate_probe_status_is_rejected_before_comparison_or_worker(self):
        text = json.dumps(self.probe_receipt()).replace(
            '"probe_exit_code": 0', '"probe_exit_code": 7, "probe_exit_code": 0')
        path = self.write("probe.json", text)
        with patch.object(cli, "compare_native_probe") as compare:
            self.assert_before_worker("duplicate JSON", abi_probe=path)
            compare.assert_not_called()

    def test_nonfinite_receipts_are_rejected_before_worker(self):
        for constant in ("NaN", "Infinity", "-Infinity", "1e999"):
            for field, receipt in (("build_receipt", self.build_receipt()),
                                   ("abi_probe", self.probe_receipt())):
                with self.subTest(constant=constant, field=field):
                    receipt["passive_measurement"] = 1.25
                    text = json.dumps(receipt).replace('"passive_measurement": 1.25',
                                                       '"passive_measurement": ' + constant)
                    path = self.write("nonfinite.json", text)
                    with patch.object(cli, "compare_native_probe", return_value={"matches": True}):
                        self.assert_before_worker("nonfinite JSON", **{field: path})

    def test_excessive_nesting_is_rejected_before_worker(self):
        nested = "[" * 10000 + "0" + "]" * 10000
        for field, receipt in (("build_receipt", self.build_receipt()),
                               ("abi_probe", self.probe_receipt())):
            with self.subTest(field=field):
                text = json.dumps(receipt)[:-1] + ', "nested":' + nested + '}'
                path = self.write("nested-receipt.json", text)
                self.assert_before_worker("JSON nesting", **{field: path})

    def test_repeated_names_in_distinct_objects_are_allowed(self):
        receipt = self.build_receipt()
        receipt["sources"] = [{"name": "first", "sha256": "a" * 64},
                              {"name": "second", "sha256": "b" * 64}]
        receipt["passive_measurement"] = 1.25
        path = self.write("ordinary.json", json.dumps(receipt))
        with patch.object(cli, "run_worker", return_value={"ok": False, "execution": "passive"}) as worker:
            report = cli.inspect(self.arguments(build_receipt=path))
        worker.assert_called_once()
        self.assertEqual(report["identity"]["build_receipt"], receipt)
        self.assertEqual(report["identity"]["build_receipt_sha256"],
                         hashlib.sha256(path.read_bytes()).hexdigest())

    def test_build_hash_covers_captured_bytes_when_file_changes_after_read(self):
        first = json.dumps(self.build_receipt()).encode("utf-8")
        second = first.replace(b'"passive"', b'"changed"')
        path = self.directory / "changing.json"
        path.write_bytes(first)
        original_read = Path.read_bytes

        def read_then_change(candidate):
            data = original_read(candidate)
            if candidate == path:
                candidate.write_bytes(second)
            return data

        with patch.object(Path, "read_bytes", read_then_change), patch.object(
                cli, "run_worker", return_value={"ok": False, "execution": "passive"}):
            report = cli.inspect(self.arguments(build_receipt=path))
        self.assertEqual(report["identity"]["build_receipt"], json.loads(first))
        self.assertEqual(report["identity"]["build_receipt_sha256"], hashlib.sha256(first).hexdigest())
        self.assertNotEqual(report["identity"]["build_receipt_sha256"], hashlib.sha256(second).hexdigest())

    def emit_worker_packet(self, payload):
        popen = subprocess.Popen
        script = "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')"

        def passive_child(command, **options):
            return popen([sys.executable, "-I", "-S", "-B", "-c", script, command[-1], payload], **options)

        with patch("inverter_interface_checks.process.subprocess.Popen", passive_child):
            return run_worker({"purpose": "passive JSON packet control"}, 2.0)

    def test_duplicate_worker_fields_cannot_replace_a_failure(self):
        for payload in ('{"ok":false,"ok":true}',
                        '{"ok":true,"detail":{"code":1,"code":2}}'):
            with self.subTest(payload=payload):
                result = self.emit_worker_packet(payload)
                self.assertFalse(result["ok"])
                self.assertEqual(result["execution"], "invalid_worker_result")

    def test_nonfinite_worker_fields_are_rejected(self):
        for constant in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(constant=constant):
                result = self.emit_worker_packet('{"ok":true,"measurement":' + constant + '}')
                self.assertFalse(result["ok"])
                self.assertEqual(result["execution"], "invalid_worker_result")

    def test_excessive_worker_nesting_returns_a_failed_result(self):
        payload = '{"ok":true,"nested":' + "[" * 10000 + "0" + "]" * 10000 + '}'
        result = self.emit_worker_packet(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution"], "invalid_worker_result")

    def test_ordinary_worker_packet_is_preserved(self):
        result = self.emit_worker_packet('{"ok":true,"detail":"passive","measurement":1.25}')
        self.assertTrue(result["ok"])
        self.assertEqual(result["detail"], "passive")
        self.assertEqual(result["measurement"], 1.25)
        self.assertEqual(result["execution"], "completed")
