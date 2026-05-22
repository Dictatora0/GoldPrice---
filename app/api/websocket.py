import asyncio
from typing import List
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self, max_connections: int = 100):
        self.active_connections: List[WebSocket] = []
        self.max_connections = max_connections

    async def connect(self, websocket: WebSocket) -> bool:
        """接受新的 WebSocket 连接"""
        if len(self.active_connections) >= self.max_connections:
            await websocket.close(code=1008, reason="连接数已达上限")
            logger.warning(f"Connection rejected: max connections ({self.max_connections}) reached")
            return False

        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket connection. Total: {len(self.active_connections)}")
        return True

    def disconnect(self, websocket: WebSocket):
        """断开 WebSocket 连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """广播消息到所有连接的客户端"""
        if not self.active_connections:
            return

        async def _send(connection: WebSocket):
            try:
                await connection.send_json(message)
                return True, connection
            except Exception as e:
                logger.error(f"Failed to send message to client: {e}")
                return False, connection

        results = await asyncio.gather(*(_send(connection) for connection in list(self.active_connections)))
        dead_connections = [connection for ok, connection in results if not ok]

        # 清理失败的连接
        for conn in dead_connections:
            self.disconnect(conn)

        if dead_connections:
            logger.info(f"Cleaned up {len(dead_connections)} dead connections")
        logger.info(f"Broadcast completed to {len(self.active_connections)} active connections")


# 全局连接管理器实例
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点"""
    if not await manager.connect(websocket):
        return

    try:
        while True:
            # 保持连接活跃,接收心跳消息
            data = await websocket.receive_text()
            # 可以在这里处理客户端发送的消息
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
