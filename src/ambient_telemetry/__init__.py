"""Ambient Labs telemetry: ``track()`` -> Umami, ``capture_error()`` -> GlitchTip (Sentry).

Same API contract as the TypeScript library. Module-level functions use one
process-wide instance; ``Telemetry`` is exposed for tests.
"""

from ._client import Telemetry, normalize_error, scrub
from ._context import Context, bind, bound
from ._context import current as current_context
from ._types import Data, GlitchTipConfig, Level, TelemetryConfig, UmamiConfig

_default = Telemetry()

init = _default.init
track = _default.track
page = _default.page
capture_error = _default.capture_error
identify = _default.identify
flush = _default.flush

__all__ = [
    "Context",
    "Data",
    "GlitchTipConfig",
    "Level",
    "Telemetry",
    "TelemetryConfig",
    "UmamiConfig",
    "bind",
    "bound",
    "capture_error",
    "current_context",
    "flush",
    "identify",
    "init",
    "normalize_error",
    "page",
    "scrub",
    "track",
]
