"""Stand-ins for the slice of pywin32 the session wrapper imports.

``session._com()`` imports ``pythoncom`` and ``win32com.client`` inside the
functions that need them, so putting these two modules in ``sys.modules`` is
enough to exercise the save path on a host without pywin32 -- which is every
Linux runner in CI.  The names and the VARIANT type codes mirror the real
package; the wrapper only reads the codes and the ``.value`` slot.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

#: The VARIANT type codes the wrapper ORs together. Copied from the real
#: package so a stub value can never disagree with production behaviour.
VT_EMPTY = 0
VT_I2 = 2
VT_I4 = 3
VT_BSTR = 8
VT_DISPATCH = 9
VT_BOOL = 11
VT_BYREF = 0x4000


class ComError(Exception):
    """pywintypes.com_error: what SolidWorks raises for a refused call."""


class Variant:
    """win32com.client.VARIANT: a typed value, filled in when passed by ref."""

    __slots__ = ("vt", "value")

    def __init__(self, vt: int, value: Any = None) -> None:
        self.vt = vt
        self.value = value

    def __repr__(self) -> str:
        return f"VARIANT({self.vt}, {self.value!r})"


def _pythoncom() -> ModuleType:
    mod = ModuleType("pythoncom")
    for name in ("VT_EMPTY", "VT_I2", "VT_I4", "VT_BSTR", "VT_DISPATCH", "VT_BOOL", "VT_BYREF"):
        setattr(mod, name, globals()[name])
    mod.CoInitialize = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    mod.CoUninitialize = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    return mod


def _pywintypes() -> ModuleType:
    mod = ModuleType("pywintypes")
    mod.com_error = ComError  # type: ignore[attr-defined]
    return mod


def _win32com() -> tuple[ModuleType, ModuleType]:
    client = ModuleType("win32com.client")
    client.VARIANT = Variant  # type: ignore[attr-defined]

    def get_active_object(progid: str = "SldWorks.Application") -> Any:
        # Nothing is running in a test, which is exactly what a test runner is
        # like; the wrapper turns this into its own SwError.
        raise ComError(f"-2147221005 invalid class string: {progid}")

    client.GetActiveObject = get_active_object  # type: ignore[attr-defined]
    client.Dispatch = get_active_object  # type: ignore[attr-defined]
    pkg = ModuleType("win32com")
    pkg.client = client  # type: ignore[attr-defined]
    return pkg, client


def install(monkeypatch: Any) -> None:
    """Shadow pywin32 for the duration of one test, whichever host runs it."""
    package, client = _win32com()
    monkeypatch.setitem(sys.modules, "pythoncom", _pythoncom())
    monkeypatch.setitem(sys.modules, "pywintypes", _pywintypes())
    monkeypatch.setitem(sys.modules, "win32com", package)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
