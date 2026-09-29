from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any

import httpx

from ._types import UmamiConfig

log = logging.getLogger("ambient_telemetry")

_MAX_QUEUE = 1000
_MAX_ATTEMPTS = 4


class UmamiTransport:
    """Fire-and-forget Umami sender.

    Calls only enqueue. A daemon thread posts to ``{host}/api/send`` with bounded
    retries, so telemetry never blocks or fails a request.
    """

    def __init__(
        self,
        cfg: UmamiConfig,
        client: httpx.Client | None = None,
        *,
        timeout: float = 5.0,
        base_delay: float = 0.5,
    ) -> None:
        self._cfg = cfg
        self._client = client or httpx.Client(timeout=timeout)
        self._base_delay = base_delay
        self._cache_token: str | None = None
        self._queue: queue.Queue[tuple[bytes, int]] = queue.Queue(maxsize=_MAX_QUEUE)
        self._thread = threading.Thread(
            target=self._run, name="ambient-telemetry-umami", daemon=True
        )
        self._thread.start()

    def event(
        self,
        *,
        url: str,
        name: str | None = None,
        data: dict[str, Any] | None = None,
        title: str | None = None,
        distinct_id: str | None = None,
    ) -> None:
        self._enqueue(
            "event",
            {"url": url, "name": name, "data": data, "title": title, "id": distinct_id},
        )

    def identify(
        self, distinct_id: str, data: dict[str, Any] | None = None, url: str = "/"
    ) -> None:
        self._enqueue("identify", {"url": url, "id": distinct_id, "data": data})

    def flush(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return self._queue.unfinished_tasks == 0

    def _enqueue(self, kind: str, fields: dict[str, Any]) -> None:
        payload = {
            "website": self._cfg.website_id,
            "hostname": self._cfg.hostname,
            **{k: v for k, v in fields.items() if v is not None},
        }
        body = json.dumps({"type": kind, "payload": payload}, default=str).encode()
        try:
            self._queue.put_nowait((body, 0))
        except queue.Full:
            log.debug("umami queue full; dropping event")

    def _run(self) -> None:
        while True:
            body, attempts = self._queue.get()
            try:
                self._send(body)
            except Exception as exc:  # noqa: BLE001 - telemetry must never raise
                attempts += 1
                if attempts < _MAX_ATTEMPTS:
                    time.sleep(self._base_delay * 2 ** (attempts - 1))
                    try:
                        self._queue.put_nowait((body, attempts))
                    except queue.Full:
                        pass
                else:
                    log.debug("umami send failed permanently: %s", exc)
            finally:
                self._queue.task_done()

    def _send(self, body: bytes) -> None:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self._cfg.user_agent,
        }
        if self._cache_token:
            headers["x-umami-cache"] = self._cache_token
        res = self._client.post(
            f"{self._cfg.host.rstrip('/')}/api/send", content=body, headers=headers
        )
        if res.status_code >= 400:
            # 4xx (other than 429) will never succeed on retry: drop instead of looping.
            if res.status_code < 500 and res.status_code != 429:
                return
            raise RuntimeError(f"umami {res.status_code}")
        try:
            token = res.json().get("cache")
        except ValueError:
            token = None
        if token:
            self._cache_token = token
