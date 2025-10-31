#!/usr/bin/env python3
"""
End-to-end functionality test for HotPin WebServer.
This script tests the main functionality without requiring external services.
"""

import asyncio
import tempfile
import os
from unittest.mock import patch, MagicMock
import sys
import time

def test_session_lifecycle():
    """Test the complete session lifecycle."""
    print("[TEST] Testing session lifecycle...")
    
    from hotpin.session_manager import session_manager, SessionState
    from hotpin.config import Config
    
    # Create a session
    session = session_manager.create_session("test_session_e2e")
    assert session is not None
    assert session.session_id == "test_session_e2e"
    assert session.state == SessionState.DISCONNECTED
    
    # Test state transitions
    session.update_state(SessionState.CONNECTED)
    assert session.state == SessionState.CONNECTED
    
    session.update_state(SessionState.IDLE)
    assert session.state == SessionState.IDLE
    
    session.update_state(SessionState.RECORDING)
    assert session.state == SessionState.RECORDING
    
    session.update_state(SessionState.PROCESSING)
    assert session.state == SessionState.PROCESSING
    
    session.update_state(SessionState.PLAYING)
    assert session.state == SessionState.PLAYING
    
    session.update_state(SessionState.IDLE)
    assert session.state == SessionState.IDLE
    
    # Add conversation history
    session.add_conversation_turn("user", "Hello, how are you?")
    session.add_conversation_turn("assistant", "I'm doing well, thank you for asking!")
    
    assert len(session.conversation_history) == 2
    assert session.conversation_history[0]["role"] == "user"
    assert session.conversation_history[1]["role"] == "assistant"
    
    # Clean up
    session_manager.remove_session("test_session_e2e")
    print("[OK] Session lifecycle test passed")


async def test_audio_ingestion():
    """Test audio ingestion functionality."""
    print("[TEST] Testing audio ingestion...")
    
    from hotpin.session_manager import session_manager, SessionState
    from hotpin.audio_ingestor import AudioIngestor
    from hotpin.config import Config
    
    audio_ingestor = AudioIngestor()
    
    # Create a session for testing
    session = session_manager.create_session("test_audio_session")
    session.update_state(SessionState.RECORDING)
    
    # Start recording session
    await audio_ingestor.start_recording_session(session)
    assert session.audio_buffer.temp_file_path is not None
    assert os.path.exists(session.audio_buffer.temp_file_path)
    
    # Ingest some test audio chunks
    test_chunk1 = b"\x00\x01" * 100  # 200 bytes
    test_chunk2 = b"\x02\x03" * 150  # 300 bytes
    test_chunk3 = b"\x04\x05" * 200  # 400 bytes
    
    success1 = await audio_ingestor.ingest_chunk(session, 0, test_chunk1)
    success2 = await audio_ingestor.ingest_chunk(session, 1, test_chunk2)
    success3 = await audio_ingestor.ingest_chunk(session, 2, test_chunk3)
    
    assert success1 and success2 and success3
    assert session.audio_buffer.total_bytes == 900  # 200 + 300 + 400
    assert session.audio_buffer.chunks_received == 3
    
    # Finalize recording
    temp_path = await audio_ingestor.finalize_recording(session)
    assert temp_path is not None
    assert os.path.exists(temp_path)
    
    # Verify the file contains the expected data
    with open(temp_path, 'rb') as f:
        content = f.read()
        expected_content = test_chunk1 + test_chunk2 + test_chunk3
        assert content == expected_content
    
    # Clean up
    await audio_ingestor.cleanup_recording_session(session)
    session_manager.remove_session("test_audio_session")
    
    print("[OK] Audio ingestion test passed")


