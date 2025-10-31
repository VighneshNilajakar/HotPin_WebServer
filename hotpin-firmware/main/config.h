/*
 * HotPin Firmware Configuration Constants
 * Automatically generated from .env file
 * Do not edit manually - edit .env instead
 */

#ifndef CONFIG_H
#define CONFIG_H

// WiFi Configuration (using actual values instead of CONFIG_ macros)
#define CONFIG_ESP_WIFI_SSID "wifi"
#define CONFIG_ESP_WIFI_PASSWORD "123456780"

// WebSocket Configuration
#define WEBSOCKET_URL "ws://10.89.246.235:8000/ws"
#define WEBSOCKET_TOKEN "mysecrettoken123"

// Audio Configuration
#define CHUNK_SIZE_BYTES 16000
#define SAMPLE_RATE 16000

// Camera Configuration
#define CAMERA_ENABLED 1

// Debug Configuration
#define LOG_LEVEL "INFO"

// WiFi Configuration (backward compatibility)
#define WIFI_SSID CONFIG_ESP_WIFI_SSID
#define WIFI_PASSWORD CONFIG_ESP_WIFI_PASSWORD

#endif // CONFIG_H
