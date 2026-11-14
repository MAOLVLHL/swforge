"""Stage events for long builds: one callback, one logger, no prints.

A SolidWorks build can run for minutes, and a library that says nothing for
minutes cannot be told apart from one that has hung.  The answer is not to
print from the library -- it may be embedded in a GUI, a notebook or a test --
but to hand every stage to whoever asked for the build, and to log the same
stages under the "swforge" logger for the people who only have a terminal.

Both channels are opt-in.  Nothing here writes to stdout, and nothing here
configures logging: a library that installs handlers fights with the
application's own logging configuration.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

#: Called as on_progress(stage, payload) -- stage is a dotted name such as
#: "part.built", payload is whatever numbers that stage can offer.
Progress = Callable[[str, "dict[str, Any]"], None]

_LOG = logging.getLogger("swforge")


def emit(on_progress: Progress | None, stage: str, /, **payload: Any) -> None:
    """Report one stage to the caller's callback and to the swforge logger.

    A callback that raises is reported and swallowed: the build keeps going.
    A progress sink is decoration on top of a five-minute SolidWorks run, and
    decoration that throws must not be able to destroy the work it decorates.
    """
    if on_progress is not None:
        try:
            on_progress(stage, payload)
        except Exception:  # noqa: BLE001 - the build outranks the progress report
            _LOG.warning("progress callback failed at %s", stage, exc_info=True)
    if _LOG.isEnabledFor(logging.INFO):
        detail = " ".join(f"{key}={value}" for key, value in payload.items())
        _LOG.info("%s %s", stage, detail)
