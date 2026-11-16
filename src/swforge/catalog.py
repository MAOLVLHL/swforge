"""GB standard fastener dimension tables.

Only the columns the generator needs are kept: across-flats `s`, head height
`k`, washer thickness `t`, and so on.  Values are the maximum material
condition from the standards, in millimetres, so a generated part is never
smaller than the real article.

Sources: GB/T 5783-2016 (hex bolts, full thread), GB/T 6170-2015 (hex nuts,
style 1), GB/T 97.1-2002 (plain washers, product grade A), GB/T 70.1-2008
(hex socket head cap screws).

Every table spans the M3-M30 range the standards define, so a fastener below
M6 or above M20 is a catalogue lookup rather than hand-typed dimensions.  The
four tables carry the same designations on purpose -- a nut, a washer and a
bolt of one designation have to fit each other, and a table that stopped short
would make "M24" mean a bolt with no washer behind it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HexBoltSize:
    designation: str
    d: float
    s: float
    k: float
    lengths: tuple[float, ...]


@dataclass(frozen=True)
class HexNutSize:
    designation: str
    d: float
    s: float
    m: float


@dataclass(frozen=True)
class WasherSize:
    designation: str
    d: float
    inner: float
    outer: float
    t: float


@dataclass(frozen=True)
class SocketScrewSize:
    designation: str
    d: float
    dk: float
    k: float
    socket: float


HEX_BOLTS: dict[str, HexBoltSize] = {
    row.designation: row
    for row in (
        HexBoltSize("M3", 3, 5.5, 2.0, (6, 8, 10, 12, 16, 20)),
        HexBoltSize("M4", 4, 7, 2.8, (8, 10, 12, 16, 20, 25)),
        HexBoltSize("M5", 5, 8, 3.5, (10, 12, 16, 20, 25, 30)),
        HexBoltSize("M6", 6, 10, 4.0, (16, 20, 25, 30, 40)),
        HexBoltSize("M8", 8, 13, 5.3, (20, 25, 30, 40, 50)),
        HexBoltSize("M10", 10, 16, 6.4, (25, 30, 40, 50, 60)),
        HexBoltSize("M12", 12, 18, 7.5, (30, 40, 50, 60, 80)),
        HexBoltSize("M16", 16, 24, 10.0, (40, 50, 60, 80, 100)),
        HexBoltSize("M20", 20, 30, 12.5, (50, 60, 80, 100, 120)),
        HexBoltSize("M24", 24, 36, 15.0, (60, 80, 100, 120, 150)),
        HexBoltSize("M30", 30, 46, 18.7, (80, 100, 120, 150, 180)),
    )
}

HEX_NUTS: dict[str, HexNutSize] = {
    row.designation: row
    for row in (
        HexNutSize("M3", 3, 5.5, 2.4),
        HexNutSize("M4", 4, 7, 3.2),
        HexNutSize("M5", 5, 8, 4.0),
        HexNutSize("M6", 6, 10, 5.2),
        HexNutSize("M8", 8, 13, 6.8),
        HexNutSize("M10", 10, 16, 8.4),
        HexNutSize("M12", 12, 18, 10.8),
        HexNutSize("M16", 16, 24, 14.8),
        HexNutSize("M20", 20, 30, 18.0),
        HexNutSize("M24", 24, 36, 21.5),
        HexNutSize("M30", 30, 46, 25.6),
    )
}

WASHERS: dict[str, WasherSize] = {
    row.designation: row
    for row in (
        WasherSize("M3", 3, 3.2, 7, 0.5),
        WasherSize("M4", 4, 4.3, 9, 0.8),
        WasherSize("M5", 5, 5.3, 10, 1.0),
        WasherSize("M6", 6, 6.4, 12, 1.6),
        WasherSize("M8", 8, 8.4, 16, 1.6),
        WasherSize("M10", 10, 10.5, 20, 2.0),
        WasherSize("M12", 12, 13.0, 24, 2.5),
        WasherSize("M16", 16, 17.0, 30, 3.0),
        WasherSize("M20", 20, 21.0, 37, 3.0),
        WasherSize("M24", 24, 25.0, 44, 4.0),
        WasherSize("M30", 30, 31.0, 56, 4.0),
    )
}

SOCKET_SCREWS: dict[str, SocketScrewSize] = {
    row.designation: row
    for row in (
        SocketScrewSize("M3", 3, 5.5, 3.0, 2.5),
        SocketScrewSize("M4", 4, 7, 4.0, 3.0),
        SocketScrewSize("M5", 5, 8.5, 5.0, 4.0),
        SocketScrewSize("M6", 6, 10, 6.0, 5.0),
        SocketScrewSize("M8", 8, 13, 8.0, 6.0),
        SocketScrewSize("M10", 10, 16, 10.0, 8.0),
        SocketScrewSize("M12", 12, 18, 12.0, 10.0),
        SocketScrewSize("M16", 16, 24, 16.0, 14.0),
        SocketScrewSize("M20", 20, 30, 20.0, 17.0),
        SocketScrewSize("M24", 24, 36, 24.0, 19.0),
        SocketScrewSize("M30", 30, 45, 30.0, 22.0),
    )
}

#: Lengths offered for socket head cap screws, per designation.
SOCKET_SCREW_LENGTHS: dict[str, tuple[float, ...]] = {
    "M3": (6, 8, 10, 12, 16, 20),
    "M4": (8, 10, 12, 16, 20, 25),
    "M5": (10, 12, 16, 20, 25, 30),
    "M6": (16, 20, 25, 30, 40),
    "M8": (20, 25, 30, 40, 50),
    "M10": (25, 30, 40, 50, 60),
    "M12": (30, 40, 50, 60, 80),
    "M16": (40, 50, 60, 80, 100),
    "M20": (50, 60, 80, 100, 120),
    "M24": (60, 80, 100, 120, 150),
    "M30": (80, 100, 120, 150, 180),
}


def _designation_key(designation: str) -> float:
    """Sort key that reads "M3, M4, ... M30" rather than "M10, M12, ... M3".

    A plain string sort puts M10 ahead of M3, which turns the suggestion in a
    lookup error into a wall of numbers in an order nobody scans.
    """
    return float(designation[1:])


def _lookup(table: dict[str, object], designation: str, table_name: str):
    try:
        return table[designation]
    except KeyError:
        known = ", ".join(sorted(table, key=_designation_key))
        raise KeyError(
            f"{designation!r} is not in {table_name}; known sizes: {known}"
        ) from None


def hex_bolt(designation: str) -> HexBoltSize:
    return _lookup(HEX_BOLTS, designation.upper(), "GB/T 5783 hex bolts")


def hex_nut(designation: str) -> HexNutSize:
    return _lookup(HEX_NUTS, designation.upper(), "GB/T 6170 hex nuts")


def washer(designation: str) -> WasherSize:
    return _lookup(WASHERS, designation.upper(), "GB/T 97.1 washers")


def nut_bore(designation: str) -> float:
    """The through hole of a hex nut, in millimetres.

    Models here are threadless on purpose (see geometry.tap_drill), so the bore
    cannot be the tap drill 0.85*d: that diameter leaves material for a thread
    that is never cut, and it is smaller than the bolt the nut is catalogued
    for, which makes every nut refuse its own bolt.  The plain washer's inner
    diameter is the clearance series this table already carries, and it is what
    a nut is drilled to, so the two share a bore.
    """
    return washer(designation).inner


def socket_screw(designation: str) -> SocketScrewSize:
    return _lookup(
        SOCKET_SCREWS, designation.upper(), "GB/T 70.1 socket head cap screws"
    )


def summary() -> str:
    """Human-readable catalogue listing, used by `swforge catalog`."""
    lines = [
        "GB/T 5783 hex bolts (designation, d, s, k, lengths)",
        *(
            f"  {row.designation:<4} d={row.d:<5g} s={row.s:<5g} k={row.k:<5g} "
            f"L={'/'.join(str(int(v)) for v in row.lengths)}"
            for row in HEX_BOLTS.values()
        ),
        "GB/T 6170 hex nuts (designation, d, s, m)",
        *(
            f"  {row.designation:<4} d={row.d:<5g} s={row.s:<5g} m={row.m:<5g}"
            for row in HEX_NUTS.values()
        ),
        "GB/T 97.1 plain washers (designation, d, inner, outer, t)",
        *(
            f"  {row.designation:<4} d={row.d:<5g} id={row.inner:<5g} "
            f"od={row.outer:<5g} t={row.t:<4g}"
            for row in WASHERS.values()
        ),
        "GB/T 70.1 socket head cap screws (designation, d, dk, k, socket)",
        *(
            f"  {row.designation:<4} d={row.d:<5g} dk={row.dk:<5g} k={row.k:<5g} "
            f"s={row.socket:<5g}"
            for row in SOCKET_SCREWS.values()
        ),
    ]
    return "\n".join(lines)
