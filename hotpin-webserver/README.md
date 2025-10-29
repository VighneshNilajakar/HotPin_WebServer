# HotPin WebServer

A multimodal assistant server designed to work with ESP32-CAM devices, providing speech-to-text, AI processing, and text-to-speech capabilities with efficient resource management for constrained clients.

## Features

- WebSocket-based communication with token authentication
- Streaming audio processing with Vosk STT
- Multimodal AI processing with Groq Cloud API
- Text-to-speech generation with pyttsx3
- Client state management and recovery mechanisms
- Configurable resource limits and cleanup
- Image upload and processing for multimodal interactions

## Prerequisites

- Python 3.10+
- Vosk speech recognition model (specifically `vosk-model-small-en-in-0.4`)
- Groq Cloud API key for multimodal processing

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy and configure environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration, especially GROQ_API_KEY
```

4. Ensure Vosk model is available at the path specified in `MODEL_PATH_VOSK`

## Configuration

Key configuration options (see `.env.example` for full list):

- `HOST`/`PORT`: Server host and port
- `WS_TOKEN`: Authentication token for WebSocket connections
- `MODEL_PATH_VOSK`: Path to Vosk model directory
- `GROQ_API_KEY`: API key for Groq Cloud multimodal processing
- `TEMP_DIR`: Directory for temporary file storage
- `MAX_SESSION_DISK_MB`: Disk quota per session

### Discovery Features

New discovery features help automatically detect and advertise the WebSocket server:

- `WEBSOCKET_PORT`: Port for WebSocket connections (default: 8000)
- `WEBSOCKET_PATH`: Path for WebSocket endpoint (default: /ws)
- `WEBSOCKET_TOKEN`: Token for WebSocket authentication (default: mysecrettoken123)
- `USE_TLS`: Use secure WebSocket (wss://) (default: false)
- `MDNS_ADVERTISE`: Advertise service via mDNS (default: false)
- `HOTPIN_NAME`: Name for mDNS advertisement (default: HotpinServer)
- `UDP_BROADCAST`: Broadcast URL via UDP (default: false)
- `BROADCAST_PORT`: UDP broadcast port (default: 50000)
- `BROADCAST_INTERVAL_SEC`: Broadcast interval in seconds (default: 5)
- `PRINT_QR`: Print QR code to console (default: false)

## Running the Server

```bash
python -m hotpin.server
```

Or with uvicorn directly:
```bash
uvicorn hotpin.server:app --host $HOST --port $PORT --loop uvloop
```

## WebSocket URL Discovery

On startup, the server automatically detects and logs WebSocket URLs that clients can use to connect:

```
INFO:     Hotpin WebSocket URL (primary): ws://192.168.1.100:8000/ws?token=mysecrettoken123
INFO:     Interface eth0 -> Hotpin WS URL: ws://192.168.1.100:8000/ws?token=mysecrettoken123
INFO:     Interface wlan0 -> Hotpin WS URL: ws://10.0.0.5:8000/ws?token=mysecrettoken123
```

## Discovery Features

The server supports multiple methods for discovering and advertising the WebSocket URL:

### mDNS Advertisement
When `MDNS_ADVERTISE=true`, the server registers a Zeroconf service `_hotpin._tcp.local` that can be discovered by other devices on the network.

### UDP Broadcast
When `UDP_BROADCAST=true`, the server periodically broadcasts the WebSocket URL to `255.255.255.255:BROADCAST_PORT` every `BROADCAST_INTERVAL_SEC` seconds.

### QR Code Printing
When `PRINT_QR=true`, the server prints an ASCII QR code of the primary WebSocket URL to the console for easy scanning.

## API Endpoints

- `ws://<host>:<port>/ws?session=<id>&token=<token>` - WebSocket endpoint for client communication
- `POST /image` - Upload image with `session` query parameter
- `GET /health` - Health check endpoint
- `GET /state?session=<id>` - Get session state

## Client Message Protocol

### Client → Server (text control)

- `hello`: `{type: "hello", session, device, capabilities}`
- `client_on`: `{type: "client_on"}`
- `recording_started`: `{type:"recording_started", ts}`
- `audio_chunk_meta`: `{type:"audio_chunk_meta", seq, len_bytes}` (then binary frame with raw PCM)
- `recording_stopped`: `{type:"recording_stopped"}`
- `image_captured`: `{type:"image_captured", filename, size}`
- `ready_for_playback`: `{type:"ready_for_playback"}`
- `playback_complete`: `{type:"playback_complete"}`
- `ping`: `{type:"ping"}`

### Server → Client (text control)

- `ready`: `{type:"ready"}`
- `ack`: `{type:"ack", ref:"chunk"|..., seq}`
- `partial`: `{type:"partial", text, stable: false}`
- `transcript`: `{type:"transcript", text, final: true}`
- `llm`: `{type:"llm", text}`
- `tts_ready`: `{type:"tts_ready", duration_ms, sampleRate:16000, format:"wav"}`
- `tts_chunk_meta`: `{type:"tts_chunk_meta", seq, len_bytes}` (then binary WAV frame)
- `tts_done`: `{type:"tts_done"}`
- `image_received`: `{type:"image_received", filename}`
- `request_rerecord`: `{type:"request_rerecord", reason}`
- `offer_download`: `{type:"offer_download", url}`
- `state_sync`: `{type:"state_sync", server_state, message}`
- `request_user_intervention`: `{type:"request_user_intervention", message}`

## Architecture Components

- **WebSocket Manager**: Handles connections with single-session enforcement
- **Session Manager**: Maintains per-session state and event logs
- **Audio Ingestor**: Processes streaming PCM audio chunks with buffering
- **STT Worker**: Uses Vosk for streaming speech recognition
- **LLM Client**: Integrates with Groq Cloud's multimodal API
- **Image Handler**: Manages image uploads and validation
- **TTS Worker**: Generates speech from text
- **TTS Streamer**: Streams audio back to client
- **Storage Manager**: Handles temp file management and cleanup

## Error Handling

- Server-led re-record requests for poor audio quality
- Playback fallback with download URLs
- Session timeout and cleanup
- Disk usage quotas per session
- Retry mechanisms for external API calls