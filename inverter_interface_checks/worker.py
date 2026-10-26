"""The only process that loads or calls a model library."""

import ctypes as c
import json
import math
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inverter_interface_checks import abi
from inverter_interface_checks.contracts import EXPORTS, check_expectations
from inverter_interface_checks.process import LOG_LIMIT, sha256


class GuardedBuffer:
    def __init__(self, body_type):
        container = type("Guarded", (c.Structure,), {
            "_fields_": [("before", c.c_uint64 * 4), ("body", body_type),
                         ("after", c.c_uint64 * 4)]
        })
        self.storage = container()
        self.body = self.storage.body
        self.pointer = c.addressof(self.storage) + container.body.offset
        self.size = c.sizeof(body_type)
        c.memset(c.addressof(self.storage), 0xA5, 32)
        c.memset(c.addressof(self.storage) + container.after.offset, 0x5A, 32)
        self.body_offset = container.body.offset
        self.storage_size = c.sizeof(container)
        self.guards = self.guard_bytes()

    def snapshot(self):
        return c.string_at(self.pointer, self.size)

    def intact(self):
        return self.guard_bytes() == self.guards

    def guard_bytes(self):
        data = c.string_at(c.addressof(self.storage), self.storage_size)
        return data[:self.body_offset] + data[self.body_offset + self.size:]


class Host:
    def __init__(self, metadata):
        self.metadata = metadata
        self.buffers = {}
        self.string_buffers = {}
        for key, field in (("inputs", "ExternalInputs"), ("outputs", "ExternalOutputs"),
                           ("parameters", "Parameters")):
            body_type = abi.host_structure(key, metadata[key], ports=key != "parameters")
            self.buffers[field] = GuardedBuffer(body_type)
        for field, count_name, scalar in (
            ("IntStates", "NumIntStates", c.c_int),
            ("FloatStates", "NumFloatStates", c.c_float),
            ("DoubleStates", "NumDoubleStates", c.c_double),
        ):
            count = metadata["states"][count_name]
            self.buffers[field] = GuardedBuffer(scalar * count)
        self.instance_buffer = GuardedBuffer(abi.Instance)
        self.instance = self.instance_buffer.body
        for field, buffer in self.buffers.items():
            setattr(self.instance, field, buffer.pointer)
        self.instance.SimTool_EMT_RMS_Mode = 1 if metadata["mode"] in (1, 3) else 2
        self.defaults()

    def set_parameter(self, index, value):
        datatype = self.metadata["parameters"][index]["datatype"]
        if datatype == 10:
            encoded = value.encode("utf-8")
            key = f"parameter_string[{index}]"
            if key not in self.string_buffers:
                self.string_buffers[key] = GuardedBuffer(c.c_char * (len(encoded) + 1))
            string = self.string_buffers[key]
            c.memmove(string.pointer, encoded + b"\0", len(encoded) + 1)
            value = string.pointer
        elif datatype == 1:
            value = bytes([value & 255])
        elif isinstance(value, str):
            value = float(value)
        setattr(self.buffers["Parameters"].body, f"field_{index}", value)

    def defaults(self):
        for index, row in enumerate(self.metadata["parameters"]):
            self.set_parameter(index, row["default"])

    def observe_call(self, check, kind, adapter):
        protected = {**self.buffers, **self.string_buffers}
        snapshots = {name: buffer.snapshot() for name, buffer in protected.items()}
        instance_bytes = self.stable_instance_bytes()
        returned = check(None if kind == "null_instance" else c.byref(self.instance))
        passed_instance = kind != "null_instance"
        error_pointer = bool(self.instance.LastErrorMessage) if passed_instance else None
        general_pointer = bool(self.instance.LastGeneralMessage) if passed_instance else None
        channel = "error" if returned == 2 else "general" if returned == 1 else None
        error = (abi.text_at(self.instance.LastErrorMessage)
                 if passed_instance and channel == "error" else None)
        general = (abi.text_at(self.instance.LastGeneralMessage)
                   if passed_instance and channel == "general" else None)
        expected = (adapter[f"{kind}_return"] if kind.startswith("null_")
                    else adapter["invalid_return"] if kind == "invalid" else adapter["valid_returns"])
        checks = [{"check": "return_code", "ok": returned in expected if isinstance(expected, list)
                   else returned == expected}]
        message_required = ((kind == "invalid" and adapter["invalid_message"])
                            or (kind == "null_parameters" and adapter["null_parameters_message"]))
        if message_required and returned == 2:
            checks.append({"check": "error_message", "ok": bool(error and error.strip())})
        if returned == 1:
            checks.append({"check": "general_message", "ok": bool(general and general.strip())})
        if kind == "valid" and returned in (0, 1) and adapter["clear_error_on_success"]:
            checks.append({"check": "success_error_cleared", "ok": not error_pointer})
        mutations = []
        for name, buffer in protected.items():
            after = buffer.snapshot()
            checks.append({"check": f"{name}/guards", "ok": buffer.intact()})
            normalization = (name == "Parameters" and returned in (0, 1)
                             and adapter.get("parameter_mutation", "forbid") == "allow-normalization")
            if normalization:
                before_protected, after_protected = bytearray(snapshots[name]), bytearray(after)
                structure = type(buffer.body)
                for index, row in enumerate(self.metadata["parameters"]):
                    if row["datatype"] == 10:
                        continue
                    field = getattr(structure, f"field_{index}")
                    start, end = field.offset, field.offset + field.size
                    if snapshots[name][start:end] != after[start:end]:
                        mutations.append({"parameter": row["name"], "index": index,
                                          "before_hex": snapshots[name][start:end].hex(),
                                          "after_hex": after[start:end].hex(),
                                          "policy": "allow-normalization"})
                    value = getattr(buffer.body, f"field_{index}")
                    if row["datatype"] == 1:
                        value = value[0]
                        if row["char_signedness"] == "signed" and value >= 128:
                            value -= 256
                    # Permission to normalize does not waive the selected value contract.
                    if adapter.get("nonfinite", "reject") == "reject":
                        checks.append({"check": f"parameter[{index}]/normalized_finite",
                                       "ok": math.isfinite(value)})
                    if adapter["bounds"] == "inclusive":
                        checks.append({"check": f"parameter[{index}]/normalized_bounds",
                                       "ok": row["minimum"] <= value <= row["maximum"]})
                    before_protected[start:end] = after_protected[start:end] = b"\0" * field.size
                checks.append({"check": "Parameters/protected_bytes_unchanged",
                               "ok": before_protected == after_protected})
            else:
                checks.append({"check": f"{name}/unchanged", "ok": after == snapshots[name]})
        checks.append({"check": "Instance/guards", "ok": self.instance_buffer.intact()})
        checks.append({"check": "instance_fields_unchanged",
                       "ok": self.stable_instance_bytes() == instance_bytes})
        return {"kind": kind, "return_code": returned, "error_message": error,
                "general_message": general, "diagnostic_channel": channel if passed_instance else None,
                "error_pointer_present": error_pointer, "general_pointer_present": general_pointer,
                "parameter_mutations": mutations, "checks": checks}

    def stable_instance_bytes(self):
        data = bytearray(c.string_at(c.addressof(self.instance), c.sizeof(self.instance)))
        for field in ("LastErrorMessage", "LastGeneralMessage"):
            offset = getattr(abi.Instance, field).offset
            data[offset:offset + c.sizeof(c.c_void_p)] = b"\0" * c.sizeof(c.c_void_p)
        return bytes(data)


