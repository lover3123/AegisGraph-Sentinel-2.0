import asyncio
import time
import logging
from typing import Dict, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

class ConnectionState:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.last_heartbeat = time.time()

class WebSocketManager:
    """Manages active WebSocket connections with bounded reconnect recovery and stale cleanup."""
    
    def __init__(self, heartbeat_timeout: float = 60.0, max_reconnect_attempts: int = 5):
        self.active_connections: Dict[str, ConnectionState] = {}
        self.disconnect_history: Dict[str, list] = {}  # client_id -> list of disconnect timestamps
        self.heartbeat_timeout = heartbeat_timeout
        self.max_reconnect_attempts = max_reconnect_attempts
        self._lock = asyncio.Lock()
        
    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """
        Accept a connection safely. Enforces exponential backoff/rate limiting 
        if a client disconnects and reconnects too rapidly.
        """
        async with self._lock:
            now = time.time()
            history = self.disconnect_history.get(client_id, [])
            # Keep only disconnects from the last 60 seconds
            history = [t for t in history if now - t < 60.0]
            self.disconnect_history[client_id] = history
            
            if len(history) >= self.max_reconnect_attempts:
                # Reject connection
                logger.warning(f"Client {client_id} reconnecting too fast. Rejecting.")
                await websocket.close(code=1008, reason="Too many reconnect attempts")
                return False
                
        await websocket.accept()
        
        async with self._lock:
            self.active_connections[client_id] = ConnectionState(websocket)
            logger.info(f"Client {client_id} connected via WebSocket")
            
        return True

    async def disconnect(self, client_id: str):
        """Remove a disconnected client from active connections."""
        async with self._lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]
                self.disconnect_history.setdefault(client_id, []).append(time.time())
                logger.info(f"Client {client_id} disconnected")

    async def heartbeat(self, client_id: str):
        """Update the heartbeat timestamp for an active client."""
        async with self._lock:
            if client_id in self.active_connections:
                self.active_connections[client_id].last_heartbeat = time.time()

    async def cleanup_stale_connections(self):
        """Find and forcefully disconnect clients missing heartbeats."""
        now = time.time()
        stale_clients = []
        
        async with self._lock:
            for client_id, state in self.active_connections.items():
                if now - state.last_heartbeat > self.heartbeat_timeout:
                    stale_clients.append(client_id)
                    
        for client_id in stale_clients:
            logger.warning(f"Closing stale connection for client {client_id}")
            async with self._lock:
                state = self.active_connections.get(client_id)
                
            if state:
                try:
                    await state.websocket.close(code=1000, reason="Heartbeat timeout")
                except Exception as e:
                    logger.error(f"Error closing stale connection for {client_id}: {e}")
            
            await self.disconnect(client_id)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients without blocking."""
        async with self._lock:
            connections = list(self.active_connections.values())
            
        for state in connections:
            try:
                await state.websocket.send_json(message)
            except Exception:
                # Ignore write errors; stale cleanup loop will catch dead sockets.
                pass
