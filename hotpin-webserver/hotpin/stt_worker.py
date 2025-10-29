"""STT worker for HotPin WebServer using Groq Whisper API."""
import os
import tempfile
import wave
from typing import Dict, Optional, Callable, Any
from io import BytesIO

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    print("WARNING: Groq not installed. Install with: pip install groq")

from .config import Config
from .utils import create_logger, calculate_rms_energy

logger = create_logger(__name__)


class STTWorker:
    """Handles STT processing using Groq Whisper API."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        self.available = False
        
        # Check if Groq is available
        if not GROQ_AVAILABLE:
            self.logger.warning("⚠️ Groq not installed - STT will be disabled")
            self.logger.warning("Install with: pip install groq")
            self.sessions = {}
            return
        
        # Check if API key is set
        if not Config.GROQ_API_KEY:
            self.logger.warning("⚠️ GROQ_API_KEY not set - STT will be disabled")
            self.logger.warning("Set GROQ_API_KEY in .env file")
            self.sessions = {}
            return
        
        # Initialize Groq client
        try:
            self.client = Groq(api_key=Config.GROQ_API_KEY)
            self.available = True
            self.sessions: Dict[str, Dict[str, Any]] = {}
            
            self.logger.info("✅ Groq Whisper STT Worker initialized")
            self.logger.info("   Model: whisper-large-v3-turbo (fast & accurate)")
            self.logger.info("   Pricing: $0.04/min (FREE tier available)")
            self.logger.info("   Same API key as LLM - no additional setup needed")
        except Exception as e:
            self.logger.error(f"Failed to initialize Groq client: {e}")
            self.available = False
            self.sessions = {}
    
    def start_recognition_session(self, session_id: str, sample_rate: int = 16000):
        """Start a new recognition session for a given session."""
        if not self.available:
            self.logger.warning(f"STT not available - cannot start session {session_id}")
            return False
        
        try:
            # Create session to accumulate audio chunks
            self.sessions[session_id] = {
                'audio_chunks': [],
                'sample_rate': sample_rate,
                'channels': 1,  # Mono
                'sample_width': 2,  # 16-bit
            }
            self.logger.info(f"Started STT session for {session_id} (sample_rate={sample_rate}Hz)")
            return True
        
        except Exception as e:
            self.logger.error(f"Failed to start recognition session {session_id}: {e}")
            return False
    
    def accept_audio_chunk(self, session_id: str, audio_chunk: bytes) -> bool:
        """Accept an audio chunk for recognition (accumulate for final transcription)."""
        if not self.available:
            return False
            
        if session_id not in self.sessions:
            self.logger.error(f"No session found for {session_id}")
            return False
        
        try:
            # Accumulate audio chunks for final transcription
            self.sessions[session_id]['audio_chunks'].append(audio_chunk)
            return True
        except Exception as e:
            self.logger.error(f"Error processing audio chunk for session {session_id}: {e}")
            return False
    
    def finalize_recognition(self, session_id: str) -> Optional[str]:
        """Finalize recognition and return the final transcript using Groq Whisper API."""
        if not self.available:
            return None
            
        if session_id not in self.sessions:
            self.logger.error(f"No session found for {session_id}")
            return None
        
        session = self.sessions.pop(session_id)
        audio_chunks = session['audio_chunks']
        
        if not audio_chunks:
            self.logger.warning(f"No audio data in session {session_id}")
            return ""
        
        # Combine audio chunks
        audio_data = b''.join(audio_chunks)
        
        try:
            # Create temporary WAV file for Groq API
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                temp_path = temp_wav.name
                
                # Write WAV file
                with wave.open(temp_wav, 'wb') as wav_file:
                    wav_file.setnchannels(session.get('channels', 1))
                    wav_file.setsampwidth(session.get('sample_width', 2))
                    wav_file.setframerate(session.get('sample_rate', 16000))
                    wav_file.writeframes(audio_data)
            
            # Call Groq Whisper API
            try:
                with open(temp_path, 'rb') as audio_file:
                    transcription = self.client.audio.transcriptions.create(
                        file=(temp_path, audio_file.read()),
                        model="whisper-large-v3-turbo",  # Fast & accurate, $0.04/min
                        response_format="json",
                        language="en",  # Optimize for English (change if needed)
                        temperature=0.0,  # Deterministic output
                    )
                
                text = transcription.text.strip()
                
                if text:
                    self.logger.info(f"✅ Groq Whisper transcribed '{text}' for session {session_id}")
                else:
                    self.logger.warning(f"Empty transcription for session {session_id}")
                
                return text
                
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except Exception as cleanup_error:
                    self.logger.warning(f"Failed to cleanup temp file: {cleanup_error}")
        
        except Exception as e:
            self.logger.error(f"Error during Groq Whisper transcription for {session_id}: {e}")
            return None
    
    def set_partial_callback(self, session_id: str, callback: Callable):
        """Set the callback function for partial STT results (not supported with cloud API)."""
        # Groq Whisper API doesn't support streaming/partial results
        # Results are only available after finalize_recognition()
        pass
    
    def set_final_callback(self, session_id: str, callback: Callable):
        """Set the callback function for final STT results (not needed with cloud API)."""
        # With cloud API, results are returned synchronously from finalize_recognition()
        pass
    
    def check_audio_quality(self, audio_chunk: bytes) -> Dict[str, Any]:
        """Check audio quality metrics."""
        rms_energy = calculate_rms_energy(audio_chunk)
        duration = len(audio_chunk) / (2 * 16000)  # Assuming 16kHz, 16-bit audio
        
        # Simple heuristics for audio quality
        is_silent = rms_energy < 50  # Adjust threshold as needed
        is_very_loud = rms_energy > 5000  # Adjust threshold as needed
        
        return {
            "rms_energy": rms_energy,
            "duration": duration,
            "is_silent": is_silent,
            "is_very_loud": is_very_loud
        }

# Global STT worker instance
stt_worker = STTWorker()
