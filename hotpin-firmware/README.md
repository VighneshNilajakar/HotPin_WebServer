# HotPin Firmware

ESP32-CAM based multimodal assistant client for the HotPin WebServer system.

## Features

- Voice recording and streaming to server (PCM16@16kHz, 0.5s chunks)
- Multimodal AI processing with text-to-speech feedback
- Camera capture and image upload
- Hardware button interface with single/double/long press actions
- Status LED with state-indicating patterns
- PSRAM support for improved performance
- WebSocket communication with server

## Hardware Requirements

- ESP32-CAM (AI-Thinker variant recommended)
- INMP441 I²S MEMS microphone
- MAX98357A I²S DAC + amplifier
- 8Ω speaker
- Push button (GPIO12 with 10kΩ pull-down)
- Status LED (GPIO33)

## Hardware Connections

### I²S Connections
- GPIO14 → INMP441 SCK & MAX98357A BCLK (shared clock)
- GPIO15 → INMP441 WS & MAX98357A LRC (shared LR clock)
- GPIO2 → INMP441 SD (microphone data in)
- GPIO13 → MAX98357A DIN (DAC data out)

### Other Connections
- GPIO12 → Push button (with 10kΩ pull-down to GND)
- GPIO33 → Status LED
- 3.3V → INMP441 VDD
- 5V → ESP32-CAM VIN and MAX98357A VIN
- All modules share common GND

**Important**: Ensure GPIO12 has a 10kΩ pull-down resistor to GND to prevent boot issues.

## Button Controls

- **Single press**: Toggle recording (idle → recording, recording → processing)
- **Double press**: Capture and upload image
- **Long press (≥1200ms)**: Shutdown device

## LED Patterns

- **Slow blink**: IDLE state
- **Fast blink**: RECORDING state  
- **Medium blink**: PROCESSING state
- **Continuous on**: PLAYING state
- **Triple quick blink**: CAMERA_CAPTURE state
- **Rapid flash**: Error state

## Building and Flashing

1. Install ESP-IDF v4.4 or later
2. Configure WiFi settings:
   ```bash
   idf.py menuconfig
   # Navigate to "HotPin Configuration" and set WiFi credentials
   ```
3. Build the project:
   ```bash
   idf.py build
   ```
4. Flash to device:
   ```bash
   idf.py flash
   ```

## Configuration

The firmware can be configured through `menuconfig`:

- WebSocket server URL and token
- WiFi credentials
- Camera model selection

## WiFi Configuration

The firmware needs to be configured with your WiFi network credentials to connect to the WebSocket server. There are three ways to configure WiFi:

### Method 1: Using .env file (Recommended)
```bash
# Copy the example configuration file:
cp .env.example .env

# Edit .env with your network credentials:
nano .env

# Generate configuration files:
./generate_config.sh  # On Linux/Mac
generate_config.bat   # On Windows

# Build the firmware:
idf.py build
```

### Method 2: Using menuconfig
```bash
idf.py menuconfig
```
Navigate to "HotPin Configuration" and set:
- WiFi SSID
- WiFi Password

### Method 3: Using sdkconfig.local
Copy the example configuration file:
```bash
cp sdkconfig.local.example sdkconfig.local
```
Then edit `sdkconfig.local` with your network credentials.

### Method 4: Using Kconfig.projbuild
Edit `main/Kconfig.projbuild` and update the default values (not recommended for production).

## State Machine

The firmware implements the following state transitions:

```
BOOTING → CONNECTED → IDLE ↔ RECORDING → PROCESSING → PLAYING → IDLE
                    ↓                                        ↓
                CAMERA_CAPTURE ←→ SHUTDOWN ←------------------┘
                    ↓
                 STALLED
```

## Audio Processing

- Audio format: PCM16 LE, mono, 16kHz
- Chunk size: 0.5 seconds (16,000 bytes)
- Preallocated buffer pool with configurable size based on PSRAM availability

## Memory Management

- With PSRAM: 16 chunk pool (256KB)
- Without PSRAM: 4 chunk pool (64KB)
- Fixed-size preallocated buffers to avoid runtime allocation issues

## Error Handling

- Buffer overflow protection during recording
- Connection reestablishment with exponential backoff
- Graceful handling of I2S/camera conflicts
- Server-orchestrated re-recording requests