from typing import List
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
import logging

logger = logging.getLogger(__name__)

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
        dead_connections = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message to client: {e}")
                dead_connections.append(connection)

        # 清理失败的连接
        for conn in dead_connections:
            self.disconnect(conn)

        if dead_connections:
            logger.info(f"Cleaned up {len(dead_connections)} dead connections")


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
