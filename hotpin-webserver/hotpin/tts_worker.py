"""TTS worker for HotPin WebServer using pyttsx3."""
import asyncio
import os
import threading
import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import pyttsx3

from .config import Config
from .utils import create_logger

logger = create_logger(__name__)

class TTSWorker:
    """Handles text-to-speech conversion using pyttsx3."""
    
    def __init__(self):
        self.logger = create_logger(self.__class__.__name__)
        self.executor = ThreadPoolExecutor(max_workers=1)  # Single worker to avoid audio conflicts
        self.engine = None
        self._engine_lock = threading.Lock()
        self._init_tts_engine()
    
    def _init_tts_engine(self):
        """Initialize the TTS engine."""
        try:
            # Initialize TTS engine
            self.engine = pyttsx3.init()
            
            # Set properties for appropriate audio format
            # Note: pyttsx3 generates audio internally, we'll convert to WAV afterward
            self.engine.setProperty('rate', 200)  # Speed of speech
            self.engine.setProperty('volume', 0.9)  # Volume level (0.0 to 1.0)
            
            self.logger.info("TTS engine initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize TTS engine: {e}")
            # Continue without TTS but log the error
    
    async def generate_speech(self, text: str, session_id: str) -> Optional[str]:
        """Generate speech from text and save to a temp file."""
        if not self.engine:
            self.logger.error("TTS engine not available")
            return await self._generate_placeholder_async(text, session_id)
        
        try:
            # Create a temp file for the audio
            temp_filename = f"tts_{session_id}_{int(time.time())}.wav"
            temp_path = os.path.join(Config.TEMP_DIR, temp_filename)
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            
            # Generate speech in a thread-safe manner
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                self.executor, 
                self._generate_speech_sync, 
                text, 
                temp_path
            )
            
            if success and os.path.exists(temp_path):
                # Verify the file was created properly
                if os.path.getsize(temp_path) > 0:
                    self.logger.info(f"TTS generated successfully: {temp_path}")
                    return temp_path
                else:
                    self.logger.error(f"TTS file is empty: {temp_path}")
                    return await self._generate_placeholder_async(text, session_id)
            else:
                self.logger.error(f"TTS generation failed for: {temp_path}")
                return await self._generate_placeholder_async(text, session_id)
                
        except Exception as e:
            self.logger.error(f"Error generating TTS for session {session_id}: {e}")
            return await self._generate_placeholder_async(text, session_id)
    
    def _generate_speech_sync(self, text: str, output_path: str) -> bool:
        """Synchronous TTS generation function to run in a separate thread."""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with self._engine_lock:
                if not self.engine:
                    return False
                # Queue the utterance and block until it has been written
                token = self.engine.connect('finished-utterance', lambda name, completed: None)
                self.engine.save_to_file(text, output_path)
                self.engine.runAndWait()

                if token is not None:
                    self.engine.disconnect(token)

            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            self.logger.error(f"Error in synchronous TTS generation: {e}")
            return False

    async def _generate_placeholder_async(self, text: str, session_id: str) -> Optional[str]:
        """Fallback placeholder audio when TTS is unavailable."""
        loop = asyncio.get_running_loop()
        temp_filename = f"tts_placeholder_{session_id}_{int(time.time())}.wav"
        temp_path = os.path.join(Config.TEMP_DIR, temp_filename)
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        success = await loop.run_in_executor(self.executor, self._generate_placeholder_wave, text, temp_path)
        if success:
            return temp_path
        return None

    def _generate_placeholder_wave(self, text: str, output_path: str) -> bool:
        """Generate a short placeholder tone as a fallback."""
        try:
            import math
            import struct
            import wave

            sample_rate = 16000
            duration = min(max(len(text) * 0.05, 1.0), 5.0)
            num_samples = int(duration * sample_rate)
            amplitude = 8000
            frequency = 440

            with wave.open(output_path, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)

                for i in range(num_samples):
                    value = int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
                    wav_file.writeframes(struct.pack('<h', value))

            self.logger.warning("Generated placeholder TTS audio due to engine failure")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to generate placeholder audio: {exc}")
            return False
    
    async def get_audio_duration(self, file_path: str) -> float:
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

# Global TTS worker instance
tts_worker = TTSWorker()