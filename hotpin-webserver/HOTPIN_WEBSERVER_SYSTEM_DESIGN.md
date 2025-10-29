# HotPin WebServer System Design & WebSocket Protocol Guide

## Table of Contents
1. [System Architecture Overview](#system-architecture-overview)
2. [Component Design & Implementation](#component-design--implementation)
3. [WebSocket Message Protocol](#websocket-message-protocol)
4. [Audio Processing Pipeline](#audio-processing-pipeline)
5. [Session Management](#session-management)
6. [Error Handling & Recovery](#error-handling--recovery)
7. [Implementation Guidelines for ESP32-CAM Client](#implementation-guidelines-for-esp32-cam-client)

---

## System Architecture Overview

### Core Architecture
The HotPin WebServer is designed as an authoritative, low-latency multimodal assistant server that processes audio and image inputs from the ESP32-CAM client. The system follows a server-centric architecture where the server handles all heavy processing while the client focuses on capturing inputs and executing simple commands.

### Key Design Principles
- **Client Authority**: Client reports local state but server orchestrates
- **Server Authority**: Server decides recovery, playback, and re-record requests
- **Single Active Device**: By default, only one session active (configurable)
- **No Retransmit**: Server requests re-record instead of asking for resends
- **Streaming-First**: Designed for real-time processing with disk backup

### Technology Stack
- **Runtime**: Python 3.10+ with FastAPI/uvicorn
- **WebSocket Protocol**: Real-time bidirectional communication
- **STT Engine**: Vosk speech recognition (Indian English model)
- **LLM Integration**: Groq Cloud multimodal API
- **TTS Engine**: pyttsx3 (prototype) for audio synthesis
- **Audio Format**: PCM16 LE, mono, 16 kHz

---

## Component Design & Implementation

### 1. Configuration Module (`config.py`)
The configuration module centralizes all environment variables and settings:

**Key Configuration Parameters**:
- Authentication: `WS_TOKEN`, `TOKEN_TTL_SEC`
- Audio: `CHUNK_SIZE_BYTES` (16000 bytes ≈ 0.5s at 16kHz), `MIN_RECORD_DURATION_SEC`
- STT: `VOSK_CONF_THRESHOLD` (default 0.5)
- Image: `MAX_IMAGE_SIZE_BYTES`, `IMAGE_MAX_DIMENSION`
- Resource: `MAX_SESSION_DISK_MB`, `SESSION_GRACE_SEC`
- API: `GROQ_API_KEY`, `GROQ_RETRY_ATTEMPTS`

### 2. WebSocket Manager (`ws_manager.py`)
Handles WebSocket connections with security and single-session enforcement:

```python
class ConnectionManager:
    # Manages active WebSocket connections
    # Enforces single session per server instance
    # Provides broadcast and personal messaging
```

**Key Features**:
- Token-based authentication (`WS_TOKEN` from config)
- Single-active-session enforcement
- Connection state tracking
- Message broadcasting capability

### 3. Session Manager (`session_manager.py`)
Maintains per-session state, event logging, and resource management:

```python
class Session:
    # Session state management (disconnected, idle, recording, etc.)
    # Audio buffer tracking
    # Conversation history with limits
    # Resource quotas and cleanup
```

**Session States**:
- `DISCONNECTED`: Initial state after connection
- `CONNECTED`: WebSocket established
- `IDLE`: Ready for commands
- `RECORDING`: Audio being captured
- `PROCESSING`: STT/LLM processing
- `PLAYING`: TTS streaming
- `CAMERA_UPLOADING`: Image upload in progress
- `STALLED`: Error recovery needed
- `SHUTDOWN`: Session termination

### 4. Audio Ingestor (`audio_ingestor.py`)
Handles audio chunk ingestion, buffering, and temporary file management:

```python
class AudioIngestor:
    # Manages audio buffer with deque + temporary files
    # Tracks chunk sequences and validates order
    # Enforces disk quotas
```

**Key Operations**:
- Chunk validation (PCM16 format, sequence order)
- Ring buffer implementation (deque for short-term, temp files for long recordings)
- Sequence number tracking with gap handling
- Disk usage monitoring

### 5. STT Worker (`stt_worker.py`)
Performs speech-to-text processing using Vosk in separate processes:

```python
class STTWorker:
    # Vosk model loading and recognition
    # Session-specific recognizers
    # Partial and final result callbacks
    # Audio quality detection
```

**Processing Features**:
- Session-specific recognizer instances
- Streaming recognition (partial + final results)
- Audio quality metrics (RMS energy, duration)
- Confidence threshold validation (0.5 default)

### 6. LLM Client (`llm_client.py`)
Integrates with Groq Cloud's multimodal API:

```python
class LLMClient:
    # Multimodal requests with text and image
    # Conversation history management
    # Retry logic with exponential backoff
    # Fallback model support
```

**Integration Features**:
- Multimodal processing (text + image)
- Conversation context maintenance
- Automatic retry with exponential backoff
- Fallback model support

### 7. Image Handler (`image_handler.py`)
Manages image uploads, validation, and preparation:

```python
class ImageHandler:
    # File validation (JPEG/PNG, size, dimensions)
    # Thumbnail generation
    # LLM preparation with resizing
    # Resource cleanup
```

### 8. TTS Worker (`tts_worker.py`)
Generates speech from text using pyttsx3:

```python
class TTSWorker:
    # Text-to-speech conversion
    # WAV file generation
    # Duration estimation
    # Thread-safe execution
```

### 9. TTS Streamer (`tts_streamer.py`)
Streams generated audio to clients:

```python
class TTSStreamer:
    # Chunked audio streaming
    # Download URL generation
    # Client readiness tracking
```

### 10. Storage Manager (`storage_manager.py`)
Manages temporary files and disk cleanup:

```python
class StorageManager:
    # Temp directory management
    # Periodic cleanup of expired files
    # Disk usage tracking
    # Quota enforcement
```

---

## WebSocket Message Protocol

### Connection Setup
```
Client → Server: WebSocket handshake with query parameters
URL: ws://<host>:<port>/ws?session=<id>&token=<token>
Headers: Authorization (optional alternative to query param)
```

### Client → Server Messages (Text Control)

1. **hello** - Initial connection and capabilities
```json
{
  "type": "hello",
  "session": "session_id",
  "device": "esp32-cam",
  "capabilities": {
    "psram": false,
    "max_chunk_bytes": 16000
  }
}
```

2. **client_on** - Client boot ready notification
```json
{
  "type": "client_on"
}
```

3. **recording_started** - Begin audio recording
```json
{
  "type": "recording_started",
  "ts": 1234567890
}
```

4. **audio_chunk_meta** - Audio chunk metadata (followed by binary frame)
```json
{
  "type": "audio_chunk_meta",
  "seq": 1,
  "len_bytes": 16000
}
```
*Followed immediately by binary PCM16 frame*

5. **recording_stopped** - End audio recording
```json
{
  "type": "recording_stopped"
}
```

6. **image_captured** - Image capture notification (upload via HTTP POST)
```json
{
  "type": "image_captured",
  "filename": "image.jpg",
  "size": 123456
}
```

7. **ready_for_playback** - Client ready to receive TTS
```json
{
  "type": "ready_for_playback"
}
```

8. **playback_complete** - TTS playback finished
```json
{
  "type": "playback_complete"
}
```

9. **ping** - Connection health check
```json
{
  "type": "ping"
}
```

### Server → Client Messages (Text Control)

1. **ready** - Server ready for commands
```json
{
  "type": "ready"
}
```

2. **ack** - Acknowledge message receipt
```json
{
  "type": "ack",
  "ref": "chunk",
  "seq": 4
}
```

3. **partial** - Partial STT result
```json
{
  "type": "partial",
  "text": "Hello wor",
  "stable": false
}
```

4. **transcript** - Final STT result
```json
{
  "type": "transcript",
  "text": "Hello world",
  "final": true
}
```

5. **llm** - LLM response
```json
{
  "type": "llm",
  "text": "Hello! How can I help you?"
}
```

6. **tts_ready** - TTS file ready for streaming
```json
{
  "type": "tts_ready",
  "duration_ms": 2500,
  "sampleRate": 16000,
  "format": "wav"
}
```

7. **tts_chunk_meta** - TTS chunk metadata (followed by binary frame)
```json
{
  "type": "tts_chunk_meta",
  "seq": 1,
  "len_bytes": 16000
}
```
*Followed immediately by binary WAV frame*

8. **tts_done** - TTS streaming complete
```json
{
  "type": "tts_done"
}
```

9. **image_received** - Server received image
```json
{
  "type": "image_received",
  "filename": "image.jpg"
}
```

10. **request_rerecord** - Server requests re-recording
```json
{
  "type": "request_rerecord",
  "reason": "Empty transcript"
}
```

11. **offer_download** - Fallback download URL
```json
{
  "type": "offer_download",
  "url": "/download/token123"
}
```

12. **state_sync** - Server state information
```json
{
  "type": "state_sync",
  "server_state": "processing",
  "message": "Processing your request"
}
```

13. **request_user_intervention** - User action required
```json
{
  "type": "request_user_intervention",
  "message": "Too many re-recording attempts"
}
```

### Binary Frames
- **Audio chunks**: Raw PCM16 LE data
- **TTS chunks**: WAV frames containing audio data

---

## Audio Processing Pipeline

### Chunk Format Requirements
- **Format**: PCM16 LE (16-bit little-endian)
- **Sample Rate**: 16,000 Hz
- **Channels**: Mono (1 channel)
- **Chunk Size**: 16,000 bytes per 0.5 seconds (≈16KB)
- **Encoding**: Raw audio data (not WAV format initially)

### Processing Flow
1. **Client**: Capture audio in 0.5s chunks (16KB of PCM16 data)
2. **Client**: Send `audio_chunk_meta` with sequence and size
3. **Client**: Immediately send binary PCM16 frame
4. **Server**: Validate chunk format and sequence
5. **Server**: Append to temporary file and ring buffer
6. **Server**: Send STT worker the chunk for streaming recognition
7. **Server**: Send partial results to client as available
8. **Server**: Generate final transcript on `recording_stopped`

### Quality Validation
- **Silence Detection**: RMS energy < 50
- **Loudness Detection**: RMS energy > 5000
- **Confidence Threshold**: < 0.5 average word confidence
- **Duration Validation**: < 0.5 seconds considered too short

---

## Session Management

### State Transitions
```
disconnected → connected → idle → recording → processing → playing → idle
     ↑                                                    ↓
     └──────────────────────────────────────────────────────┘
```

### Session Lifecycle
1. **Session Creation**: On WebSocket connection
2. **State Synchronization**: Server tracks authoritative state
3. **Resource Allocation**: Temporary files and buffers
4. **Activity Logging**: All client events logged
5. **Resource Cleanup**: On session end or timeout

### Session Quotas
- **Disk**: Configurable per session (default 100MB)
- **Memory**: Ring buffer limits (configurable)
- **Time**: Inactive session timeout (default 300s)
- **Retry**: Re-record attempts (default 2)

---

## Error Handling & Recovery

### Server-Led Re-Record Policy
**Triggers**:
- Empty STT transcript
- Low confidence (< 0.5 threshold)
- Audio duration < 0.5s
- Loud clipping or extreme noise
- Disconnect during recording

**Actions**:
```json
{
  "type": "request_rerecord",
  "reason": "Empty transcript"
}
```

**Retry Limit**: 2 attempts before user intervention required

### Playback Fallback
When client doesn't respond to `ready_for_playback`:
1. Wait for timeout (default 5s)
2. Generate download URL with expiry (default 300s)
3. Send offer with download URL

### Timeout Handling
- **Chunk arrival**: 5s timeout during recording
- **Playback ready**: 5s timeout before fallback
- **Idle sessions**: 300s grace before cleanup
- **API calls**: 60s timeout with retry logic

---

## Implementation Guidelines for ESP32-CAM Client

### Audio Capture Requirements

#### Hardware Configuration
- **Microphone**: I2S interface for audio input
- **Sample Rate**: 16,000 Hz
- **Bit Depth**: 16-bit
- **Channels**: Mono
- **Buffer Size**: 16,000 bytes per 0.5s chunk

#### Audio Processing Pipeline
```cpp
// Pseudocode for ESP32 audio capture
void audioCaptureLoop() {
    // 1. Initialize I2S for audio input
    // 2. Configure for 16kHz, 16-bit, mono
    // 3. Create 16KB buffer for 0.5s chunks
    
    while (recording) {
        // 4. Fill buffer with audio samples
        // 5. When buffer full (0.5s):
        //    - Send audio_chunk_meta with seq and size
        //    - Immediately send binary PCM16 data
        //    - Reset buffer, increment sequence
    }
}
```

#### Chunk Sequencing
- Start sequence at 0 or 1
- Increment for each chunk sent
- Handle potential gaps in sequence
- Maintain consistent chunk timing (0.5s intervals)

### WebSocket Communication

#### Connection Management
```cpp
// Connect with session ID and auth token
String url = "ws://<server>/ws?session=" + sessionId + "&token=" + token;
wsClient.begin(url);
```

#### Message Handling
```cpp
// Example message handling
void onWebSocketMessage(String& message) {
    DynamicJsonDocument doc(1024);
    deserializeJson(doc, message);
    
    String msgType = doc["type"];
    
    if (msgType == "ready") {
        // Server ready, start sending commands
    } else if (msgType == "partial") {
        // Display partial STT result
        String text = doc["text"];
    } else if (msgType == "request_rerecord") {
        // Play beep/pulse LED, wait for user re-record
        String reason = doc["reason"];
    }
}
```

### Client State Management

#### State Synchronization
Maintain consistent state with server:
- **idle**: Ready to start recording
- **recording**: Capturing audio chunks
- **playing**: Receiving TTS stream
- **waiting**: Awaiting server response

#### Event Reporting
Report all local events to server:
- `client_on` on boot
- `recording_started` when user presses record
- `recording_stopped` when user releases record
- `ready_for_playback` when TTS playback ready
- `playback_complete` when finished

### Image Upload Implementation

#### Image Capture & Upload
```cpp
// Capture image using ESP32-CAM
void captureAndUploadImage() {
    // 1. Capture image from camera
    // 2. Validate size and format
    // 3. Send image_captured notification to server
    // 4. Upload file to POST /image with proper headers
    
    // Example upload to server
    HTTPClient http;
    http.begin(serverUrl + "/image?session=" + sessionId);
    http.addHeader("Authorization", token);
    
    int httpResponseCode = http.POST(imageData, imageSize);
    http.end();
}
```

### TTS Playback Implementation

#### Audio Playback Requirements
- **Format Support**: WAV PCM16@16kHz
- **Buffer Management**: Handle chunked audio
- **Synchronization**: Respond to server readiness signals

#### Playback Flow
```cpp
void handleTTSPlayback() {
    // 1. Receive tts_ready message with duration
    // 2. Send ready_for_playback to server
    // 3. Receive tts_chunk_meta and binary frames
    // 4. Play audio using I2S or appropriate output
    // 5. Send playback_complete when done
}
```

### Error Handling Implementation

#### Network Resilience
- **Reconnection Logic**: Auto-reconnect on network issues
- **Sequence Validation**: Handle sequence gaps gracefully
- **Timeout Management**: Implement local timeouts

#### Audio Quality Checks
- **Silence Detection**: Monitor for very low input levels
- **Clipping Detection**: Monitor for very high input levels
- **Duration Validation**: Don't send very short recordings

### Configuration Recommendations

#### Memory Management
- **PSRAM Utilization**: Use if available for larger buffers
- **Chunk Size**: Maintain 0.5s (16KB) default for compatibility
- **Sequence Numbers**: Use 32-bit integers for sequence tracking

#### Performance Considerations
- **Chunk Timing**: Maintain consistent 0.5s intervals
- **Connection Stability**: Implement heartbeat/ping mechanism
- **Resource Cleanup**: Clean up resources on state transitions

### Testing and Validation

#### Integration Testing
- **WebSocket Connectivity**: Test connection establishment and auth
- **Audio Streaming**: Verify chunk format and timing
- **STT Integration**: Confirm partial and final results
- **TTS Playback**: Validate audio quality and format
- **Error Scenarios**: Test re-record requests and timeouts

#### Hardware-Specific Validation
- **Audio Input**: Verify 16kHz, 16-bit, mono capture
- **Memory Usage**: Monitor during long recordings
- **Power Management**: Optimize for battery operation
- **Network Stability**: Handle intermittent connectivity

---

## Conclusion

The HotPin WebServer is designed as a robust, low-latency multimodal assistant that handles all heavy processing while the ESP32-CAM client focuses on input capture and simple command execution. The system prioritizes:

- **Reliability**: Server-led recovery mechanisms
- **Efficiency**: Streaming-first architecture with resource quotas
- **Flexibility**: Configurable parameters for different environments
- **Security**: Token-based authentication and validation

The ESP32-CAM client should focus on reliable audio capture and WebSocket communication, leaving all processing to the server. This architecture allows the resource-constrained ESP32 to provide rich multimodal assistance while maintaining simplicity and reliability.