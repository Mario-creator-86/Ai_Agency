"""The few Windows calls start.py needs to start and stop the live graphics (ctypes, no new
dependency): the process list with command lines, the free commit, the session, closing and
killing one process, a Job Object that kills its processes when start.py goes, and a console
control handler for the closed window.

Everything here is read-only except `post_close`, `kill`, the job and the handler, and the
callers decide which pid they touch (scripts/live_graphics.py checks name AND command line
first). On another platform every function answers "nothing" and changes nothing.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

WINDOWS = sys.platform == "win32"

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WM_CLOSE = 0x0010
STILL_ACTIVE = 259
#: NtQueryInformationProcess's ProcessCommandLineInformation (Windows 8.1 and later).
PROCESS_COMMAND_LINE_INFORMATION = 60
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

#: A process seen by name and command line.
ProcessRow = tuple[int, str, str]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> Any:
    """kernel32 with the signatures this module uses (handles are pointers: never truncated)."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = handle
    k.Process32FirstW.argtypes = [handle, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32FirstW.restype = wintypes.BOOL
    k.Process32NextW.argtypes = [handle, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32NextW.restype = wintypes.BOOL
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = handle
    k.CloseHandle.argtypes = [handle]
    k.CloseHandle.restype = wintypes.BOOL
    k.TerminateProcess.argtypes = [handle, wintypes.UINT]
    k.TerminateProcess.restype = wintypes.BOOL
    k.WaitForSingleObject.argtypes = [handle, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.GetExitCodeProcess.argtypes = [handle, ctypes.POINTER(wintypes.DWORD)]
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.K32GetPerformanceInfo.argtypes = [ctypes.POINTER(PERFORMANCE_INFORMATION), wintypes.DWORD]
    k.K32GetPerformanceInfo.restype = wintypes.BOOL
    k.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    k.ProcessIdToSessionId.restype = wintypes.BOOL
    k.GetCurrentProcessId.restype = wintypes.DWORD
    k.GetCurrentProcess.restype = handle
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.CreateJobObjectW.restype = handle
    k.SetInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.QueryInformationJobObject.argtypes = [
        handle,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    k.QueryInformationJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [handle, handle]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.IsProcessInJob.argtypes = [handle, handle, ctypes.POINTER(wintypes.BOOL)]
    k.IsProcessInJob.restype = wintypes.BOOL
    return k


_K32: Any = None


def kernel32() -> Any:
    global _K32
    if _K32 is None:
        _K32 = _kernel32()
    return _K32


def _open(pid: int, access: int) -> int | None:
    h = kernel32().OpenProcess(access, False, pid)
    return h or None


def command_line(pid: int) -> str:
    """A process's command line, or "" when Windows does not give it (another user's, gone)."""
    if not WINDOWS:
        return ""
    k = kernel32()
    ntdll = ctypes.WinDLL("ntdll")
    query = ntdll.NtQueryInformationProcess
    query.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    query.restype = ctypes.c_long
    h = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if h is None:
        return ""
    try:
        size = wintypes.ULONG(0)
        query(h, PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(size))
        if not size.value:
            return ""
        buffer = ctypes.create_string_buffer(size.value)
        if query(h, PROCESS_COMMAND_LINE_INFORMATION, buffer, size, ctypes.byref(size)) != 0:
            return ""
        text = UNICODE_STRING.from_buffer(buffer)
        if not text.Buffer or not text.Length:
            return ""
        return ctypes.wstring_at(text.Buffer, text.Length // 2)
    finally:
        k.CloseHandle(h)


def list_processes(want_command_line: Callable[[str], bool]) -> list[ProcessRow]:
    """Every process as (pid, name, command line); the command line is read only for the names
    `want_command_line` accepts (it costs a handle per process)."""
    if not WINDOWS:
        return []
    k = kernel32()
    snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return []
    rows: list[ProcessRow] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pid, name = int(entry.th32ProcessID), entry.szExeFile
            rows.append((pid, name, command_line(pid) if want_command_line(name) else ""))
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return rows


def free_commit_bytes() -> int | None:
    """Commit limit minus commit charge: what Win32_OperatingSystem.FreeVirtualMemory reports,
    and what Unreal dies on (machine note 2026-09-19)."""
    if not WINDOWS:
        return None
    info = PERFORMANCE_INFORMATION()
    info.cb = ctypes.sizeof(info)
    if not kernel32().K32GetPerformanceInfo(ctypes.byref(info), info.cb):
        return None
    return int((info.CommitLimit - info.CommitTotal) * info.PageSize)


def session_id() -> int | None:
    """This process's Windows session: 0 is the services' session, with no desktop."""
    if not WINDOWS:
        return None
    k = kernel32()
    session = wintypes.DWORD(0)
    if not k.ProcessIdToSessionId(k.GetCurrentProcessId(), ctypes.byref(session)):
        return None
    return int(session.value)


def post_close(pid: int) -> int:
    """Ask a process to close: WM_CLOSE to each of its top-level windows. Returns how many."""
    if not WINDOWS:
        return 0
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    windows: list[int] = []

    def visit(hwnd: int, _: int) -> bool:
        owner = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            windows.append(hwnd)
        return True

    user32.EnumWindows(callback_type(visit), 0)
    for hwnd in windows:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return len(windows)


def kill(pid: int) -> bool:
    """TerminateProcess. The caller has checked that the pid is the process it means."""
    if not WINDOWS:
        return False
    h = _open(pid, PROCESS_TERMINATE)
    if h is None:
        return False
    try:
        return bool(kernel32().TerminateProcess(h, 1))
    finally:
        kernel32().CloseHandle(h)


def wait_exit(pid: int, timeout: float) -> bool:
    """True once the process is gone (or was never there), False if it still runs after
    `timeout` seconds."""
    if not WINDOWS:
        return True
    h = _open(pid, SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION)
    if h is None:
        return True
    try:
        result = kernel32().WaitForSingleObject(h, int(max(timeout, 0) * 1000))
        return bool(result == WAIT_OBJECT_0)
    finally:
        kernel32().CloseHandle(h)


class KillOnCloseJob:
    """A Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: when its last handle closes - when
    start.py ends, however it ends - Windows ends every process in it.

    The handle is not inheritable, so no child holds the job open. A process already in another
    job is nested under it (Windows 8 and later), which is what `uv run`, Windows Terminal and
    PyCharm do to start.py; a process that cannot be nested is reported, never forced."""

    def __init__(self, handle: int) -> None:
        self.handle: int | None = handle

    @classmethod
    def create(cls) -> KillOnCloseJob | None:
        if not WINDOWS:
            return None
        k = kernel32()
        handle = k.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(
            handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
        ):
            k.CloseHandle(handle)
            return None
        return cls(handle)

    def kill_on_close(self) -> bool:
        """Whether the job really carries the limit (read back from Windows)."""
        if self.handle is None:
            return False
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if not kernel32().QueryInformationJobObject(
            self.handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return False
        flags = info.BasicLimitInformation.LimitFlags
        return bool(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)

    def _assign_handle(self, process: int) -> bool:
        k = kernel32()
        inside = wintypes.BOOL(False)
        if k.IsProcessInJob(process, self.handle, ctypes.byref(inside)) and inside.value:
            return True
        return bool(k.AssignProcessToJobObject(self.handle, process))

    def assign_current(self) -> bool:
        """Put start.py itself in the job: every process it starts from then on, and theirs,
        is in it from its first instruction (no window between a start and an assignment)."""
        if self.handle is None:
            return False
        return self._assign_handle(kernel32().GetCurrentProcess())

    def assign(self, pid: int) -> bool:
        if self.handle is None:
            return False
        h = _open(pid, PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION)
        if h is None:
            return False
        try:
            return self._assign_handle(h)
        finally:
            kernel32().CloseHandle(h)

    def close(self) -> None:
        """Closing the last handle ends every process still in the job."""
        if self.handle is not None:
            kernel32().CloseHandle(self.handle)
            self.handle = None


def install_close_handler(callback: Callable[[], None]) -> Any:
    """Run `callback` when the console window is closed, the user logs off or Windows shuts down.
    Windows gives a console process about five seconds after CTRL_CLOSE_EVENT and then ends it;
    a process whose handler returns at once (Python's, uvicorn's) is ended at once.
    Ctrl+C and Ctrl+Break pass through to Python's own handling. Returns the routine, which the
    caller keeps (a collected routine would crash the handler)."""
    if not WINDOWS:
        return None
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    routine_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    k.SetConsoleCtrlHandler.argtypes = [routine_type, wintypes.BOOL]
    k.SetConsoleCtrlHandler.restype = wintypes.BOOL

    def handler(event: int) -> bool:
        if event not in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            return False
        try:
            callback()
        except BaseException:  # noqa: BLE001 - nothing may escape into Windows' thread
            pass
        return True

    routine = routine_type(handler)
    k.SetConsoleCtrlHandler(routine, True)
    return routine
