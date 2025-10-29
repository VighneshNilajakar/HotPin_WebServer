"""Audio ingestor for HotPin WebServer."""
import asyncio
import json
import os
import time
from typing import Dict, Optional, Callable
from collections import deque
from .config import Config
from .utils import create_logger, create_temp_file, create_wave_file, estimate_audio_duration
from .session_manager import Session, SessionState

logger = create_logger(__name__)

class AudioIngestor:
    """Handles audio chunk ingestion, buffering, and temporary file management."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        self.chunk_callbacks: Dict[str, Callable] = {}  # session_id -> callback function
        self.recording_start_times: Dict[str, float] = {}  # session_id -> start time
    
    async def start_recording_session(self, session: Session):
        """Initialize a new recording session."""
        # Create a temporary file for this recording
        temp_filename = f"audio_{session.session_id}_{int(time.time())}.raw"
        temp_path = os.path.join(Config.TEMP_DIR, temp_filename)
        
        session.audio_buffer.temp_file_path = temp_path
        session.audio_buffer.chunks_received = 0
        session.audio_buffer.total_bytes = 0
        session.audio_buffer.sequence_numbers = []
        
        # Initialize file for writing
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, 'wb') as f:
            pass  # Create empty file
        
        self.recording_start_times[session.session_id] = time.time()
        session.update_disk_usage()
        
        self.logger.info(f"Started recording session for {session.session_id}, temp file: {temp_path}")
    
    async def ingest_chunk(self, session: Session, seq: int, chunk_data: bytes) -> bool:
        """Ingest an audio chunk and append it to the session's buffer."""
        if not session.audio_buffer.temp_file_path:
            self.logger.error(f"No active recording for session {session.session_id}")
            return False
        
        try:
            # Validate chunk
            if not chunk_data or len(chunk_data) == 0:
                self.logger.warning(f"Received empty chunk for session {session.session_id}")
                return False
            
            if not self._validate_chunk_order(session, seq):
                self.logger.warning(f"Chunk sequence out of order for session {session.session_id}: expected {session.expected_seq}, got {seq}")
                # For now, just update expected sequence to handle gaps
                if seq > session.expected_seq:
                    session.expected_seq = seq + 1
                    session.log_event("chunk_gap", {"expected": session.expected_seq - 1, "received": seq})
            
            # Write chunk to temp file
            with open(session.audio_buffer.temp_file_path, 'ab') as f:
                f.write(chunk_data)
            
            # Update session buffer stats
            session.audio_buffer.chunks_received += 1
            session.audio_buffer.total_bytes += len(chunk_data)
            session.audio_buffer.sequence_numbers.append(seq)
            
            # Update expected sequence number
            if seq == session.expected_seq:
                session.expected_seq += 1
            elif seq >= session.expected_seq:
                session.expected_seq = seq + 1
            
            # Update disk usage
            session.update_disk_usage()
            
            # Check disk quota
            if session.is_disk_quota_exceeded():
                self.logger.warning(f"Session {session.session_id} exceeded disk quota: {session.disk_usage_bytes} bytes")
                return False
            
            # Log chunk receipt periodically
            if session.audio_buffer.chunks_received % 10 == 0:
                self.logger.debug(f"Session {session.session_id}: received {session.audio_buffer.chunks_received} chunks, {session.audio_buffer.total_bytes} bytes")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error ingesting chunk for session {session.session_id}: {e}")
            return False
    
    def _validate_chunk_order(self, session: Session, seq: int) -> bool:
        """Validate that the chunk sequence is in order."""
        # For the first chunk, accept any sequence number
        if session.audio_buffer.chunks_received == 0:
            session.expected_seq = seq
            return True
        
        # Check if sequence number is acceptable
        # Accept if it's the expected sequence or a reasonable gap (for lost packets)
        max_acceptable_gap = 5  # Allow up to 5 chunks gap
        if seq == session.expected_seq:
            return True
        elif seq > session.expected_seq and (seq - session.expected_seq) <= max_acceptable_gap:
            return True
        else:
            return False
    
    async def finalize_recording(self, session: Session) -> Optional[str]:
        """Finalize the recording and return the file path."""
        if not session.audio_buffer.temp_file_path or not os.path.exists(session.audio_buffer.temp_file_path):
            self.logger.error(f"No recording file found for session {session.session_id}")
            return None
        
        # Get duration of recording
        duration = estimate_audio_duration(
            self.get_recording_data(session),
            sample_rate=16000,
            sample_width=2,
            channels=1
        )
        
        self.logger.info(f"Finalized recording for session {session.session_id}: {duration:.2f}s, {session.audio_buffer.total_bytes} bytes")
        
        # Log recording stats
        session.log_event("recording_finalized", {
            "duration_seconds": duration,
            "total_chunks": session.audio_buffer.chunks_received,
            "total_bytes": session.audio_buffer.total_bytes
        })
        
        return session.audio_buffer.temp_file_path
    
    def get_recording_data(self, session: Session) -> bytes:
        """Get the raw recording data from the temp file."""
        if not session.audio_buffer.temp_file_path or not os.path.exists(session.audio_buffer.temp_file_path):
            return b""
        
        with open(session.audio_buffer.temp_file_path, 'rb') as f:
            return f.read()
    
    def get_recording_duration(self, session: Session) -> float:
        """Get the duration of the current recording."""
        if not session.audio_buffer.temp_file_path:
            return 0.0
        
        audio_data = self.get_recording_data(session)
        return estimate_audio_duration(audio_data)
    
    async def cleanup_recording_session(self, session: Session):
        """Clean up resources for a recording session."""
        if session.audio_buffer.temp_file_path and os.path.exists(session.audio_buffer.temp_file_path):
            try:
                os.remove(session.audio_buffer.temp_file_path)
                self.logger.info(f"Cleaned up recording file: {session.audio_buffer.temp_file_path}")
            except Exception as e:
                self.logger.error(f"Failed to clean up recording file: {e}")
        
        # Clear buffer state
        session.audio_buffer.temp_file_path = ""
        session.audio_buffer.chunks_received = 0
        session.audio_buffer.total_bytes = 0
        session.audio_buffer.sequence_numbers = []
        session.expected_seq = 0
        
        # Remove from tracking
        if session.session_id in self.recording_start_times:
            del self.recording_start_times[session.session_id]