def check_case(library, metadata, case, adapter):
    check = library.Model_CheckParameters
    check.argtypes = [c.POINTER(abi.Instance)]
    check.restype = c.c_int
    host = Host(metadata)
    if "index" in case:
        host.set_parameter(case["index"], case["value"])
    if case["kind"] == "null_parameters":
        host.instance.Parameters = None
    calls = [host.observe_call(check, case["kind"], adapter)]
    if case["kind"] == "invalid" and adapter.get("recheck_policy", "same-instance") == "same-instance":
        host.defaults()
        calls.append(host.observe_call(check, "valid", adapter))
    unchanged = read_metadata(library, adapter) == metadata
    return {"ok": unchanged and all(check["ok"] for call in calls for check in call["checks"]),
            "calls": calls, "metadata_unchanged": unchanged,
            "recheck_policy": adapter.get("recheck_policy", "same-instance")}


def read_metadata(library, adapter):
    return abi.read_metadata(library, adapter["char_signedness"],
                             name_syntax=adapter.get("name_syntax", "nonempty"),
                             fixed_value_policy=adapter.get("fixed_value_policy", "nonzero"))


def run(request):
    if c.sizeof(c.c_void_p) != 8:
        raise ValueError("this release requires a 64-bit host")
    path = Path(request["library"])
    if sha256(path) != request["library_sha256"]:
        raise ValueError("library identity changed before loading")
    if os.name == "nt":
        library = c.CDLL(str(path), winmode=0x1100)
    else:
        library = c.CDLL(str(path), mode=os.RTLD_LOCAL | os.RTLD_NOW)
    missing = [name for name in EXPORTS if not hasattr(library, name)]
    if missing:
        return {"ok": False, "detail": "missing exports", "missing_exports": missing}
    metadata = read_metadata(library, request["adapter"])
    check_expectations(metadata, request["adapter"])
    if request["action"] == "metadata":
        result = {"ok": True, "metadata": metadata, "native_layout": abi.native_layout(),
                  "native_layout_scope": "ctypes declarations; not producer-library attestation",
                  "host_layouts": abi.host_layouts(metadata)}
    else:
        if metadata != request["metadata"]:
            raise ValueError("metadata changed between workers")
        result = check_case(library, metadata, request["case"], request["adapter"])
    if sha256(path) != request["library_sha256"]:
        raise ValueError("library identity changed after loading")
    return result


def main():
    request_path, result_path = map(Path, sys.argv[1:])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (LOG_LIMIT, LOG_LIMIT))
        cpu_seconds = max(1, math.ceil(request["timeout"]) + 1)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    try:
        result = run(request)
    except (OSError, ValueError, AttributeError, TypeError, OverflowError) as error:
        result = {"ok": False, "detail": str(error), "exception": type(error).__name__}
    result_path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
