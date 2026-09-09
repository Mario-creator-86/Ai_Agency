"""Fernet credential encryption; Windows key is wrapped with per-user DPAPI."""

import ctypes
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


def dpapi(data: bytes, decrypt: bool = False) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    api = ctypes.windll.crypt32  # type: ignore[attr-defined]
    function = api.CryptUnprotectData if decrypt else api.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Credential key cannot be accessed by this Windows account")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))  # type: ignore[attr-defined]


class CredentialVault:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _cipher(self, create: bool = False) -> Fernet:
        if not self.path.exists() and create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            wrapped = dpapi(key) if os.name == "nt" else key
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(wrapped)
                    handle.flush()
                    os.fsync(handle.fileno())
        stored = self.path.read_bytes()
        return Fernet(dpapi(stored, True) if os.name == "nt" else stored)

    def encrypt(self, values: dict) -> str:
        return self._cipher(create=True).encrypt(json.dumps(values).encode()).decode()

    def decrypt(self, value: str) -> dict:
        return json.loads(self._cipher().decrypt(value.encode()))
