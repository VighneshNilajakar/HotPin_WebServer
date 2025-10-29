# Groq Whisper STT Implementation

## Overview
HotPin WebServer now uses **Groq's Whisper API** for speech-to-text (STT) transcription. This is a cloud-based solution that provides fast, accurate transcription using OpenAI's Whisper models hosted on Groq's infrastructure.

## Why Groq Whisper?

### Previous Attempts
1. **Vosk** (Local, Offline)
   - ❌ Failed: Requires Rust compilation for Pydantic dependencies
   - ❌ No ARM Android wheels available for Termux
   
2. **PocketSphinx** (Local, Offline)
   - ❌ Failed: ABI incompatibility with Python 3.12 on ARM64
   - ❌ Error: `dlopen failed: cannot locate symbol "_Py_NoneStruct"`

### Groq Whisper (Cloud, API)
- ✅ **Works on Termux**: No compilation required, pure Python API client
- ✅ **FREE Tier**: 25MB file upload limit per request
- ✅ **Fast**: `whisper-large-v3-turbo` optimized for speed
- ✅ **Accurate**: `whisper-large-v3` for maximum accuracy
- ✅ **Same API Key**: Uses existing `GROQ_API_KEY` (no additional setup)

## Architecture

### How It Works
1. **Audio Accumulation**: STT worker accumulates PCM audio chunks in memory during recording session
2. **WAV Conversion**: When recording ends, convert accumulated PCM to WAV format
3. **API Upload**: Send WAV file to Groq Whisper API via `client.audio.transcriptions.create()`
4. **Transcription**: Groq returns text transcription synchronously
5. **Cleanup**: Delete temporary WAV file after API call

### Key Differences from Local STT
- **No Streaming**: Cloud API requires complete audio file (not chunk-by-chunk)
- **Session-Based**: Audio chunks stored per session_id until `finalize_recognition()`
- **Synchronous**: Returns full transcription immediately (no partial results)
- **Network Dependent**: Requires internet connection (no offline mode)

## Configuration

### Environment Variables (.env)
```bash
# Groq API (shared with LLM)
GROQ_API_KEY=gsk_your_api_key_here

# Groq Whisper STT settings
GROQ_STT_MODEL=whisper-large-v3-turbo  # Fast, $0.04/min
# GROQ_STT_MODEL=whisper-large-v3       # Accurate, $0.111/min
STT_LANGUAGE=en                         # ISO 639-1 language code
STT_TEMPERATURE=0.0                     # 0.0 = deterministic, higher = more creative
```

### Available Models
| Model | Speed | Accuracy | Cost | Best For |
|-------|-------|----------|------|----------|
| `whisper-large-v3-turbo` | Fast | Good | $0.04/min | Real-time apps |
| `whisper-large-v3` | Slower | Excellent | $0.111/min | High accuracy needs |

### Pricing & Limits
- **Free Tier**: 25MB file size limit per request
- **Minimum Billing**: 10 seconds (shorter audio billed as 10s)
- **Rate Limits**: Check Groq console for current limits

## API Usage

### Code Example (from stt_worker.py)
```python
from groq import Groq

# Initialize client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Transcribe audio
with open("audio.wav", "rb") as audio_file:
    transcription = client.audio.transcriptions.create(
        file=audio_file,
        model="whisper-large-v3-turbo",
        language="en",
        temperature=0.0,
        response_format="json"
    )
    text = transcription.text
```

## Implementation Details

### Modified Files
1. **`hotpin/stt_worker.py`**
   - Replaced PocketSphinx with Groq Whisper API
   - Added session-based audio accumulation
   - Implemented WAV file creation from PCM chunks
   - Added Groq API error handling

2. **`hotpin/config.py`**
   - Removed: `POCKETSPHINX_MODEL`
   - Added: `GROQ_STT_MODEL`, `STT_LANGUAGE`, `STT_TEMPERATURE`

3. **`hotpin/server.py`**
   - Updated health endpoint: `"models": ["groq-whisper", "groq-llm"]`

4. **`.env` and `.env.example`**
   - Removed PocketSphinx configuration
   - Added Groq Whisper settings

5. **`tests/test_basic.py`**
   - Updated config test: `POCKETSPHINX_MODEL` → `GROQ_STT_MODEL`

6. **`requirements-termux.txt`**
   - Removed: `pocketsphinx>=5.0.0`
   - Notes: Uses existing `groq` package (installed for LLM)

### Key Methods (stt_worker.py)

#### `start_recognition_session(session_id: str)`
Creates a new session dict to accumulate audio chunks:
```python
self.sessions[session_id] = {
    "audio_chunks": [],
    "sample_rate": 16000,
    "channels": 1
}
```

#### `accept_audio_chunk(session_id: str, audio_chunk: bytes)`
Appends audio chunk to session buffer:
```python
if session_id in self.sessions:
    self.sessions[session_id]["audio_chunks"].append(audio_chunk)
```

