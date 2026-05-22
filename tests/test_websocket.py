import asyncio

from app.api.websocket import ConnectionManager


class _FakeSocket:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.messages = []

    async def send_json(self, message):
        if self.should_fail:
            raise RuntimeError("send failed")
        self.messages.append(message)


def test_websocket_broadcast_cleans_failed_connections():
    manager = ConnectionManager()
    alive = _FakeSocket()
    dead = _FakeSocket(should_fail=True)
    manager.active_connections = [alive, dead]

    asyncio.run(manager.broadcast({"type": "ping"}))

    assert manager.active_connections == [alive]
    assert alive.messages == [{"type": "ping"}]
