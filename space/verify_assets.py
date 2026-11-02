"""Verify the retained release bytes and control comparison without native execution."""

import hashlib
import json
import zipfile
from pathlib import Path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify(root):
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["schema"] == "inverter-interface-space/1"
    checker = manifest["checker"]
    assert checker["version"] == "0.2.3"
    assert checker["commit"] == "6b86747cd95bb0d163a8018dd53822b350511706"
    assert checker["wheel"]["sha256"] == "1580a8b1044971c38a846930305946484183333074caa7a14ed693cfbcde59e6"
    assert manifest["native_validation"]["sha256"] == "603872725785265cfe31332f4f9d10162b1f1d511d8149912668a69f68c92f52"

    def asset(identity):
        path = Path(identity["path"])
        assert not path.is_absolute() and ".." not in path.parts
        data = (root / path).read_bytes()
        assert len(data) == identity["bytes"]
        assert sha256(data) == identity["sha256"], path
        return data

    asset(checker["wheel"])
    installation = manifest["installation"]
    assert installation["version"] == "0.2.4"
    assert installation["commit"] == "5ec2849d23b543a91d4effd21bbd24515d2d9114"
    assert installation["wheel"]["sha256"] == "9fb277f98587475d4cef8325432a86c6a1d7579edf397e30eb178feb2423e637"
    asset(installation["wheel"])
    with zipfile.ZipFile(root / installation["wheel"]["path"]) as current:
        metadata = current.read("inverter_interface_checks-0.2.4.dist-info/METADATA").decode("utf-8")
        assert "Version: 0.2.4\n" in metadata
    validation = json.loads(asset(manifest["native_validation"]))
    assert validation["checker_commit"] == checker["commit"]
    assert validation["electrical_initialization_or_stepping"] is False
    results = []
    with zipfile.ZipFile(root / checker["wheel"]["path"]) as wheel:
        for platform in manifest["platforms"]:
            reports = {}
            for kind in ("original", "fixed"):
                report = json.loads(asset(platform[kind]))
                assert report["schema"] == "inverter-interface-report/2"
                assert report["identity"]["build_receipt"]["source_commit"] == manifest["sources"][kind]["commit"]
                assert report["identity"]["library"]["sha256"] == platform[kind]["library_sha256"]
                assert report["identity"]["engine"]["version"] == checker["version"]
                for name, digest in report["identity"]["engine"]["files"].items():
                    assert sha256(wheel.read("inverter_interface_checks/" + name)) == digest, name
                assert report["summary"]["complete"] is True
                assert len(report["cases"]) == 24
                reports[kind] = report
            before, after = reports["original"], reports["fixed"]
            assert before["metadata"]["metadata"] == after["metadata"]["metadata"]
            assert before["identity"]["adapter"] == after["identity"]["adapter"]
            assert before["summary"]["cases_failed"] == 3 and after["summary"]["cases_failed"] == 0
            changed = []
            for original, fixed in zip(before["cases"], after["cases"]):
                assert original["case"] == fixed["case"]
                left = {k: v for k, v in original.items() if k != "elapsed_seconds"}
                right = {k: v for k, v in fixed.items() if k != "elapsed_seconds"}
                if left != right:
                    changed.append(original["case"]["id"])
                    assert original["case"]["value"] == "nan"
                    assert original["calls"][0]["return_code"] == 0
                    assert fixed["calls"][0]["return_code"] == 2
                    assert original["ok"] is False and fixed["ok"] is True
            assert changed == manifest["expected_comparison"]["changed_ids"]
            results.append({"platform": platform["id"], "changed": len(changed), "unchanged": 24 - len(changed)})
    return {"ok": True, "method": "Retained artifact bytes; no native execution",
            "current_checker": installation["version"], "platforms": results}


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parent), indent=2))
