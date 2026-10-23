"""Explicit adapter policies; these checks do not certify a model."""

import json
import math
import struct
from pathlib import Path

EXPORTS = (
    "Model_GetInfo", "Model_FirstCall", "Model_PrintInfo", "Model_CheckParameters",
    "Model_Initialize", "Model_Outputs", "Model_Iterate", "Model_Terminate",
)
ADAPTER_KEYS = {
    "schema", "id", "abi", "calling_convention", "parameter_layout", "bounds",
    "valid_returns", "invalid_return", "invalid_message", "clear_error_on_success",
    "null_instance_return", "null_parameters_return", "null_parameters_message",
    "expected_model_name", "expected_parameters",
    "parameter_check_setup",
    "char_signedness",
}


def load_adapter(value):
    path = Path(value)
    if value in ("ieee-cigre-1.1", "openibr-1.1"):
        path = Path(__file__).parent / "adapters" / f"{value}.json"
    data = path.read_bytes()
    if len(data) > 65536:
        raise ValueError("adapter exceeds 64 KiB")
    adapter = json.loads(data)
    if not isinstance(adapter, dict) or set(adapter) - ADAPTER_KEYS:
        raise ValueError("adapter has unknown fields")
    expected = {
        "schema": "inverter-interface-adapter/1", "abi": "ieee-cigre-1.1-native-c",
        "calling_convention": "cdecl", "parameter_layout": "native-struct-metadata-order",
        "bounds": "inclusive", "invalid_return": 2,
        "null_instance_return": 2, "null_parameters_return": 2,
        "parameter_check_setup": "none",
    }
    if any(adapter.get(key) != value for key, value in expected.items()):
        raise ValueError("unsupported adapter ABI or parameter contract")
    if not isinstance(adapter.get("id"), str) or not adapter["id"]:
        raise ValueError("adapter id must be nonempty")
    if adapter.get("valid_returns") not in ([0], [0, 1]):
        raise ValueError("valid_returns must be [0] or [0, 1]")
    for key in ("invalid_message", "clear_error_on_success", "null_parameters_message"):
        if not isinstance(adapter.get(key), bool):
            raise ValueError(f"{key} must be boolean")
    if adapter.get("char_signedness") not in ("signed", "unsigned", "unsupported"):
        raise ValueError("char_signedness must be signed, unsigned or unsupported")
    parameters = adapter.get("expected_parameters")
    if parameters is not None and (
        not isinstance(parameters, list) or any(
            not isinstance(row, dict) or set(row) != {"name", "datatype"}
            or not isinstance(row["name"], str) or not row["name"]
            or type(row["datatype"]) is not int or row["datatype"] not in range(1, 11)
            for row in parameters
        )
    ):
        raise ValueError("invalid expected_parameters")
    return adapter, path, data


def check_expectations(metadata, adapter):
    expected = adapter.get("expected_model_name")
    if expected is not None and metadata["ModelName"] != expected:
        raise ValueError("model name differs from adapter")
    parameters = adapter.get("expected_parameters")
    actual = [{"name": row["name"], "datatype": row["datatype"]} for row in metadata["parameters"]]
    if parameters is not None and parameters != actual:
        raise ValueError("parameter names, order or datatypes differ from adapter")


def adjacent_float32(value, positive):
    if value == 0:
        return struct.unpack("!f", struct.pack("!I", 1 if positive else 0x80000001))[0]
    bits = struct.unpack("!I", struct.pack("!f", value))[0]
    bits += 1 if (value > 0) == positive else -1
    return struct.unpack("!f", struct.pack("!I", bits))[0]


def plan_cases(metadata):
    cases = [{"id": "defaults", "kind": "valid"}]
    skipped = []
    for index, row in enumerate(metadata["parameters"]):
        datatype, name = row["datatype"], row["name"]
        if row["fixed"] or datatype == 10:
            skipped.append({"parameter": name, "reason": "fixed" if row["fixed"] else "string"})
            continue
        low, high = row["minimum"], row["maximum"]
        values = [("minimum", low, "valid"), ("maximum", high, "valid")]
        if datatype in (8, 9):
            before = adjacent_float32(low, False) if datatype == 8 else math.nextafter(low, -math.inf)
            after = adjacent_float32(high, True) if datatype == 8 else math.nextafter(high, math.inf)
            values += [("below_minimum", before, "invalid"), ("above_maximum", after, "invalid"),
                       ("nan", "nan", "invalid"), ("positive_infinity", "inf", "invalid"),
                       ("negative_infinity", "-inf", "invalid")]
        else:
            limits = {1: (0, 255), 2: (-128, 127), 3: (0, 255),
                      4: (-32768, 32767), 5: (0, 65535),
                      6: (-(2**31), 2**31 - 1), 7: (0, 2**32 - 1)}
            if datatype == 1 and row["char_signedness"] == "signed":
                limits[1] = (-128, 127)
            for label, value in (("below_minimum", low - 1), ("above_maximum", high + 1)):
                if limits[datatype][0] <= value <= limits[datatype][1]:
                    values.append((label, value, "invalid"))
                else:
                    skipped.append({"parameter": name, "reason": f"{label} is unrepresentable"})
        for label, value, kind in values:
            if isinstance(value, float) and not math.isfinite(value):
                value = "inf" if value > 0 else "-inf"
            cases.append({"id": f"parameter[{index}]/{label}", "parameter": name,
                          "index": index, "value": value, "kind": kind})
    cases.extend([{"id": "null_instance", "kind": "null_instance"},
                  {"id": "null_parameters", "kind": "null_parameters"}])
    return cases, skipped
