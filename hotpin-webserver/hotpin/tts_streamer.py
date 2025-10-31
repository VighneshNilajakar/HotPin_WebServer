"""TTS streamer for HotPin WebServer."""
import asyncio
import os
from typing import Optional, Callable
from .config import Config
from .utils import create_logger

logger = create_logger(__name__)

class TTSStreamer:
    """Handles streaming TTS audio chunks to clients."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        self.chunk_size = Config.CHUNK_SIZE_BYTES  # Use same chunk size as audio input
    
    async def stream_tts_to_client(
        self, 
        tts_file_path: str, 
        send_chunk_callback: Callable,
        session_id: str
    ) -> bool:
        """Stream TTS audio file to client in chunks."""
        if not os.path.exists(tts_file_path):
            self.logger.error(f"TTS file does not exist: {tts_file_path}")
            return False
        
        try:
            # Get file size
            file_size = os.path.getsize(tts_file_path)
            self.logger.info(f"Streaming TTS file {tts_file_path} ({file_size} bytes) to session {session_id}")
            
            # Send tts_ready message
            await send_chunk_callback({
                "type": "tts_ready",
                "duration_ms": int(self._get_audio_duration(tts_file_path) * 1000),
                "sampleRate": 16000,
                "format": "wav",
                "fileSize": file_size
            })
            
            # Stream the file in chunks
            seq = 0
            bytes_sent = 0
            
            with open(tts_file_path, 'rb') as f:
                while True:
                    chunk_data = f.read(self.chunk_size)
                    if not chunk_data:
                        break  # End of file
                    
                    # Send chunk metadata
                    chunk_meta = {
                        "type": "tts_chunk_meta",
                        "seq": seq,
                        "len_bytes": len(chunk_data)
                    }
                    try:
                        await send_chunk_callback(chunk_meta)
                        
                        # Send binary chunk data
                        await send_chunk_callback(chunk_data, binary=True)
                    except Exception as e:
                        self.logger.error(f"Error sending TTS chunk {seq} to session {session_id}: {e}")
                        return False
                    
                    seq += 1
                    bytes_sent += len(chunk_data)
                    
                    # Optional: Add small delay to prevent overwhelming the client
                    await asyncio.sleep(0.01)  # 10ms delay between chunks
            
            # Send completion message
            await send_chunk_callback({
                "type": "tts_done"
            })
            
            self.logger.info(f"Completed TTS streaming for session {session_id}, {bytes_sent} bytes sent")
            return True
            
        except Exception as e:
            self.logger.error(f"Error streaming TTS for session {session_id}: {e}")
            return False
    
    def _get_audio_duration(self, file_path: str) -> float:
        """Get the duration of an audio file in seconds."""
        try:
            import wave
            with wave.open(file_path, 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                return frames / float(rate)
        except Exception as e:
            self.logger.error(f"Error getting audio duration for {file_path}: {e}")
            return 0.0
    
    async def create_download_url(self, tts_file_path: str) -> Optional[str]:
        """Create a temporary download URL for the TTS file."""
        if not os.path.exists(tts_file_path):
            self.logger.error(f"TTS file does not exist: {tts_file_path}")
            return None
        
        try:
            import uuid
            from urllib.parse import quote
            
            # Generate a unique token for the download
            token = str(uuid.uuid4())
            
            # In a real implementation, you'd store the mapping from token to file
            # and serve the file through a download endpoint
            # For now, we'll return a placeholder URL
            
            # In a real implementation, this would be mapped to a download endpoint
            # that validates the token and serves the file
            download_url = f"/download/{token}"
            
            self.logger.info(f"Created download URL for TTS file: {download_url}")
            return download_url
            
        except Exception as e:
            self.logger.error(f"Error creating download URL for {tts_file_path}: {e}")
            return None

# Global TTS streamer instance
tts_streamer = TTSStreamer()