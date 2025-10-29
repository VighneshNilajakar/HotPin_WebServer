/*
 * HotPin Firmware - Global Variables Definition
 */

#include "main.h"

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