# HotPin Firmware Configuration Management

The HotPin firmware uses a `.env` file-based configuration system that automatically generates the appropriate firmware configuration files.

## Configuration Files

### `.env` - Main Configuration File
This is the primary configuration file that users should edit with their settings.

### `.env.example` - Configuration Template
Template file showing all available configuration options.

### `sdkconfig.local` - Generated ESP-IDF Configuration
Automatically generated from `.env` - contains ESP-IDF configuration options.

### `main/config.h` - Generated C Header
Automatically generated from `.env` - contains C constants for use in firmware code.

## Configuration Process

### 1. Setup
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your settings:
   ```bash
   # WiFi Configuration
   WIFI_SSID=YourWiFiNetworkName
   WIFI_PASSWORD=YourWiFiPassword
   
   # WebSocket Configuration
   WEBSOCKET_URL=ws://10.50.92.58:8000/ws
   WEBSOCKET_TOKEN=mysecrettoken123
   ```

### 2. Generate Configuration Files
Run the configuration generator:
```bash
# On Linux/Mac
./generate_config.sh

# On Windows
generate_config.bat
```

Or run directly:
```bash
python tools/config_generator.py
```

### 3. Build Firmware
```bash
idf.py build
```

## Available Configuration Options

### WiFi Configuration
- `WIFI_SSID`: WiFi network name (required for WiFi connectivity)
- `WIFI_PASSWORD`: WiFi network password (leave empty for open networks)

### WebSocket Configuration
- `WEBSOCKET_URL`: WebSocket server URL
- `WEBSOCKET_TOKEN`: Authentication token for WebSocket connection

### Audio Configuration
- `CHUNK_SIZE_BYTES`: Size of audio chunks in bytes
- `SAMPLE_RATE`: Audio sample rate in Hz

### Camera Configuration
- `CAMERA_ENABLED`: Enable/disable camera support (true/false)

### Debug Configuration
- `LOG_LEVEL`: Logging level (INFO/WARN/ERROR/DEBUG)

## Troubleshooting

### Configuration Not Applied
1. Ensure `.env` file exists and is properly formatted
2. Run `generate_config.sh` or `generate_config.bat` after making changes
3. Rebuild firmware with `idf.py build`

### WiFi Connection Issues
1. Verify `WIFI_SSID` and `WIFI_PASSWORD` in `.env`
2. Ensure the WiFi network is accessible
3. Check that the network credentials are correct

### WebSocket Connection Issues
1. Verify `WEBSOCKET_URL` in `.env`
2. Ensure the WebSocket server is running and accessible
3. Check that `WEBSOCKET_TOKEN` is correct