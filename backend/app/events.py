from __future__ import annotations

import asyncio
import json


class AlertBroadcaster:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[str]] = set()

    async def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._clients.discard(queue)

    async def publish(self, alert: dict) -> None:
        message = json.dumps(alert, default=str)
        for queue in tuple(self._clients):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)


alert_broadcaster = AlertBroadcaster()
