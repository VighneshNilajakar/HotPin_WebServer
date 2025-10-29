"""WebSocket connection manager for HotPin WebServer."""
import asyncio
import json
import logging
from typing import Dict, List, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect
from .config import Config
from .utils import create_logger

logger = create_logger(__name__)

class ConnectionManager:
    """Manages WebSocket connections with single-session enforcement."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}  # session_id -> websocket
        self.connection_sessions: Dict[WebSocket, str] = {}  # websocket -> session_id
        self.active_session: Optional[str] = None  # Currently active session ID
        self.max_connections: int = Config.MAX_CONNECTIONS
        
    async def connect(self, websocket: WebSocket, session_id: str) -> bool:
        """Accept a new WebSocket connection with session validation."""
        # Check if we've reached the maximum number of connections
        if len(self.active_connections) >= self.max_connections:
            await websocket.close(code=1008, reason="Too many connections")
            return False
            
        # Check if this session is already connected (single session enforcement)
        if session_id in self.active_connections:
            await websocket.close(code=1013, reason="Session already connected")
            return False
            
        # Check if there's already an active session and single session mode is on
        if self.active_session is not None and self.max_connections == 1:
            await websocket.close(code=1013, reason="Another session is already active")
            return False
            
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self.connection_sessions[websocket] = session_id
        self.active_session = session_id
        
        logger.info(f"New connection established for session {session_id}")
        return True
        
    def disconnect(self, websocket: WebSocket):
        """Handle WebSocket disconnection."""
        session_id = self.connection_sessions.get(websocket)
        if session_id:
            del self.active_connections[session_id]
            del self.connection_sessions[websocket]
            
            # If this was the active session, clear it
            if self.active_session == session_id:
                self.active_session = None
                
            logger.info(f"Connection disconnected for session {session_id}")
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific WebSocket connection."""
        try:
            await websocket.send_text(json.dumps(message))
        except WebSocketDisconnect:
            self.disconnect(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        disconnected = []
        for session_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except WebSocketDisconnect:
                disconnected.append(websocket)
        
        # Clean up disconnected websockets
        for websocket in disconnected:
            self.disconnect(websocket)
    
    def get_session_id(self, websocket: WebSocket) -> Optional[str]:
        """Get the session ID for a WebSocket connection."""
        return self.connection_sessions.get(websocket)
    
    def is_session_active(self, session_id: str) -> bool:
        """Check if a specific session is currently connected."""
        return session_id in self.active_connections
    
    def get_active_session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self.active_connections)

# Global connection manager instance
manager = ConnectionManager()