"""STT worker for HotPin WebServer using Vosk."""
import json
import multiprocessing
from typing import Dict, Optional, Callable, Any
from vosk import Model, KaldiRecognizer, SetLogLevel
from .config import Config
from .utils import create_logger, calculate_rms_energy

logger = create_logger(__name__)

# Set Vosk log level to reduce verbosity (0 = no logging, -1 = default)
SetLogLevel(0)

class STTWorker:
    """Handles STT processing in a separate process to avoid blocking the event loop."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        self.model: Optional[Model] = None
        self.recognizers: Dict[str, KaldiRecognizer] = {}  # session_id -> recognizer
        self.partial_callbacks: Dict[str, Callable] = {}  # session_id -> callback for partial results
        self.final_callbacks: Dict[str, Callable] = {}  # session_id -> callback for final results
        self.results_queue: Optional[multiprocessing.Queue] = None
        self.input_queue: Optional[multiprocessing.Queue] = None
        self.worker_process: Optional[multiprocessing.Process] = None
        self.running = False
        
        # Validate and load model
        self._load_model()
    
    def _load_model(self):
        """Load the Vosk model at startup."""
        try:
            self.logger.info(f"Loading Vosk model from: {Config.MODEL_PATH_VOSK}")
            self.model = Model(Config.MODEL_PATH_VOSK)
            self.logger.info("Vosk model loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load Vosk model from {Config.MODEL_PATH_VOSK}: {e}")
            raise
    
    def start_recognition_session(self, session_id: str, sample_rate: int = 16000):
        """Start a new recognition session for a given session."""
        if not self.model:
            raise RuntimeError("Vosk model not loaded")
        
        # Create a new recognizer for this session
        recognizer = KaldiRecognizer(self.model, sample_rate)
        self.recognizers[session_id] = recognizer
        
        self.logger.info(f"Started STT recognition session for {session_id}")
    
    def accept_audio_chunk(self, session_id: str, audio_chunk: bytes) -> bool:
        """Accept an audio chunk for recognition."""
        if session_id not in self.recognizers:
            self.logger.error(f"No recognizer found for session {session_id}")
            return False
        
        recognizer = self.recognizers[session_id]
        
        try:
            is_final = recognizer.AcceptWaveform(audio_chunk)

            if is_final:
                result = json.loads(recognizer.Result())
                text = result.get("text", "")
                if text:
                    # Notify any registered final callback
                    if session_id in self.final_callbacks:
                        try:
                            self.final_callbacks[session_id](session_id, text)
                        except Exception as callback_error:
                            self.logger.error(f"Final callback failed for {session_id}: {callback_error}")
                    # Surface the final text through the partial callback as a stable segment
                    if session_id in self.partial_callbacks:
                        try:
                            self.partial_callbacks[session_id](session_id, text, False)
                        except Exception as callback_error:
                            self.logger.error(f"Partial callback failed for {session_id}: {callback_error}")
            else:
                partial_payload = json.loads(recognizer.PartialResult())
                partial_text = partial_payload.get("partial", "").strip()
                if partial_text and session_id in self.partial_callbacks:
                    try:
                        self.partial_callbacks[session_id](session_id, partial_text, True)
                    except Exception as callback_error:
                        self.logger.error(f"Partial callback failed for {session_id}: {callback_error}")

            return True
        except Exception as e:
            self.logger.error(f"Error processing audio chunk for session {session_id}: {e}")
            return False
    
    def finalize_recognition(self, session_id: str) -> Optional[str]:
        """Finalize recognition and return the final transcript."""
        if session_id not in self.recognizers:
            self.logger.error(f"No recognizer found for session {session_id}")
            return None
        
        recognizer = self.recognizers[session_id]
        
        try:
            # Finalize recognition
            final_result = recognizer.FinalResult()
            result = json.loads(final_result)
            text = result.get("text", "")
            
            # Log the recognized text
            if text.strip():
                self.logger.info(f"Final STT result for {session_id}: '{text}'")
            else:
                self.logger.warning(f"Empty STT result for {session_id}")
            
            # Clean up recognizer for this session
            del self.recognizers[session_id]
            
            return text
        except Exception as e:
            self.logger.error(f"Error finalizing recognition for session {session_id}: {e}")
            # Clean up recognizer even if there was an error
            if session_id in self.recognizers:
                del self.recognizers[session_id]
            return None
    
    def set_partial_callback(self, session_id: str, callback: Callable):
        """Set the callback function for partial STT results."""
        self.partial_callbacks[session_id] = callback
    
    def set_final_callback(self, session_id: str, callback: Callable):
        """Set the callback function for final STT results."""
        self.final_callbacks[session_id] = callback
    
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