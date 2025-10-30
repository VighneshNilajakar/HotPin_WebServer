/*
 * HotPin Firmware - Global Variables Definition
 */

#include "main.h"
#include "esp_system.h"
#include "esp_mac.h"
#include "esp_timer.h"

// Global state variables definition
client_state_t current_state = CLIENT_STATE_BOOTING;
QueueHandle_t q_free_chunks = NULL;
QueueHandle_t q_capture_to_send = NULL;
QueueHandle_t q_playback = NULL;
QueueHandle_t q_ws_messages = NULL;  // WebSocket message queue
SemaphoreHandle_t state_mutex = NULL;
SemaphoreHandle_t i2s_mutex = NULL;
uint32_t next_seq = 0;
bool psram_available = false;
bool audio_i2s_initialized = false;
uint8_t *chunk_pool = NULL;
int pool_size = 0;

// Also define the camera_task_handle here
TaskHandle_t camera_task_handle = NULL;

// Define the dynamically generated session ID with timestamp for uniqueness
char SESSION_ID[32] = {0};

// Initialize the session ID with a unique value based on MAC address and timestamp
void init_session_id() {
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    
    // Add timestamp and random component for extra uniqueness
    uint32_t timestamp = (uint32_t)(esp_timer_get_time() / 1000000); // Seconds since boot
    uint32_t random_val = esp_random();  // Add random component for extra uniqueness
    
    // Format as "hotpin-XXYYZZ-TTTTTT-RRRR" where:
    // XXYYZZ are last 3 bytes of MAC 
    // TTTTTT is timestamp (seconds since boot)
    // RRRR is random value
    snprintf(SESSION_ID, sizeof(SESSION_ID), "hotpin-%02x%02x%02x-%06lx-%04lx", 
             mac[3], mac[4], mac[5], (unsigned long)(timestamp & 0xFFFFFF), (unsigned long)(random_val & 0xFFFF));
    ESP_LOGI("HOTPIN", "Generated unique session ID: %s", SESSION_ID);
}