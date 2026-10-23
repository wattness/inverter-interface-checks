"""Bounded workers. Process isolation is not a security sandbox."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LOG_LIMIT = 131072


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def worker_environment(directory):
    environment = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
                   "TMPDIR": str(directory), "TEMP": str(directory), "TMP": str(directory)}
    for key in ("SystemRoot", "WINDIR"):
        if key in os.environ:
            environment[key] = os.environ[key]
    return environment


def stop_process(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait(timeout=5)


def run_worker(request, timeout):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="inverter-check-") as temporary:
        directory = Path(temporary)
        request_path, result_path = directory / "request.json", directory / "result.json"
        log_path = directory / "native.log"
        request_path.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
        command = [sys.executable, "-I", "-B", str(Path(__file__).with_name("worker.py")),
                   str(request_path), str(result_path)]
        with log_path.open("wb") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       cwd=directory, env=worker_environment(directory),
                                       start_new_session=os.name == "posix")
            reason = None
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    reason = "timeout"
                elif log_path.stat().st_size >= LOG_LIMIT:
                    reason = "output_limit"
                if reason:
                    stop_process(process)
                    break
                time.sleep(0.01)
            if os.name == "posix":
                stop_process(process)
        elapsed = round(time.monotonic() - started, 4)
        if reason is None and log_path.stat().st_size >= LOG_LIMIT:
            reason = "output_limit"
        if reason is None and process.returncode:
            reason = "native_crash" if process.returncode < 0 else "worker_exit"
        if reason is None and (not result_path.exists() or result_path.stat().st_size > LOG_LIMIT):
            reason = "invalid_worker_result"
        with log_path.open("rb") as stream:
            log_text = stream.read(8192).decode("utf-8", errors="replace")
        log_text = log_text.encode("utf-8")[:8192].decode("utf-8", errors="ignore")
        if reason:
            return {"ok": False, "execution": reason, "returncode": process.returncode,
                    "elapsed_seconds": elapsed, "native_log": log_text}
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise ValueError("invalid worker result")
        except (OSError, ValueError) as error:
            return {"ok": False, "execution": "invalid_worker_result", "detail": str(error),
                    "elapsed_seconds": elapsed, "native_log": log_text}
        result.update(execution="completed", elapsed_seconds=elapsed)
        if log_text:
            result["native_log"] = log_text
        return result
