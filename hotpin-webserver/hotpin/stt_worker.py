"""STT worker for HotPin WebServer using PocketSphinx."""
import json
import logging
from typing import Dict, Optional, Callable, Any

try:
    from pocketsphinx import Pocketsphinx, get_model_path
    POCKETSPHINX_AVAILABLE = True
except ImportError:
    POCKETSPHINX_AVAILABLE = False
    print("WARNING: PocketSphinx not installed. Install with: pip install pocketsphinx")

from .config import Config
from .utils import create_logger, calculate_rms_energy

logger = create_logger(__name__)


class STTWorker:
    """Handles STT processing using PocketSphinx."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        
        if not POCKETSPHINX_AVAILABLE:
            raise ImportError("PocketSphinx not installed. Install with: pip install pocketsphinx")
        
        self.recognizers: Dict[str, Pocketsphinx] = {}  # session_id -> recognizer
        self.partial_callbacks: Dict[str, Callable] = {}  # session_id -> callback for partial results
        self.final_callbacks: Dict[str, Callable] = {}  # session_id -> callback for final results
        
        # Get model paths
        self.model_path = get_model_path(Config.POCKETSPHINX_MODEL)
        self.dict_path = get_model_path('cmudict-en-us.dict')
        
        self.logger.info(f"PocketSphinx STT Worker initialized")
        self.logger.info(f"Model: {self.model_path}")
        self.logger.info(f"Dictionary: {self.dict_path}")
    
    def start_recognition_session(self, session_id: str, sample_rate: int = 16000):
        """Start a new recognition session for a given session."""
        try:
            # Create PocketSphinx decoder config
            config = {
                'hmm': self.model_path,
                'dict': self.dict_path,
                'samprate': sample_rate,
                'verbose': False
            }
            
            # Create recognizer
            recognizer = Pocketsphinx(**config)
            recognizer.start_utt()  # Start utterance processing
            
            self.recognizers[session_id] = recognizer
            self.logger.info(f"Started STT recognition session for {session_id} (sample_rate={sample_rate}Hz)")
        
        except Exception as e:
            self.logger.error(f"Failed to start recognition session {session_id}: {e}")
            raise
    
    def accept_audio_chunk(self, session_id: str, audio_chunk: bytes) -> bool:
        """Accept an audio chunk for recognition."""
        if session_id not in self.recognizers:
            self.logger.error(f"No recognizer found for session {session_id}")
            return False
        
        recognizer = self.recognizers[session_id]
        
        try:
            # Process audio data
            recognizer.process_raw(audio_chunk, False, False)
            
            # Get hypothesis (partial result)
            hyp = recognizer.hyp()
            
            if hyp:
                text = hyp.hypstr
                
                # Get score and normalize to confidence (0-1 range)
                score = hyp.prob if hasattr(hyp, 'prob') else 0
                confidence = max(0.0, min(1.0, (score + 30000) / 30000))
                
                # Check if confidence meets threshold
                if confidence >= Config.STT_CONF_THRESHOLD:
                    # End utterance and get final result
                    recognizer.end_utt()
                    
                    # Notify final callback
                    if session_id in self.final_callbacks:
                        try:
                            self.final_callbacks[session_id](session_id, text)
                        except Exception as callback_error:
                            self.logger.error(f"Final callback failed for {session_id}: {callback_error}")
                    
                    # Also notify partial callback as stable segment
                    if session_id in self.partial_callbacks:
                        try:
                            self.partial_callbacks[session_id](session_id, text, False)
                        except Exception as callback_error:
                            self.logger.error(f"Partial callback failed for {session_id}: {callback_error}")
                    
                    # Restart utterance for next chunk
                    recognizer.start_utt()
                    
                    self.logger.debug(f"STT result for {session_id}: {text} (confidence: {confidence:.2f})")
                else:
                    # Send as partial result
                    if session_id in self.partial_callbacks:
                        try:
                            self.partial_callbacks[session_id](session_id, text, True)
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
            # End the current utterance
            recognizer.end_utt()
            
            # Get final hypothesis
            hyp = recognizer.hyp()
            
            text = ""
            if hyp:
                text = hyp.hypstr
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
