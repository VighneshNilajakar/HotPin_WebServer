"""Configuration module for HotPin WebServer."""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Resolve repository paths
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_BASE_DIR, os.pardir))
_DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, "model")

class Config:
    """Configuration class to store all environment variables and defaults."""
    
    # Server settings
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # WebSocket settings
    WEBSOCKET_PORT: int = int(os.getenv("WEBSOCKET_PORT", "8000"))
    WEBSOCKET_PATH: str = os.getenv("WEBSOCKET_PATH", "/ws")
    WEBSOCKET_TOKEN: str = os.getenv("WEBSOCKET_TOKEN", "mysecrettoken123")
    USE_TLS: bool = os.getenv("USE_TLS", "false").lower() == "true"
    
    # Authentication
    WS_TOKEN: str = os.getenv("WS_TOKEN", "mysecrettoken123")
    TOKEN_TTL_SEC: int = int(os.getenv("TOKEN_TTL_SEC", "3600"))
    
    # Discovery settings
    MDNS_ADVERTISE: bool = os.getenv("MDNS_ADVERTISE", "false").lower() == "true"
    HOTPIN_NAME: str = os.getenv("HOTPIN_NAME", "HotpinServer")
    UDP_BROADCAST: bool = os.getenv("UDP_BROADCAST", "false").lower() == "true"
    BROADCAST_PORT: int = int(os.getenv("BROADCAST_PORT", "50000"))
    BROADCAST_INTERVAL_SEC: int = int(os.getenv("BROADCAST_INTERVAL_SEC", "5"))
    PRINT_QR: bool = os.getenv("PRINT_QR", "false").lower() == "true"
    
    # STT settings (Groq Whisper API)
    GROQ_STT_MODEL: str = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")  # Groq Whisper model
    STT_LANGUAGE: str = os.getenv("STT_LANGUAGE", "en")  # Language for STT (ISO 639-1 code)
    STT_TEMPERATURE: float = float(os.getenv("STT_TEMPERATURE", "0.0"))  # Temperature for STT (0.0 = deterministic)
    STT_CONF_THRESHOLD: float = float(os.getenv("STT_CONF_THRESHOLD", "0.5"))  # Confidence threshold for STT
    
    # Audio settings
    CHUNK_SIZE_BYTES: int = int(os.getenv("CHUNK_SIZE_BYTES", "16000"))  # ~0.5s at 16kHz PCM16
    MIN_RECORD_DURATION_SEC: float = float(os.getenv("MIN_RECORD_DURATION_SEC", "0.5"))
    MAX_CHUNKS_PER_SEC: int = int(os.getenv("MAX_CHUNKS_PER_SEC", "10"))
    

    
    # Image settings
    MAX_IMAGE_SIZE_BYTES: int = int(os.getenv("MAX_IMAGE_SIZE_BYTES", "2097152"))  # 2MB
    IMAGE_MAX_DIMENSION: int = int(os.getenv("IMAGE_MAX_DIMENSION", "1600"))
    IMAGE_SOFT_PERCENT: int = int(os.getenv("IMAGE_SOFT_PERCENT", "20"))
    
    # Disk and resource settings
    TEMP_DIR: str = os.getenv("TEMP_DIR", "./temp")
    MAX_SESSION_DISK_MB: int = int(os.getenv("MAX_SESSION_DISK_MB", "100"))
    AUDIO_SOFT_PERCENT: int = int(os.getenv("AUDIO_SOFT_PERCENT", "80"))
    SESSION_GRACE_SEC: int = int(os.getenv("SESSION_GRACE_SEC", "30"))
    
    # Session settings
    MAX_RERECORD_ATTEMPTS: int = int(os.getenv("MAX_RERECORD_ATTEMPTS", "2"))
    MAX_CONNECTIONS: int = int(os.getenv("MAX_CONNECTIONS", "1"))
    PLAYBACK_READY_TIMEOUT_SEC: float = float(os.getenv("PLAYBACK_READY_TIMEOUT_SEC", "5.0"))
    
    # API settings
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_RETRY_ATTEMPTS: int = int(os.getenv("GROQ_RETRY_ATTEMPTS", "3"))
    GROQ_FALLBACK_MODEL: str = os.getenv("GROQ_FALLBACK_MODEL", "")
    PLAYBACK_URL_EXP_SEC: int = int(os.getenv("PLAYBACK_URL_EXP_SEC", "300"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return list of validation errors."""
        errors = []
        
        # Check if temp directory exists or can be created
        if not os.path.exists(cls.TEMP_DIR):
            try:
                os.makedirs(cls.TEMP_DIR, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create temp directory {cls.TEMP_DIR}: {str(e)}")
        
        # Validate directory is writable
        try:
            test_file = os.path.join(cls.TEMP_DIR, ".write_test")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
        except Exception:
            errors.append(f"Temp directory {cls.TEMP_DIR} is not writable")
        
        # Check if GROQ API key is provided
        if not cls.GROQ_API_KEY:
            errors.append("GROQ_API_KEY is not set in environment")
        
        # Validate port ranges
        if not (1 <= cls.PORT <= 65535):
            errors.append(f"PORT {cls.PORT} is not in valid range (1-65535)")
        
        if not (1 <= cls.WEBSOCKET_PORT <= 65535):
            errors.append(f"WEBSOCKET_PORT {cls.WEBSOCKET_PORT} is not in valid range (1-65535)")
        
        # Validate chunk size (should be reasonable)
        if cls.CHUNK_SIZE_BYTES <= 0:
            errors.append("CHUNK_SIZE_BYTES must be > 0")
        elif cls.CHUNK_SIZE_BYTES > 1024 * 1024:  # 1MB
            errors.append("CHUNK_SIZE_BYTES seems too large (> 1MB)")
        
        return errors