#### `finalize_recognition(session_id: str) -> Optional[str]`
1. Concatenates all audio chunks into single PCM buffer
2. Creates temporary WAV file from PCM data
3. Calls Groq Whisper API with WAV file
4. Returns transcription text
5. Cleans up temporary file and session data

## Audio Format Requirements

### Input (from ESP32-CAM)
- **Format**: PCM (raw audio)
- **Sample Rate**: 16000 Hz
- **Channels**: 1 (mono)
- **Bit Depth**: 16-bit signed integers

### API Upload (WAV)
- **Format**: WAV container with PCM data
- **Sample Rate**: 16000 Hz (preserved from input)
- **Channels**: 1 (mono)
- **Bit Depth**: 16-bit signed integers

## Testing on Termux

### Installation
```bash
# Install Python and dependencies
pkg update
pkg install python git

# Clone repository
cd ~/storage/shared
git clone <repository-url>
cd hotpin-webserver

# Install dependencies
pip install --upgrade pip
pip install -r requirements-termux.txt
```

### Run Server
```bash
# Set environment variables
export GROQ_API_KEY="gsk_your_api_key_here"

# Run server
python -m hotpin.server
```

### Test STT
1. Connect ESP32-CAM client
2. Start recording session
3. Speak into microphone
4. End recording
5. Check server logs for Groq API call and transcription

## Error Handling

### Common Errors
1. **Missing API Key**
   ```
   ERROR: GROQ_API_KEY not set in environment
   ```
   **Solution**: Set `GROQ_API_KEY` in `.env` file

2. **File Size Limit**
   ```
   ERROR: File size exceeds 25MB limit
   ```
   **Solution**: Reduce recording duration or implement chunking

3. **Network Error**
   ```
   ERROR: Failed to connect to Groq API
   ```
   **Solution**: Check internet connection, verify API key

4. **Rate Limit**
   ```
   ERROR: Rate limit exceeded
   ```
   **Solution**: Wait before retrying, upgrade to paid tier

## Performance Considerations

### Latency
- **Network Latency**: ~100-500ms (depends on connection)
- **API Processing**: ~500-2000ms (depends on audio length and model)
- **Total**: ~1-3 seconds for typical voice commands

### Audio Size Optimization
- **Typical Voice Command**: 3-5 seconds = ~96-160KB WAV file
- **Max Free Tier**: 25MB ≈ 13 minutes of audio at 16kHz mono
- **Recommendation**: Keep recordings under 30 seconds for best UX

### Cost Estimation (Paid Tier)
- **Average Command**: 5 seconds
- **Billed As**: 10 seconds (minimum)
- **Cost per Command**: $0.0067 (turbo) or $0.0185 (v3)
- **1000 Commands**: $6.70 (turbo) or $18.50 (v3)

## Future Improvements

### Potential Enhancements
1. **Audio Chunking**: Split long recordings into <25MB segments
2. **Voice Activity Detection (VAD)**: Trim silence before/after speech
3. **Audio Compression**: Reduce file size with Opus/MP3 encoding
4. **Fallback STT**: Add Google/Azure STT as backup if Groq fails
5. **Caching**: Cache common phrases to reduce API calls
6. **Streaming**: Explore Groq's streaming API when available

## Troubleshooting

### Issue: "No transcription returned"
- **Check**: Audio file created successfully?
- **Check**: Audio contains speech (not silence)?
- **Check**: API key valid and has quota remaining?
- **Solution**: Enable debug logging, check temp WAV file manually

### Issue: "Slow transcription"
- **Check**: Network connection speed
- **Try**: Switch to `whisper-large-v3-turbo` model
- **Try**: Reduce audio sample rate to 8kHz (if acceptable)

### Issue: "Incorrect language detected"
- **Fix**: Set `STT_LANGUAGE=en` in `.env` explicitly
- **Try**: Use `whisper-large-v3` for better multilingual support

## References

- **Groq Speech-to-Text Docs**: https://console.groq.com/docs/speech-to-text
- **Groq Python SDK**: https://github.com/groq/groq-python
- **Whisper Model Card**: https://github.com/openai/whisper
- **HotPin WebServer**: Current implementation

## Migration Notes

### From PocketSphinx
1. Removed `pocketsphinx` from requirements
2. Changed from streaming recognition to batch processing
3. Added audio accumulation in `accept_audio_chunk()`
4. Created WAV conversion in `finalize_recognition()`
5. Updated config to use `GROQ_STT_MODEL` instead of `POCKETSPHINX_MODEL`

### Breaking Changes
- **No Partial Results**: Cloud API doesn't support streaming partial transcriptions
- **Requires Network**: No offline mode (PocketSphinx was offline)
- **API Costs**: Free tier limited, paid tier has per-minute costs

### Compatibility
- ✅ ESP32-CAM client: No changes needed (same WebSocket protocol)
- ✅ Server API: Same endpoints and responses
- ✅ Session management: Same flow (start → chunks → finalize)
- ⚠️ Latency: Slightly higher due to network + API processing
