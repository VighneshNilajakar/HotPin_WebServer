#!/usr/bin/env python3
"""
Test script to verify that the HotPin server starts correctly after fixes.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_imports():
    """Test that all modules can be imported without errors."""
    print("Testing module imports...")
    
    try:
        from hotpin.config import Config
        print("[OK] Config module imported")
        
        # Validate configuration
        errors = Config.validate()
        if errors:
            print(f"[WARN] Configuration warnings: {errors}")
        else:
            print("[OK] Configuration validation passed")
            
    except Exception as e:
        print(f"[FAIL] Config import failed: {e}")
        return False
    
    try:
        from hotpin.utils import create_logger
        logger = create_logger("test")
        print("[OK] Utils module imported")
    except Exception as e:
        print(f"[FAIL] Utils import failed: {e}")
        return False
    
    try:
        from hotpin.session_manager import session_manager
        print("[OK] Session manager imported")
    except Exception as e:
        print(f"[FAIL] Session manager import failed: {e}")
        return False
    
    try:
        from hotpin.stt_worker import stt_worker
        print("[OK] STT worker imported")
    except Exception as e:
        print(f"[FAIL] STT worker import failed: {e}")
        return False
    
    try:
        from hotpin.llm_client import llm_client
        print("[OK] LLM client imported")
    except Exception as e:
        print(f"[FAIL] LLM client import failed: {e}")
        return False
    
    try:
        from hotpin.tts_worker import tts_worker
        print("[OK] TTS worker imported")
    except Exception as e:
        print(f"[FAIL] TTS worker import failed: {e}")
        return False
    
    try:
        from hotpin.audio_ingestor import AudioIngestor
        print("[OK] Audio ingestor imported")
    except Exception as e:
        print(f"[FAIL] Audio ingestor import failed: {e}")
        return False
    
    try:
        from hotpin.ws_manager import manager as ws_manager
        print("[OK] WebSocket manager imported")
    except Exception as e:
        print(f"[FAIL] WebSocket manager import failed: {e}")
        return False
    
    try:
        from hotpin.server import app
        print("[OK] Server app imported")
    except Exception as e:
        print(f"[FAIL] Server app import failed: {e}")
        return False
    
    print("\n[OK] All modules imported successfully!")
    return True


def test_config():
    """Test configuration values."""
    print("\nTesting configuration...")
    
    from hotpin.config import Config
    
    # Check that critical values are set appropriately
    assert Config.PORT > 0 and Config.PORT <= 65535, f"Invalid PORT: {Config.PORT}"
    assert Config.WEBSOCKET_PORT > 0 and Config.WEBSOCKET_PORT <= 65535, f"Invalid WEBSOCKET_PORT: {Config.WEBSOCKET_PORT}"
    assert Config.CHUNK_SIZE_BYTES > 0, f"Invalid CHUNK_SIZE_BYTES: {Config.CHUNK_SIZE_BYTES}"
    
    print("[OK] Configuration values are valid")
    

def test_audio_functions():
    """Test audio-related utility functions."""
    print("\nTesting audio functions...")
    
    from hotpin.utils import validate_audio_chunk, create_wave_file
    
    # Test valid PCM16 chunk
    valid_chunk = b"\x00\x00" * 100  # 200 bytes, valid PCM16
    assert validate_audio_chunk(valid_chunk) == True
    print("[OK] Valid audio chunk validation passed")
    
    # Test invalid chunk (odd number of bytes)
    invalid_chunk = b"\x00" * 101  # 101 bytes (not divisible by 2)
    assert validate_audio_chunk(invalid_chunk) == False
    print("[OK] Invalid audio chunk validation passed")
    
    # Test chunk with wrong expected size
    assert validate_audio_chunk(valid_chunk, 100) == False  # Expected 100, got 200
    print("[OK] Expected size validation passed")
    
    # Test WAV file creation
    test_audio = b"\x00\x00" * 10  # 20 bytes of test audio data
    wav_data = create_wave_file(test_audio, sample_rate=16000, channels=1, sample_width=2)
    assert len(wav_data) > 0
    print("[OK] WAV file creation passed")


def main():
    """Run all tests."""
    print("HotPin WebServer - Post-Fix Validation Tests")
    print("="*50)
    
    success = True
    
    # Test module imports
    if not test_imports():
        success = False
    
    # Test configuration
    try:
        test_config()
    except Exception as e:
        print(f"[FAIL] Config test failed: {e}")
        success = False
    
    # Test audio functions
    try:
        test_audio_functions()
    except Exception as e:
        print(f"[FAIL] Audio function test failed: {e}")
        success = False
    
    print("\n" + "="*50)
    if success:
        print("[OK] All tests passed! Server should start correctly.")
        return 0
    else:
        print("[FAIL] Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())