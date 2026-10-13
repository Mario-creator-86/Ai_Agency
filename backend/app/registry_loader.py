"""Import every module of a package once, on first need (2026-10-09, P0).

The Owner's rule of 2026-10-09: every correction must leave the studio able to notice the
mistake and repair it itself, asking him only for money, his accounts or his choices. About
fifteen packages of that plan each add a card (an applier and a condition of the decisions
core) or a watchdog pass. Written into `decisions/services.py` and `workflows/watchdog.py`
directly, they would all queue on the same three tables; so each adds a module of its own to
`app.decisions.producers` or `app.workflows.passes`, which registers itself when it is
imported, and the registry imports the whole package the first time it is read.

Why on first read and not at import: a producer imports the decisions core (to register),
and the core is imported by the media and provider modules a producer reads; importing the
producers while the core itself is being imported would close that circle. On first read
every module the studio needs is already there.

What a module of such a package may do when imported: define functions and register them.
Nothing else: no database, no network, no file written. A module that fails to import is
logged and named in `errors`; the others still load, and whatever named the missing piece
fails closed where it is read (a card's condition reads UNREADABLE, an accept refuses).

A module that fails after it registered something leaves nothing behind (review of
2026-10-09): every entry it added is taken out again (`added` records them), and a sibling it
imported meanwhile is forgotten and imported again in its own turn. Without that, half of a
broken producer stayed live: its applier ran his accept while the module was named as not
loaded, and a card whose condition name collided read the other module's condition.

That held only while the loader itself was importing the module (second review of
2026-10-09). A producer imported first some other way (a pass module's top, a router, a
sibling that caught its error) registered while no loader was looking; its own turn then found
«the same function» already there, failed again and undid nothing, and his accept could still
run the applier of a module the studio named as not loaded. So an entry registered by any
other module than the one this loader is importing is also kept as owned by its function's
module, and every read of a table first drops what a module that is not imported (Python
forgets a module whose import failed) left behind (`_drop_dead`).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
import threading
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger("studio.registry")


def _module_of(entry: object) -> str | None:
    """The module that defined a registered entry: a function's own, or, for a watchdog
    pass's entry, its function's."""
    module = getattr(getattr(entry, "function", entry), "__module__", None)
    return module if isinstance(module, str) else None


class _Owned:
    """An entry kept as owned by its function's module, with the tables whose entry of the
    same name goes with it (a condition's words). Compared by identity."""

    __slots__ = ("also", "key", "module", "table")

    def __init__(
        self, table: dict[str, Any], key: str, module: str, also: tuple[dict[str, Any], ...]
    ) -> None:
        self.table, self.key, self.module, self.also = table, key, module, also


class PackageLoader:
    """Imports every public module (not starting with ``_``) of one package, once, in the
    order of their names. Safe to call from any thread and from inside the load itself: a
    module that reads its registry while it is being imported sees what is registered so far,
    and another thread waits until the whole package is in."""

    def __init__(self, package: str) -> None:
        self.package = package
        self._lock = threading.RLock()
        self._done = False
        self._loading = False
        #: Module name -> why it could not be imported ("Type: message").
        self.errors: dict[str, str] = {}
        #: The modules imported, in order.
        self.loaded: list[str] = []
        # The module being imported (and by which thread), and the entries it added so far.
        self._importing: str | None = None
        self._importing_thread: int | None = None
        self._added: list[tuple[dict[str, Any], str]] = []
        # Entries registered by a module other than the one this loader was importing (or with
        # no load running): checked on every read against the modules Python still has.
        self._owned: list[_Owned] = []

    @property
    def done(self) -> bool:
        return self._done

    def load(self) -> None:
        """Import the package's modules unless that already happened (or is happening on
        this thread: a registration read during the load must not start it again)."""
        if self._done:
            if self._owned:
                self._drop_dead()
            return
        with self._lock:
            if self._done or self._loading:
                return
            self._loading = True
            try:
                self._import_all()
            finally:
                self._loading = False
                self._done = True
            self._drop_dead()

    def added(
        self,
        table: dict[str, Any],
        key: str,
        *,
        owner: object,
        also: Iterable[dict[str, Any]] = (),
    ) -> None:
        """A registry calls this after it added a NEW entry (not one already there); ``owner``
        is the registered function, ``also`` the tables whose entry of the same name goes with
        it. When that happens while one of this package's modules is being imported on this
        thread, the entry is taken out again if that import fails. When the function is not
        that module's own (or nothing is being imported), the entry is also kept as owned by
        its function's module, and dropped on a read once that module is not imported.

        No lock here: a module registering on another thread while this loader holds its lock
        could be the very module the load waits for (Python's import locks would not see
        that circle); appending to a list is atomic."""
        others = tuple(also)
        importing = self._importing
        in_turn = importing is not None and self._importing_thread == threading.get_ident()
        if in_turn:
            self._added.extend((each, key) for each in (table, *others))
        module = _module_of(owner)
        if module is not None and (not in_turn or module != importing):
            self._owned.append(_Owned(table, key, module, others))

    def _drop_dead(self) -> None:
        """Take out every kept entry whose module Python does not have: its import failed
        (Python forgets such a module) or a failed sibling's undo forgot it. A module being
        imported is already in `sys.modules`, so its entries stay while it runs."""
        for record in list(self._owned):
            current = dict.get(record.table, record.key)
            if current is None or _module_of(current) != record.module:
                self._forget(record)  # gone, or another module's entry now
                continue
            if sys.modules.get(record.module) is not None:
                continue
            for each in (record.table, *record.also):
                # dict's own pop: a registry's reads would start the load this is part of.
                dict.pop(each, record.key, None)
            self._forget(record)
            logger.error(
                "registry_entry_of_failed_module_dropped",
                extra={"registry_module": record.module, "entry": record.key},
            )

    def _forget(self, record: _Owned) -> None:
        try:
            self._owned.remove(record)
        except ValueError:  # another thread forgot it first
            pass

    def _import_all(self) -> None:
        package = importlib.import_module(self.package)
        paths = list(getattr(package, "__path__", []))
        prefix = f"{self.package}."
        for info in sorted(pkgutil.iter_modules(paths), key=lambda found: found.name):
            if info.name.startswith("_"):
                continue
            name = f"{prefix}{info.name}"
            before = {module for module in sys.modules if module.startswith(prefix)}
            self._importing, self._importing_thread = name, threading.get_ident()
            self._added = []
            try:
                importlib.import_module(name)
            except Exception as exc:  # noqa: BLE001 - one broken module must not hide the rest
                self._undo(before, prefix)
                self.errors[name] = f"{type(exc).__name__}: {exc}"[:500]
                logger.error(
                    "registry_module_import_failed",
                    # Not "module": that is a LogRecord field, and logging refuses to overwrite it.
                    extra={"registry_module": name, "error": type(exc).__name__},
                    exc_info=exc,
                )
            else:
                self.loaded.append(name)
            finally:
                self._importing, self._importing_thread = None, None
                self._added = []

    def _undo(self, before: set[str], prefix: str) -> None:
        """Take out what the failed module registered, and forget the siblings it imported
        (Python forgets only the failed module itself): a sibling's entries were counted as
        the failed module's and are gone, so it must run again in its own turn."""
        for table, key in reversed(self._added):
            # dict's own pop: a registry's reads would start the load this is part of.
            dict.pop(table, key, None)
        for module in [m for m in sys.modules if m.startswith(prefix) and m not in before]:
            del sys.modules[module]
        # And what a module imported meanwhile from elsewhere registered and then failed on.
        self._drop_dead()

    def reset(self) -> None:
        """Forget that the package was loaded, so the next read imports it again. For tests
        that add a module of their own; the modules already imported are not run again."""
        with self._lock:
            self._done = False
            self.errors.clear()
            self.loaded.clear()


__all__ = ["PackageLoader"]
