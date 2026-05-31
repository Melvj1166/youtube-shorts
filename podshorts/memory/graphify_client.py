from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("podshorts.memory")


class GraphifyClient:
    """Thin, fail-safe wrapper around the Graphify memory system.

    All methods swallow exceptions and log warnings -- memory is augmentation,
    not a hard dependency.
    """

    def __init__(
        self,
        namespace: str = "podshorts",
        endpoint: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.namespace = namespace
        self.endpoint = endpoint
        self.api_key = api_key
        self._client: Any = None
        self._available = False
        self._try_connect()

    def _try_connect(self) -> None:
        if not self.endpoint:
            return
        try:
            import httpx  # noqa: PLC0415
            self._client = httpx.Client(
                base_url=self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                timeout=5.0,
            )
            self._available = True
            logger.debug("Graphify connected: %s", self.endpoint)
        except Exception as exc:
            logger.warning("Graphify unavailable: %s", exc)

    def recall(self, query: str) -> str | None:
        """Query Graphify for prior context. Returns text or None."""
        if not self._available:
            return None
        try:
            assert self._client is not None
            resp = self._client.post(
                "/recall",
                json={"namespace": self.namespace, "query": query},
            )
            resp.raise_for_status()
            return resp.json().get("result")
        except Exception as exc:
            logger.warning("Graphify recall failed: %s", exc)
            return None

    def remember(self, key: str, value: Any) -> None:
        """Store a key-value pair in Graphify."""
        if not self._available:
            return
        try:
            assert self._client is not None
            resp = self._client.post(
                "/remember",
                json={"namespace": self.namespace, "key": key, "value": value},
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Graphify remember failed (key=%s): %s", key, exc)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass


def make_graphify_client(
    namespace: str,
    endpoint: str | None,
    api_key: str | None,
) -> GraphifyClient:
    return GraphifyClient(namespace=namespace, endpoint=endpoint, api_key=api_key)
