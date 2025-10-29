"""Basic tests for HotPin WebServer."""
import asyncio
import os
from hotpin.config import Config
from hotpin.utils import create_logger
from hotpin.session_manager import session_manager
from hotpin.stt_worker import stt_worker
from hotpin.llm_client import llm_client
from hotpin.image_handler import image_handler
from hotpin.tts_worker import tts_worker

logger = create_logger(__name__)

def test_config_loading():
    """Test that configuration loads properly."""
    print("Testing configuration loading...")
    
    # Check that required config values exist
    assert hasattr(Config, 'WS_TOKEN'), "WS_TOKEN should be in config"
    assert hasattr(Config, 'GROQ_STT_MODEL'), "GROQ_STT_MODEL should be in config"
    assert hasattr(Config, 'GROQ_API_KEY'), "GROQ_API_KEY should be in config"
    
    print("✓ Configuration loaded successfully")


def test_components_initialization():
    """Test that components initialize properly."""
    print("Testing component initialization...")
    
    # Check that required components exist
    assert session_manager is not None, "Session manager should be initialized"
    assert stt_worker is not None, "STT worker should be initialized"
    assert llm_client is not None, "LLM client should be initialized"
    assert image_handler is not None, "Image handler should be initialized"
    assert tts_worker is not None, "TTS worker should be initialized"
    
    print("✓ All components initialized successfully")


def test_session_management():
    """Test basic session management."""
    print("Testing session management...")
    
    # Create a test session
    session = session_manager.create_session("test_session_123")
    assert session is not None, "Session should be created"
    assert session.session_id == "test_session_123", "Session ID should match"
    
    # Verify session is in manager
    retrieved_session = session_manager.get_session("test_session_123")
    assert retrieved_session is not None, "Session should be retrievable"
    
    # Test session state changes
    from hotpin.session_manager import SessionState
    assert session.state == session.state.DISCONNECTED, "Session should start as disconnected"
    
    session.update_state(SessionState.IDLE)
    assert session.state == SessionState.IDLE, "Session state should update"
    
    # Clean up
    session_manager.remove_session("test_session_123")
    
    print("✓ Session management working correctly")


def test_audio_validation():
    """Test audio validation utilities."""
    print("Testing audio validation...")
    
    from hotpin.utils import validate_audio_chunk
    
    # Test valid PCM data (16-bit, multiple of 2 bytes)
    valid_chunk = b"\x00\x00" * 100  # 200 bytes, valid PCM16
    assert validate_audio_chunk(valid_chunk), "Valid PCM chunk should pass validation"
    
    # Test invalid PCM data (odd number of bytes)
    invalid_chunk = b"\x00" * 101  # 101 bytes, invalid
    assert not validate_audio_chunk(invalid_chunk), "Invalid PCM chunk should fail validation"
    
    print("✓ Audio validation working correctly")


async def run_all_tests():
    """Run all basic tests."""
    print("Starting HotPin WebServer basic tests...\n")
    
    test_config_loading()
    test_components_initialization()
    test_session_management()
    test_audio_validation()
    
    print("\n✓ All basic tests passed!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())