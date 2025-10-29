"""Session manager for HotPin WebServer."""
import asyncio
import json
import time
import os
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from .config import Config
from .utils import create_logger, generate_session_id, create_temp_file

logger = create_logger(__name__)

class SessionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    PLAYING = "playing"
    CAMERA_UPLOADING = "camera_uploading"
    STALLED = "stalled"
    SHUTDOWN = "shutdown"

@dataclass
class ClientCapabilities:
    psram: bool = False
    max_chunk_bytes: int = Config.CHUNK_SIZE_BYTES

@dataclass
class AudioBuffer:
    """Represents audio buffer state."""
    chunks_received: int = 0
    total_bytes: int = 0
    sequence_numbers: List[int] = None
    temp_file_path: str = ""
    
    def __post_init__(self):
        if self.sequence_numbers is None:
            self.sequence_numbers = []

class Session:
    """Represents a single client session."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.last_activity = time.time()
        self.state = SessionState.DISCONNECTED
        self.client_capabilities: Optional[ClientCapabilities] = None
        
        # Event logging
        self.event_log: List[Dict[str, Any]] = []
        
        # Audio buffering
        self.audio_buffer = AudioBuffer()
        
        # Conversation history (limit to prevent memory growth)
        self.conversation_history: List[Dict[str, str]] = []
        self.max_history_turns = 10  # Keep last 10 turns
        
        # Image context
        self.current_image_path: Optional[str] = None
        self.current_image_metadata: Optional[Dict[str, Any]] = None
        
        # Re-record tracking
        self.rerecord_attempts = 0
        self.max_rerecord_attempts = Config.MAX_RERECORD_ATTEMPTS
        
        # Resource tracking
        self.disk_usage_bytes = 0
        self.disk_quota_bytes = Config.MAX_SESSION_DISK_MB * 1024 * 1024  # Convert to bytes
        
        # Audio sequence tracking
        self.expected_seq = 0
        
        # TTS state
        self.tts_file_path: Optional[str] = None
        self.tts_duration_ms: Optional[int] = None
        self.tts_ready = False
        
    def log_event(self, event_type: str, data: Dict[str, Any] = None):
        """Log an event to the session's event log."""
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data or {}
        }
        self.event_log.append(event)
        self.last_activity = time.time()
        
        # Limit event log size to prevent memory growth
        if len(self.event_log) > 100:
            self.event_log = self.event_log[-50:]  # Keep last 50 events
    
    def update_state(self, new_state: SessionState):
        """Update the session state and log the transition."""
        old_state = self.state
        self.state = new_state
        self.log_event("state_change", {
            "from": old_state.value,
            "to": new_state.value
        })
        logger.info(f"Session {self.session_id}: {old_state.value} -> {new_state.value}")
    
    def can_rerecord(self) -> bool:
        """Check if the session can request another re-record."""
        return self.rerecord_attempts < self.max_rerecord_attempts
    
    def increment_rerecord_attempt(self):
        """Increment the re-record attempt counter."""
        self.rerecord_attempts += 1
        self.log_event("rerecord_attempt", {"attempt_number": self.rerecord_attempts})
    
    def add_conversation_turn(self, role: str, content: str):
        """Add a conversation turn to the history."""
        turn = {
            "role": role,
            "content": content,
            "timestamp": time.time()
        }
        self.conversation_history.append(turn)
        
        # Limit history to prevent memory growth
        if len(self.conversation_history) > self.max_history_turns:
            self.conversation_history = self.conversation_history[-self.max_history_turns:]
    
    def get_conversation_context(self) -> str:
        """Get the conversation context as a string."""
        context_parts = []
        for turn in self.conversation_history:
            context_parts.append(f"{turn['role']}: {turn['content']}")
        return "\n".join(context_parts)
    
    def update_disk_usage(self):
        """Update the current disk usage based on temp files."""
        total = 0
        
        # Calculate audio file size
        if self.audio_buffer.temp_file_path and os.path.exists(self.audio_buffer.temp_file_path):
            total += os.path.getsize(self.audio_buffer.temp_file_path)
        
        # Calculate image file size
        if self.current_image_path and os.path.exists(self.current_image_path):
            total += os.path.getsize(self.current_image_path)
        
        # Calculate TTS file size
        if self.tts_file_path and os.path.exists(self.tts_file_path):
            total += os.path.getsize(self.tts_file_path)
        
        self.disk_usage_bytes = total
        logger.debug(f"Session {self.session_id} disk usage: {total} bytes")
    
    def is_disk_quota_exceeded(self) -> bool:
        """Check if disk quota has been exceeded."""
        return self.disk_usage_bytes > self.disk_quota_bytes
    
    def cleanup_temp_files(self):
        """Clean up all temporary files associated with this session."""
        files_to_remove = [
            self.audio_buffer.temp_file_path,
            self.current_image_path,
            self.tts_file_path
        ]
        
        for file_path in files_to_remove:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Removed temp file: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to remove temp file {file_path}: {e}")
        
        # Reset file paths
        self.audio_buffer.temp_file_path = ""
        self.current_image_path = None
        self.tts_file_path = None
        self.disk_usage_bytes = 0


class SessionManager:
    """Manages all active sessions."""
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.logger = create_logger(self.__class__.__name__)
        self.cleanup_task: Optional[asyncio.Task] = None
    
    def create_session(self, session_id: Optional[str] = None) -> Session:
        """Create a new session."""
        if session_id is None:
            session_id = generate_session_id()
        
        session = Session(session_id)
        self.sessions[session_id] = session
        self.logger.info(f"Created new session: {session_id}")
        
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return self.sessions.get(session_id)
    
    def remove_session(self, session_id: str):
        """Remove a session and cleanup resources."""
        session = self.sessions.pop(session_id, None)
        if session:
            session.cleanup_temp_files()
            self.logger.info(f"Removed session: {session_id}")
    
    def get_all_sessions(self) -> Dict[str, Session]:
        """Get all active sessions."""
        return self.sessions.copy()
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions based on idle timeout."""
        current_time = time.time()
        idle_grace_period = Config.SESSION_GRACE_SEC
        
        expired_sessions = []
        for session_id, session in self.sessions.items():
            if current_time - session.last_activity > idle_grace_period:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            self.remove_session(session_id)
    
    async def start_cleanup_task(self):
        """Start a background task to periodically clean up expired sessions."""
        if self.cleanup_task is not None:
            self.cleanup_task.cancel()
        
        async def cleanup_loop():
            while True:
                try:
                    self.cleanup_expired_sessions()
                    await asyncio.sleep(60)  # Run cleanup every minute
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Error in cleanup task: {e}")
        
        self.cleanup_task = asyncio.create_task(cleanup_loop())
    
    def stop_cleanup_task(self):
        """Stop the cleanup task."""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            self.cleanup_task = None
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about all sessions."""
        active_states = {}
        total_sessions = len(self.sessions)
        
        for session in self.sessions.values():
            state = session.state.value
            active_states[state] = active_states.get(state, 0) + 1
        
        return {
            "total_sessions": total_sessions,
            "active_states": active_states,
            "timestamp": time.time()
        }

# Global session manager instance
session_manager = SessionManager()