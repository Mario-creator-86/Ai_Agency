"""Fernet credential encryption; Windows key is wrapped with per-user DPAPI.

A key that cannot be read is said, not crashed on (REL-06, TS-03, SELL-12). The key file is
missing after a restore that left it behind, foreign after a restore of another studio's key,
and unreadable to any Windows account but the one that wrapped it (and, plausibly, to the same
account under the S4U "run whether signed in or not" logon, which has no password to unlock
DPAPI). Every such case raises `VaultUnreadable`, an OSError as the old failures were, with a
code and a reason in the Owner's words, so the studio can start and tell him what to do.
"""

import ctypes
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

#: The key file is not there: a restore that left it behind, or a studio never given one.
VAULT_MISSING = "MISSING"
#: The key file is there and this Windows account cannot unwrap it (another account, S4U).
VAULT_UNREADABLE = "UNREADABLE"
#: The key file was unwrapped but is not a key at all.
VAULT_CORRUPT = "CORRUPT"
#: The key reads, but the stored connection was locked with another key (another studio's).
VAULT_FOREIGN = "FOREIGN"

#: What to do, said once for every code: the Owner types the keys again in the page.
RECONNECT_RO = "reconectați furnizorii (introduceți din nou cheile lor) în Setări"

VAULT_REASONS_RO = {
    VAULT_MISSING: (
        "Fișierul cheii conexiunilor lipsește de lângă baza de date (de exemplu după o "
        "restaurare fără el)"
    ),
    VAULT_UNREADABLE: (
        "Fișierul cheii conexiunilor nu poate fi deschis de acest cont Windows (a fost creat de "
        "alt cont, sau studioul rulează ca sarcină fără utilizator conectat)"
    ),
    VAULT_CORRUPT: "Fișierul cheii conexiunilor este deteriorat",
    VAULT_FOREIGN: (
        "Conexiunea a fost salvată cu altă cheie decât cea de lângă baza de date (cheia unui "
        "alt studio)"
    ),
}


class VaultUnreadable(OSError):
    """The stored credentials cannot be read. ``code`` is one of the VAULT_* codes."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.reason_ro = VAULT_REASONS_RO[code]
        super().__init__(f"credential vault {code.lower()}")


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
        try:
            stored = self.path.read_bytes()
        except FileNotFoundError:
            raise VaultUnreadable(VAULT_MISSING) from None
        except OSError:
            raise VaultUnreadable(VAULT_UNREADABLE) from None
        try:
            key = dpapi(stored, True) if os.name == "nt" else stored
        except OSError:
            raise VaultUnreadable(VAULT_UNREADABLE) from None
        try:
            return Fernet(key)
        except (ValueError, TypeError):
            raise VaultUnreadable(VAULT_CORRUPT) from None

    def encrypt(self, values: dict) -> str:
        return self._cipher(create=True).encrypt(json.dumps(values).encode()).decode()

    def decrypt(self, value: str) -> dict:
        cipher = self._cipher()
        try:
            plain = cipher.decrypt(value.encode())
        except InvalidToken:
            raise VaultUnreadable(VAULT_FOREIGN) from None
        try:
            values = json.loads(plain)
        except ValueError:
            raise VaultUnreadable(VAULT_CORRUPT) from None
        return values if isinstance(values, dict) else {}

    def key_present(self) -> bool:
        return self.path.is_file()

    def self_test(self) -> str | None:
        """The canary: None when the key on disk unwraps and round-trips a value, else the
        VAULT_* code. A studio with no key file yet answers VAULT_MISSING; whether that is a
        fault depends on whether anything was stored with a key (`vault_health`). Writes
        nothing: a missing key is never created here."""
        try:
            cipher = self._cipher()
        except VaultUnreadable as exc:
            return exc.code
        try:
            token = cipher.encrypt(b'{"canary": true}')
            return None if json.loads(cipher.decrypt(token)) == {"canary": True} else VAULT_CORRUPT
        except (InvalidToken, ValueError):
            return VAULT_CORRUPT
