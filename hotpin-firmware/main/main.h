/*
 * HotPin Firmware - Main Header File
 */

#ifndef MAIN_H
#define MAIN_H

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <inttypes.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#include "esp_system.h"
#include "esp_mac.h"  // Required for MAC address functions in ESP-IDF v5.4+
#include "esp_heap_caps.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_websocket_client.h"

#include "driver/gpio.h"
#include "driver/i2s.h"  // Legacy I2S API (with deprecation warning)
#include "driver/ledc.h"

#include "cJSON.h"

#include "dynamic_config.h"

#include "sdkconfig.h"
#include "config.h"  // Generated configuration from .env file

#include "lwip/err.h"
#include "lwip/sys.h"
#include "lwip/sockets.h"
#include "lwip/dns.h"
#include "lwip/netdb.h"

#include "esp_http_client.h"
#include "dynamic_config.h"
#include "network_discovery.h"

// WebSocket configuration
// Use values from generated config.h
#define HOTPIN_WS_URL WEBSOCKET_URL
#define HOTPIN_WS_TOKEN WEBSOCKET_TOKEN
// SESSION_ID will be dynamically generated to be unique per device
extern char SESSION_ID[32];  // Dynamically generated unique session ID

// GPIO mapping
#define GPIO_MIC_SD     2   // I2S data in from INMP441
#define GPIO_BCLK       14  // I2S BCLK (shared)
#define GPIO_LRCLK      15  // I2S LRCLK/WS (shared)
#define GPIO_DAC_SD     13  // I2S data out to MAX98357A
#define GPIO_BUTTON     12  // Push button (active LOW with internal pull-up)
#define GPIO_LED        33  // Status LED

// Timing constants
#define DEBOUNCE_MS             50
#define DOUBLE_PRESS_WINDOW_MS  300
#define LONG_PRESS_MS           1200

// Audio constants
#define SAMPLE_RATE         16000
#define BITS_PER_SAMPLE     I2S_BITS_PER_SAMPLE_16BIT
#define CHANNELS            1
#define CHUNK_SAMPLES       8000  // 0.5 seconds at 16kHz
#define CHUNK_BYTES         16000 // 8000 samples * 2 bytes per sample
#define I2S_PORT            I2S_NUM_1  // Prefer I2S1 to avoid camera conflicts

// Memory pool configuration
#define POOL_COUNT_NO_PSRAM     4   // ~64KB pool
#define POOL_COUNT_WITH_PSRAM   16  // ~256KB pool

// Task stack sizes
#define TASK_STACK_SIZE_AUDIO_CAPTURE   8192
#define TASK_STACK_SIZE_AUDIO_SEND      4096
#define TASK_STACK_SIZE_AUDIO_PLAYBACK  8192
#define TASK_STACK_SIZE_WS              6144
#define TASK_STACK_SIZE_BUTTON          3072
#define TASK_STACK_SIZE_CAMERA          12288

// Camera GPIO definitions (AI-Thinker specific)
#ifdef CONFIG_CAMERA_MODEL_AI_THINKER
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM       5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#endif

// Global variables and structs
typedef enum {
    CLIENT_STATE_BOOTING = 0,
    CLIENT_STATE_CONNECTED,
    CLIENT_STATE_IDLE,
    CLIENT_STATE_RECORDING,
    CLIENT_STATE_PROCESSING,
    CLIENT_STATE_PLAYING,
    CLIENT_STATE_CAMERA_CAPTURE,
    CLIENT_STATE_STALLED,
    CLIENT_STATE_SHUTDOWN
} client_state_t;

typedef struct {
    uint8_t *data;
    size_t len;
    uint32_t seq;
    TickType_t timestamp;
} audio_chunk_t;

typedef enum {
    BUTTON_STATE_IDLE = 0,
    BUTTON_STATE_PRESSED,
    BUTTON_STATE_RELEASED,
    BUTTON_STATE_LONG_PRESS_DETECTED
} button_state_t;

// Global state variables
extern client_state_t current_state;
extern QueueHandle_t q_free_chunks;
extern QueueHandle_t q_capture_to_send;
extern QueueHandle_t q_playback;
extern QueueHandle_t q_ws_messages;  // WebSocket message queue
extern SemaphoreHandle_t state_mutex;
extern SemaphoreHandle_t i2s_mutex;
extern uint32_t next_seq;
extern bool psram_available;
extern bool audio_i2s_initialized;
extern uint8_t *chunk_pool;
extern int pool_size;

// WebSocket message queue structure
typedef struct {
    cJSON *json;        // JSON message to send (NULL if binary)
    bool is_binary;     // Flag indicating if this is a binary message
    uint8_t *data;      // Binary data (if is_binary is true)
    size_t len;         // Length of binary data
} ws_message_t;

// External reference to WebSocket message queue
extern QueueHandle_t q_ws_messages;
extern TaskHandle_t audio_capture_task_handle;
extern TaskHandle_t audio_send_task_handle;
extern TaskHandle_t audio_playback_task_handle;

// Function declarations
void app_main(void);
void set_state(client_state_t new_state);
const char* state_to_string(client_state_t state);
void update_led_pattern();
bool init_psram_detection();
bool init_chunk_pool();
bool init_gpio();
bool init_i2s();
bool uninstall_i2s();
bool init_wifi();
bool init_websocket();
void cleanup_websocket();  // Add WebSocket cleanup function
void reconnect_websocket();  // Add WebSocket reconnection function
void button_task(void *pvParameters);
void audio_capture_task(void *pvParameters);
void audio_send_task(void *pvParameters);
void audio_playback_task(void *pvParameters);
void websocket_task(void *pvParameters);
void camera_task(void *pvParameters);
void state_manager_task(void *pvParameters);
void config_update_task(void *pvParameters);
void websocket_message_task(void *pvParameters);  // WebSocket message processing task
void handle_text_message(char *message, size_t len);
void handle_binary_message(const uint8_t *data, size_t data_len);
void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data);
bool ws_send_json(cJSON *json);
bool ws_send_binary(uint8_t *data, size_t len);
esp_websocket_client_handle_t get_ws_client();
uint8_t* alloc_chunk();
void free_chunk(uint8_t *buf);
void cleanup_resources();
void send_reject_message(const char* reason, const char* current_state_str);
#ifdef CONFIG_CAMERA_ENABLED
bool upload_image_to_server(uint8_t *image_data, size_t image_len);
#endif
void reconnect_websocket();
uint8_t* strip_wav_header(uint8_t *data, size_t *len);

#endif // MAIN_H