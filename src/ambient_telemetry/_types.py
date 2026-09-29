from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Data = dict[str, Any]
Level = Literal["fatal", "error", "warning", "info", "debug"]


@dataclass(frozen=True)
class UmamiConfig:
    host: str
    website_id: str
    #: Umami has no server concept; events need a hostname to attribute them to.
    #: Use the API's own public hostname (e.g. "api.example.com").
    hostname: str
    user_agent: str = "ambient-telemetry-python"


@dataclass(frozen=True)
class GlitchTipConfig:
    dsn: str
    sample_rate: float = 1.0
    traces_sample_rate: float = 0.0


@dataclass
class TelemetryConfig:
    app: str
    environment: str
    release: str | None = None
    glitchtip: GlitchTipConfig | None = None
    umami: UmamiConfig | None = None
    #: Kill switch. False makes every call a no-op.
    enabled: bool = True
    #: Return None to drop the event.
    before_track: (
        Callable[[str, Data | None], tuple[str, Data | None] | None] | None
    ) = None
    #: Return None to drop the error.
    before_send: (
        Callable[[BaseException, Data], tuple[BaseException, Data] | None] | None
    ) = None
    debug: bool = False
    #: Extra sentry_sdk.init kwargs (integrations, etc).
    sentry_options: dict[str, Any] = field(default_factory=dict)
