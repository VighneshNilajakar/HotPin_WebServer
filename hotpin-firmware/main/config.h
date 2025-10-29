/*
 * HotPin Firmware Configuration Constants
 * Automatically generated from .env file
 * Do not edit manually - edit .env instead
 */

#ifndef CONFIG_H
#define CONFIG_H

// WiFi Configuration
#define WIFI_SSID "wifi"
#define WIFI_PASSWORD "123456780"

// WebSocket Configuration
#define WEBSOCKET_URL "ws://10.88.188.211:8000/ws"
#define WEBSOCKET_TOKEN "mysecrettoken123"

// Audio Configuration
#define CHUNK_SIZE_BYTES 16000
#define SAMPLE_RATE 16000

// Camera Configuration
#define CAMERA_ENABLED 1

// Debug Configuration
#define LOG_LEVEL "INFO"

#endif // CONFIG_H
