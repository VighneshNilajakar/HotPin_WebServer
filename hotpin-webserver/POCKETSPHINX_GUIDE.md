# PocketSphinx STT Setup Guide

## Why PocketSphinx?

✅ **Works natively on Termux** - No compilation needed  
✅ **Fully offline** - No internet required  
✅ **Lightweight** - Models are ~30MB  
✅ **No dependencies** - Pure Python package  
✅ **ARM-compatible** - Built for Android/ARM processors  
✅ **Battle-tested** - CMU Sphinx has been around since 1980s  
✅ **Cross-platform** - Works on Windows, Linux, Mac, Android  

❌ **Lower accuracy** - Best for command recognition and basic transcription  
❌ **Less flexible** - Harder to customize  
❌ **Slower updates** - Less active development  

## Installation on Termux

```bash
# Navigate to project
cd ~/HotPin_WebServer/hotpin-webserver

# Install requirements (includes PocketSphinx)
pip install -r requirements-termux.txt

# OR install just PocketSphinx
pip install pocketsphinx
```

## Configuration

### Option 1: Environment Variable

Create a `.env` file:
```bash
# PocketSphinx model (default: en-us)
POCKETSPHINX_MODEL=en-us

# Confidence threshold (default: 0.5)
STT_CONF_THRESHOLD=0.5
```

## Models

PocketSphinx comes with a built-in English model (`en-us`). No download needed!

### Available Models

- **en-us** (Default) - US English, general purpose
- **en-us-semi** - Semi-continuous model, faster
- **cmusphinx-en-us-ptm-5.2** - Larger model, better accuracy

### Using Different Models

```bash
# Set in .env
echo "POCKETSPHINX_MODEL=en-us" >> .env
```

Or in Python:
```python
from hotpin.pocketsphinx_stt_worker import PocketSphinxSTTWorker

worker = PocketSphinxSTTWorker(model_path="/path/to/model")
```

## Usage Examples

### Basic Usage

```python
from hotpin.pocketsphinx_stt_worker import PocketSphinxSTTWorker

# Create worker
worker = PocketSphinxSTTWorker()

# Start session
worker.start_recognition_session("session1", sample_rate=16000)

# Process audio (16-bit PCM, mono, 16kHz)
result = worker.process_audio("session1", audio_data)
if result:
    print(f"Recognized: {result.text}")

# End session
final_result = worker.end_recognition_session("session1")
```

### With Audio File

```python
import wave
from hotpin.pocketsphinx_stt_worker import PocketSphinxSTTWorker

worker = PocketSphinxSTTWorker()
session_id = "test"

worker.start_recognition_session(session_id)

with wave.open("audio.wav", "rb") as wf:
    chunk_size = 8000  # 0.5 seconds at 16kHz
    
    while True:
        data = wf.readframes(chunk_size)
        if not data:
            break
        
        result = worker.process_audio(session_id, data)
        if result:
            print(f"Text: {result.text}")

final = worker.end_recognition_session(session_id)
```

## Features & Benefits

| Feature | PocketSphinx |
|---------|--------------|
| **Works on Termux** | ✅ Yes |
| **Installation** | `pip install` - Easy |
| **Model Size** | ~30 MB |
| **Accuracy** | Good (80-90%) |
| **Speed** | Fast |
| **Offline** | ✅ Yes |
| **RAM Usage** | Low (~50MB) |
| **Cross-Platform** | Windows, Linux, Mac, Android |
| **Best For** | Commands & Basic Transcription |

## When to Use PocketSphinx

### ✅ Perfect For:
- Running on Termux/Android
- Voice commands and control
- Offline-only applications
- Low memory/storage devices
- Simple installation requirements
- Basic transcription needs

### ⚠️ Consider Alternatives If:
- Need very high accuracy (95%+)
- Transcribing long conversations
- Multiple speakers/accents
- Complex vocabulary requirements

## Testing

```bash
# Test PocketSphinx installation
python -c "
from pocketsphinx import Pocketsphinx, get_model_path
print('✅ PocketSphinx is installed!')
print(f'Model path: {get_model_path(\"en-us\")}')
"
```

## Troubleshooting

### "No module named 'pocketsphinx'"

```bash
pip install pocketsphinx
```

### "Cannot find model"

PocketSphinx includes models by default. If you see this error:

```python
from pocketsphinx import get_model_path
print(get_model_path('en-us'))  # Check model location
```

### Poor recognition quality

1. **Ensure correct audio format**:
   - 16-bit PCM
   - Mono (1 channel)
   - 16kHz sample rate

2. **Reduce background noise**
3. **Speak clearly and at moderate pace**
4. **Use keyword spotting** for specific commands

### Low confidence scores

PocketSphinx confidence scores are based on acoustic model probabilities:
- Lower scores don't always mean wrong recognition
- Typical range: 0.2 to 0.8 (vs 0.0 to 1.0 for some other STT engines)
- Use a threshold of ~0.3-0.4 instead of 0.5

## Improving Accuracy

### 1. Use Keyword Spotting

For command recognition:

```python
config = {
    'keyphrase': 'hello computer',
    'kws_threshold': 1e-20
}
recognizer = Pocketsphinx(**config)
```

### 2. Use Grammar Files (JSGF)

Define specific phrases:

```jsgf
#JSGF V1.0;

grammar commands;

public <command> = <action> <direction> <amount>;
<action> = (go | move);
<direction> = (forward | backward | left | right);
<amount> = (one | two | three | four | five) (meter | meters);
```

### 3. Custom Dictionary

Add words to pronunciation dictionary:

```
HOTPIN HH AA T P IH N
WEBSERVER W EH B S ER V ER
```

## Performance Tips

1. **Process audio in chunks** - Don't send huge files at once
2. **Use appropriate sample rate** - 16kHz is optimal
3. **Pre-process audio** - Remove silence, normalize volume
4. **Adjust timeout values** - Based on expected speech length

## Integration with HotPin

The HotPin server will automatically use PocketSphinx when configured:

```bash
# .env file
STT_BACKEND=pocketsphinx
POCKETSPHINX_MODEL=en-us
```

Then run:
```bash
python -m hotpin.server
```

The server will use PocketSphinx for all STT operations!

## Resources

- [PocketSphinx Documentation](https://pocketsphinx.readthedocs.io/)
- [CMU Sphinx Home](https://cmusphinx.github.io/)
- [PocketSphinx PyPI](https://pypi.org/project/pocketsphinx/)
- [Language Models](https://sourceforge.net/projects/cmusphinx/files/Acoustic%20and%20Language%20Models/)

## Summary

**Quick Start:**
```bash
# Install
pip install pocketsphinx

# Configure
echo "STT_BACKEND=pocketsphinx" >> .env

# Test
python -c "from pocketsphinx import Pocketsphinx; print('Works!')"

# Run
python -m hotpin.server
```

**That's it!** PocketSphinx is the easiest offline STT solution for Termux. 🎉
