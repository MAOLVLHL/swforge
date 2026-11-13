"""swforge: parametric SolidWorks parts for GB fasteners and simple designs.

Importing this package never touches the SolidWorks COM API, so the analytic
half works on any platform (and in CI).  Only swforge.session needs pywin32.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
