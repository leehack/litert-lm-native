#!/usr/bin/env python3
"""Checks that a runtime's CPU backend honours the requested thread count (#89).

XNNPACK starts one worker per extra thread when the LLM session is created.
The probe creates a CPU engine and session once with one thread and once with
--threads, each in a fresh process, and requires the second process to own at
least threads - 1 more threads. A runtime that drops the CPU options runs
single-threaded and adds none.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CHILD_TIMEOUT_SECONDS = 600
LOG_SEVERITY_ERROR = 4
_DLL_DIRECTORY_HANDLES: list[object] = []


def process_thread_count() -> int:
    if sys.platform.startswith("linux"):
        return len(os.listdir("/proc/self/task"))
    if sys.platform == "darwin":
        return _darwin_thread_count()
    if sys.platform == "win32":
        return _windows_thread_count()
    raise RuntimeError(f"Unsupported probe host: {sys.platform}")


def _darwin_thread_count() -> int:
    class ProcTaskInfo(ctypes.Structure):
        _fields_ = [("times", ctypes.c_uint64 * 6), ("counters", ctypes.c_int32 * 12)]

    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    info = ProcTaskInfo()
    proc_pidtaskinfo = 4
    size = libc.proc_pidinfo(os.getpid(), proc_pidtaskinfo, ctypes.c_uint64(0),
                             ctypes.byref(info), ctypes.sizeof(info))
    if size != ctypes.sizeof(info):
        raise RuntimeError("proc_pidinfo(PROC_PIDTASKINFO) failed")
    # pti_threadnum follows nine int32 counters.
    return info.counters[9]


def _windows_thread_count() -> int:
    from ctypes import wintypes

    class ThreadEntry32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    th32cs_snapthread = 0x4
    snapshot = kernel32.CreateToolhelp32Snapshot(th32cs_snapthread, 0)
    if snapshot in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        pid = os.getpid()
        count = 0
        more = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            count += entry.th32OwnerProcessID == pid
            more = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        return count
    finally:
        kernel32.CloseHandle(snapshot)


def bind(library_path: Path) -> ctypes.CDLL:
    if os.name == "nt":
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(library_path.parent)))
    library = ctypes.CDLL(str(library_path))
    pointer = ctypes.c_void_p
    signatures = {
        "litert_lm_set_min_log_level": (None, [ctypes.c_int]),
        "litert_lm_engine_settings_create": (
            pointer, [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]),
        "litert_lm_engine_settings_set_num_threads": (None, [pointer, ctypes.c_int]),
        "litert_lm_engine_settings_set_cache_dir": (None, [pointer, ctypes.c_char_p]),
        "litert_lm_engine_settings_delete": (None, [pointer]),
        "litert_lm_engine_create": (pointer, [pointer]),
        "litert_lm_engine_delete": (None, [pointer]),
        "litert_lm_session_config_create": (pointer, []),
        "litert_lm_session_config_delete": (None, [pointer]),
        "litert_lm_engine_create_session": (pointer, [pointer, pointer]),
        "litert_lm_session_delete": (None, [pointer]),
    }
    for name, (restype, argtypes) in signatures.items():
        function = getattr(library, name)
        function.restype = restype
        function.argtypes = argtypes
    return library


def session_thread_count(library_path: Path, model: Path, threads: int) -> int:
    """Returns this process's thread count with a live CPU session."""
    library = bind(library_path)
    library.litert_lm_set_min_log_level(LOG_SEVERITY_ERROR)
    with tempfile.TemporaryDirectory(prefix="litert-lm-threads-") as cache_dir:
        settings = library.litert_lm_engine_settings_create(
            str(model).encode(), b"cpu", None, None)
        if not settings:
            raise RuntimeError("litert_lm_engine_settings_create failed")
        engine = session = config = None
        try:
            library.litert_lm_engine_settings_set_num_threads(settings, threads)
            library.litert_lm_engine_settings_set_cache_dir(settings, cache_dir.encode())
            engine = library.litert_lm_engine_create(settings)
            if not engine:
                raise RuntimeError("litert_lm_engine_create failed")
            config = library.litert_lm_session_config_create()
            session = library.litert_lm_engine_create_session(engine, config)
            if not session:
                raise RuntimeError("litert_lm_engine_create_session failed")
            return process_thread_count()
        finally:
            if session:
                library.litert_lm_session_delete(session)
            if config:
                library.litert_lm_session_config_delete(config)
            if engine:
                library.litert_lm_engine_delete(engine)
            library.litert_lm_engine_settings_delete(settings)


def evaluate(threads: int, counts: dict[int, int]) -> dict[str, object]:
    added = counts[threads] - counts[1]
    return {
        "threads": threads,
        "threadCounts": {str(n): counts[n] for n in sorted(counts)},
        "addedThreads": added,
        "requiredAddedThreads": threads - 1,
        "passed": added >= threads - 1,
    }


def measure_in_child(library: Path, model: Path, threads: int) -> int:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child",
         "--library", str(library), "--model", str(model), "--threads", str(threads)],
        check=True, capture_output=True, text=True, timeout=CHILD_TIMEOUT_SECONDS)
    return json.loads(result.stdout.strip().splitlines()[-1])["threadCount"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    library = args.library.resolve()
    if args.child:
        count = session_thread_count(library, args.model.resolve(), args.threads)
        print(json.dumps({"threadCount": count}), flush=True)
        return 0
    if args.threads < 2:
        parser.error("--threads must be at least 2")
    counts = {n: measure_in_child(library, args.model, n) for n in (1, args.threads)}
    result = evaluate(args.threads, counts)
    print(json.dumps(result, sort_keys=True), flush=True)
    if not result["passed"]:
        print(f"CPU backend ignored num_threads={args.threads}: the session added "
              f"{result['addedThreads']} threads over num_threads=1", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