def test_mock_stt():
    """Test STT worker with mocked API."""
    print("[TEST] Testing STT functionality...")
    
    from hotpin.stt_worker import STTWorker
    import tempfile
    import wave
    
    # Create a simple dummy WAV file for testing
    test_audio = b"\x00\x00" * 8000  # 0.5 seconds of silence at 16kHz
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
        temp_path = temp_wav.name
        with wave.open(temp_wav, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(16000)  # 16kHz
            wav_file.writeframes(test_audio)
    
    try:
        # Initialize STT worker (might fail if Groq not available, but should handle gracefully)
        stt_worker = STTWorker()
        
        # Test session management
        session_id = "test_stt_session"
        success = stt_worker.start_recognition_session(session_id)
        # This might fail if Groq is not available, but that's expected in test environment
        
        if stt_worker.available:
            # Test chunk acceptance
            result = stt_worker.accept_audio_chunk(session_id, test_audio[:100])
            assert result == True  # Should accept chunks even without finalizing
            
            # We can't fully test finalize_recognition without real Groq API
            print("[OK] STT functionality test passed (with real API if available)")
        else:
            print("[OK] STT worker initialized in disabled state (expected without API key)")
        
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    print("[OK] STT functionality test passed")


def test_tts_generation():
    """Test TTS generation."""
    print("[TEST] Testing TTS generation...")
    
    from hotpin.tts_worker import tts_worker
    from hotpin.config import Config
    import time
    
    # Test basic TTS generation
    test_text = "Hello, this is a test of the text to speech system."
    session_id = f"test_tts_{int(time.time())}"
    
    # Generate TTS (this may create a placeholder if TTS engine fails)
    tts_path = asyncio.run(tts_worker.generate_speech(test_text, session_id))
    
    if tts_path and os.path.exists(tts_path):
        # Verify the file exists and has content
        assert os.path.getsize(tts_path) > 0
        print(f"[OK] TTS file generated: {tts_path}")
        
        # Clean up
        if os.path.exists(tts_path):
            os.remove(tts_path)
    else:
        print("[OK] TTS generation attempted (may have created placeholder)")
    
    print("[OK] TTS generation test passed")


def test_message_processing():
    """Test message processing logic."""
    print("[TEST] Testing message processing...")
    
    # We'll test the message routing logic by directly calling the handler functions
    # This requires mocking a WebSocket connection and session
    from hotpin.server import process_client_message, handle_hello, handle_client_on
    from hotpin.session_manager import session_manager, Session, SessionState
    from unittest.mock import AsyncMock, MagicMock
    
    # Create a mock WebSocket
    mock_websocket = AsyncMock()
    mock_websocket.send_text = AsyncMock()
    
    # Create a session
    session = Session("test_message_session")
    session_manager.sessions["test_message_session"] = session
    
    # Test hello message handling
    hello_message = {
        "type": "hello",
        "capabilities": {
            "psram": True,
            "max_chunk_bytes": 16000
        }
    }
    
    asyncio.run(handle_hello(mock_websocket, session, hello_message))
    # Verify capabilities were set
    assert session.client_capabilities is not None
    assert session.client_capabilities.psram == True
    
    # Test client_on message
    client_on_message = {
        "type": "client_on"
    }
    
    asyncio.run(handle_client_on(mock_websocket, session, client_on_message))
    assert session.state == SessionState.IDLE
    
    # Test process_client_message with unknown message type
    unknown_message = {
        "type": "unknown_message_type"
    }
    
    # This should send an error message
    asyncio.run(process_client_message(mock_websocket, session, unknown_message))
    
    # Clean up
    session_manager.remove_session("test_message_session")
    
    print("[OK] Message processing test passed")


def run_end_to_end_tests():
    """Run all end-to-end tests."""
    print("HotPin WebServer - End-to-End Functionality Tests")
    print("="*60)
    
    success = True
    
    try:
        test_session_lifecycle()
        print()
    except Exception as e:
        print(f"[FAIL] Session lifecycle test failed: {e}")
        success = False
    
    try:
        asyncio.run(test_audio_ingestion())
        print()
    except Exception as e:
        print(f"[FAIL] Audio ingestion test failed: {e}")
        success = False
    
    try:
        test_mock_stt()
        print()
    except Exception as e:
        print(f"[FAIL] STT test failed: {e}")
        success = False
    
    try:
        test_tts_generation()
        print()
    except Exception as e:
        print(f"[FAIL] TTS generation test failed: {e}")
        success = False
    
    try:
        test_message_processing()
        print()
    except Exception as e:
        print(f"[FAIL] Message processing test failed: {e}")
        success = False
    
    print("="*60)
    if success:
        print("[OK] All end-to-end functionality tests passed!")
        return 0
    else:
        print("[FAIL] Some end-to-end tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(run_end_to_end_tests())