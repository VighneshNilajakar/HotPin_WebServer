/*
 * HotPin Firmware - Main Application
 * ESP32-CAM based multimodal assistant client
 */

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
#include "esp_heap_caps.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "nvs_flash.h"
#include "esp_netif.h"

#include "driver/gpio.h"
#include "driver/i2s.h"
#include "driver/ledc.h"

#include "cJSON.h"

#include "lwip/err.h"
#include "lwip/sys.h"
#include "lwip/sockets.h"
#include "lwip/dns.h"
#include "lwip/netdb.h"
#include "lwip/igmp.h"
#include "lwip/priv/tcp_priv.h"
#include "lwip/tcp.h"
#include "lwip/udp.h"
#include "lwip/priv/sockets_priv.h"

#include "esp_http_client.h"
#include "mbedtls/base64.h"
#include "main.h"

// Global state variables are defined in globals.c



// Forward declaration for configuration update task
void config_update_task(void *pvParameters);

// Main application entry point
void app_main()
{
    ESP_LOGI("HOTPIN", "Starting HotPin Firmware");

    // Initialize NVS first
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Initialize state mutex
    state_mutex = xSemaphoreCreateMutex();
    if (!state_mutex) {
        ESP_LOGE("HOTPIN", "Failed to create state mutex");
        return;
    }

    // Initialize PSRAM detection
    if (!init_psram_detection()) {
        ESP_LOGE("HOTPIN", "PSRAM initialization failed");
        // Continue but with limited functionality
    }

    // Initialize GPIO early but with minimal power draw
    if (!init_gpio()) {
        ESP_LOGE("HOTPIN", "Failed to initialize GPIO");
        return;
    }

    // Small delay to let power stabilize after GPIO initialization
    vTaskDelay(pdMS_TO_TICKS(100));

    // Create queues (must be created before init_chunk_pool)
    q_free_chunks = xQueueCreate(psram_available ? POOL_COUNT_WITH_PSRAM : POOL_COUNT_NO_PSRAM, sizeof(uint8_t*));
    q_capture_to_send = xQueueCreate(32, sizeof(audio_chunk_t));  // Buffer for captured chunks
    q_playback = xQueueCreate(16, sizeof(audio_chunk_t));  // Buffer for playback chunks
    q_ws_messages = xQueueCreate(16, sizeof(ws_message_t));  // Buffer for WebSocket messages

    if (!q_free_chunks || !q_capture_to_send || !q_playback || !q_ws_messages) {
        ESP_LOGE("HOTPIN", "Failed to create queues");
        cleanup_resources();
        return;
    }

    // Small delay to let memory allocation settle
    vTaskDelay(pdMS_TO_TICKS(50));

    // Initialize chunk pool (depends on q_free_chunks being created)
    if (!init_chunk_pool()) {
        ESP_LOGE("HOTPIN", "Failed to initialize chunk pool");
        return;
    }

    // Small delay to let memory pool initialization settle
    vTaskDelay(pdMS_TO_TICKS(50));

    // Initialize WiFi (most power intensive operation) after other components
    // Use error checking to catch initialization failures
    if (!init_wifi()) {
        ESP_LOGE("HOTPIN", "Failed to initialize WiFi");
        // Continue but without WiFi connectivity
        // The system can still operate in local mode
    }

    // Small delay after WiFi initialization to let power stabilize
    vTaskDelay(pdMS_TO_TICKS(200));

    // Initialize WebSocket client after WiFi is ready
    // Wait for IP address to be assigned before starting WebSocket
    ESP_LOGI("HOTPIN", "Waiting for IP address before starting WebSocket...");
    int wait_count = 0;
    while (wait_count < 100) {  // Wait up to 10 seconds
        esp_netif_ip_info_t ip_info;
        esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
        if (netif && esp_netif_get_ip_info(netif, &ip_info) == ESP_OK && ip_info.ip.addr != 0) {
            ESP_LOGI("HOTPIN", "IP address obtained, initializing WebSocket");
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
        wait_count++;
    }
    
    if (!init_websocket()) {
        ESP_LOGW("HOTPIN", "Failed to initialize WebSocket, will retry in background");
        // Continue - the websocket task will attempt reconnection
    }

    // Don't set state to CONNECTED yet - let websocket_task handle the handshake first
    // The state will be set to CONNECTED->IDLE after hello/client_on messages are sent

    // Initialize I2S driver in RX mode (for microphone recording)
    if (!init_i2s()) {
        ESP_LOGE("HOTPIN", "Failed to initialize I2S driver");
        // Continue - will retry when needed
    }

    // Small delay before creating tasks
    vTaskDelay(pdMS_TO_TICKS(100));

    // Create tasks
    xTaskCreate(&state_manager_task, "state_manager", TASK_STACK_SIZE_BUTTON, NULL, 5, NULL);
    xTaskCreate(&button_task, "button", TASK_STACK_SIZE_BUTTON, NULL, 5, NULL);
    xTaskCreate(&websocket_task, "websocket", TASK_STACK_SIZE_WS, NULL, 5, NULL);  // WebSocket connection and handshake task
    xTaskCreate(&websocket_message_task, "websocket_message", 8192, NULL, 5, NULL);  // WebSocket message processing task
    
    // Only create audio and camera tasks after system is stable
    xTaskCreate(&audio_capture_task, "audio_capture", TASK_STACK_SIZE_AUDIO_CAPTURE, NULL, 5, NULL);
    xTaskCreate(&audio_send_task, "audio_send", TASK_STACK_SIZE_AUDIO_SEND, NULL, 5, NULL);
    xTaskCreate(&audio_playback_task, "audio_playback", TASK_STACK_SIZE_AUDIO_PLAYBACK, NULL, 5, NULL);
    xTaskCreate(&camera_task, "camera", TASK_STACK_SIZE_CAMERA, NULL, 4, NULL);

    ESP_LOGI("HOTPIN", "All tasks created, system ready");
    // Don't call set_state(CLIENT_STATE_IDLE) here - websocket_task will do it after handshake

    // Task will be deleted by state manager when shutdown occurs
    vTaskDelete(NULL);
}