"""Bounded local worker execution. No shell, model imports, or network calls."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


class WorkerTimeout(Exception):
    pass


class WorkerFailed(Exception):
    pass


class WorkerUnavailable(Exception):
    pass


class WindowsJob:
    """Kill-on-close Job Object, including descendants of an exited worker."""
    def __init__(self):
        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                        ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in ("user", "kernel", "period_user", "period_kernel")] + [
                (name, wintypes.DWORD) for name in ("faults", "total", "active", "terminated")]

        self.accounting = Accounting

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                       wintypes.DWORD, ctypes.c_void_p]
        self.api.QueryInformationJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("Cannot create worker job")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError("Cannot configure worker job")

    def assign(self, pid: int):
        process = self.api.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise OSError("Cannot open worker process")
        try:
            if not self.api.AssignProcessToJobObject(self.handle, process):
                raise OSError("Cannot contain worker process")
        finally:
            self.api.CloseHandle(process)

    def terminate(self):
        if self.handle:
            if not self.api.TerminateJobObject(self.handle, 1):
                raise OSError("Cannot terminate worker job")
            deadline = time.monotonic() + 5
            while True:
                accounting = self.accounting()
                if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting),
                                                          ctypes.sizeof(accounting), None):
                    raise OSError("Cannot query worker job")
                if not accounting.active:
                    break
                if time.monotonic() >= deadline:
                    raise OSError("Worker job did not terminate")
                time.sleep(0.01)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def run_worker(python: Path, script: Path, request: dict, *, timeout: float,
               output_limit: int, cpu_threads: int) -> dict:
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", CUDA_VISIBLE_DEVICES="",
               OMP_NUM_THREADS=str(cpu_threads), MKL_NUM_THREADS=str(cpu_threads),
               AUDIOMASK_CPU_THREADS=str(cpu_threads))
    proc = None
    job = None
    readers = []
    writer = None
    output = bytearray()
    overflow = threading.Event()
    deadline = time.monotonic() + timeout

    def read_pipe(pipe, keep):
        count = 0
        try:
            while chunk := pipe.read(4096):
                count += len(chunk)
                if count > output_limit:
                    overflow.set()
                    return
                if keep:
                    output.extend(chunk)
        finally:
            pipe.close()

    def write_request(pipe, data):
        try:
            pipe.write(data)
            pipe.flush()
        except (BrokenPipeError, OSError):
            pass  # Exit status/output determines the sanitized worker error.
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    try:
        if os.name == "nt":
            job = WindowsJob()
        proc = subprocess.Popen(
            [str(python), "-I", "-u", str(script)], shell=False,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=str(script.parent),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        # Trusted workers wait for stdin before importing libraries/spawning any
        # descendants. Assign to the job before releasing this startup gate.
        if job:
            job.assign(proc.pid)
        for pipe, keep in [(proc.stdout, True), (proc.stderr, False)]:
            thread = threading.Thread(target=read_pipe, args=(pipe, keep), daemon=True)
            readers.append(thread)
            thread.start()
        data = json.dumps(request, ensure_ascii=True).encode("ascii") + b"\n"
        if len(data) >= 65536:
            raise WorkerFailed()
        # Even a misconfigured interpreter that never reads stdin cannot block
        # the supervisor's deadline on a full Windows pipe.
        writer = threading.Thread(target=write_request, args=(proc.stdin, data), daemon=True)
        writer.start()
        while proc.poll() is None:
            if overflow.is_set():
                raise WorkerFailed()
            if time.monotonic() >= deadline:
                raise WorkerTimeout()
            time.sleep(0.01)
        # Cleanup below kills descendants before joining readers: a child may
        # still hold the output handles even after its parent exits.
    except (OSError, ValueError) as exc:
        raise WorkerUnavailable() from exc
    finally:
        try:
            if proc is not None:
                if job:
                    job.terminate()
                elif os.name != "nt":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        finally:
            if job:
                job.close()
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                if writer:
                    writer.join()
                elif proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            for thread in readers:
                thread.join()
    if overflow.is_set() or proc.returncode != 0:
        # Workers use exit 3 for unavailable dependencies/weights, without
        # forwarding tracebacks or model output to the HTTP response/logs.
        if proc.returncode == 3 and not overflow.is_set():
            raise WorkerUnavailable()
        raise WorkerFailed()
    try:
        result = json.loads(output.decode("utf-8"))
        if not isinstance(result, dict) or set(result) != {"text"} or not isinstance(result["text"], str):
            raise ValueError()
        return result
    except (UnicodeError, ValueError) as exc:
        raise WorkerFailed() from exc
