"""Utility functions for HotPin WebServer."""
import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from hashlib import sha256
import wave
import io

def create_logger(name: str) -> logging.Logger:
    """Create a logger with structured JSON output."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO")))
    
    # Prevent adding multiple handlers to the same logger
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

def generate_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid.uuid4())

def validate_audio_chunk(chunk: bytes, expected_size: int = None) -> bool:
    """Validate audio chunk format and size."""
    if not chunk:
        return False
    
    # Check if chunk is valid PCM16 data (multiple of 2 bytes)
    if len(chunk) % 2 != 0:
        return False
    
    # Check expected size if provided
    if expected_size and len(chunk) != expected_size:
        return False
    
    return True

def validate_image_file(image_data: bytes, max_size: int, max_dimension: int) -> Dict[str, Any]:
    """Validate image file format, size and dimensions."""
    from PIL import Image
    
    if len(image_data) > max_size:
        return {"valid": False, "error": f"Image too large: {len(image_data)} bytes > {max_size}"}
    
    try:
        # Check if it's a valid image
        img = Image.open(io.BytesIO(image_data))
        
        # Verify format is JPEG or PNG
        if img.format not in ["JPEG", "PNG"]:
            return {"valid": False, "error": f"Unsupported image format: {img.format}"}
        
        # Check dimensions
        width, height = img.size
        if width > max_dimension or height > max_dimension:
            return {"valid": False, "error": f"Image dimensions too large: {width}x{height} > {max_dimension}"}
        
        return {"valid": True, "format": img.format, "dimensions": (width, height)}
    except Exception as e:
        return {"valid": False, "error": f"Invalid image file: {str(e)}"}

def create_temp_file(prefix: str = "", suffix: str = "") -> str:
    """Create a temporary file in the configured temp directory."""
    from .config import Config
    return tempfile.mktemp(prefix=prefix, suffix=suffix, dir=Config.TEMP_DIR)

def create_wave_file(audio_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Create a WAV file from raw PCM audio data."""
    wav_buffer = io.BytesIO()
    
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)  # 16-bit = 2 bytes
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)
    
    return wav_buffer.getvalue()

def estimate_audio_duration(audio_bytes: bytes, sample_rate: int = 16000, sample_width: int = 2, channels: int = 1) -> float:
    """Estimate audio duration in seconds from raw PCM data."""
    num_samples = len(audio_bytes) // (sample_width * channels)
    duration = num_samples / sample_rate
    return duration

def calculate_rms_energy(audio_data: bytes) -> float:
    """Calculate RMS energy of audio data to detect silence/noise."""
    import struct
    
    # Convert bytes to signed 16-bit integers
    fmt = f"{len(audio_data)//2}h"
    samples = struct.unpack(fmt, audio_data)
    
    # Calculate RMS
    sum_squares = sum(s * s for s in samples)
    rms = (sum_squares / len(samples)) ** 0.5
    
    return rms

def generate_download_token(file_path: str) -> str:
    """Generate a secure token for download URLs."""
    timestamp = str(time.time())
    token_input = f"{file_path}{timestamp}{os.urandom(16).hex()}"
    return sha256(token_input.encode()).hexdigest()[:16]

def is_token_expired(timestamp: float, expiry_seconds: int) -> bool:
    """Check if a token has expired."""
    return time.time() - timestamp > expiry_seconds

def cleanup_old_files(temp_dir: str, grace_period: int) -> int:
    """Clean up files older than grace period. Return number of files cleaned up."""
    count = 0
    now = time.time()
    grace_seconds = grace_period
    
    for filename in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, filename)
        if os.path.isfile(file_path):
            # Check if file is older than grace period
            if now - os.path.getmtime(file_path) > grace_seconds:
                try:
                    os.remove(file_path)
                    count += 1
                except Exception:
                    # Log error but continue with other files
                    pass
    
    return count