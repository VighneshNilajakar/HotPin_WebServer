/*
 * HotPin Firmware - State Management and Button Handling
 */

#include "main.h"
#include "esp_timer.h"  // For esp_timer_get_time()

// These are defined as global variables in main.c
extern TaskHandle_t camera_task_handle;

void set_state(client_state_t new_state) {
    if (xSemaphoreTake(state_mutex, portMAX_DELAY) == pdTRUE) {
        client_state_t old_state = current_state;
        current_state = new_state;
        
        // Handle I2S mode switching when entering/leaving RECORDING state
        if (new_state == CLIENT_STATE_RECORDING && old_state != CLIENT_STATE_RECORDING) {
            // Entering RECORDING state - ensure I2S is in RX mode
            ESP_LOGI("STATE", "Switching I2S to RX mode for recording");
            uninstall_i2s();  // Use the safe mutex-protected uninstall function
            
            // Wait a bit for uninstall to complete
            vTaskDelay(pdMS_TO_TICKS(50));
            
            i2s_config_t i2s_config_rx = {
                .mode = I2S_MODE_MASTER | I2S_MODE_RX,
                .sample_rate = SAMPLE_RATE,
                .bits_per_sample = BITS_PER_SAMPLE,
                .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
                .communication_format = I2S_COMM_FORMAT_STAND_I2S,
                .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
                .dma_buf_count = 4,
                .dma_buf_len = 1024,
                .use_apll = false,
                .tx_desc_auto_clear = true,
                .fixed_mclk = 0,
                .mclk_multiple = I2S_MCLK_MULTIPLE_128,
                .bits_per_chan = I2S_BITS_PER_CHAN_DEFAULT
            };
            
            // Take I2S mutex to safely reinstall
            if (i2s_mutex && xSemaphoreTake(i2s_mutex, pdMS_TO_TICKS(5000)) == pdTRUE) {
                if (i2s_driver_install(I2S_PORT, &i2s_config_rx, 0, NULL) == ESP_OK) {
                    i2s_pin_config_t pin_config = {
                        .bck_io_num = GPIO_BCLK,
                        .ws_io_num = GPIO_LRCLK,
                        .data_out_num = -1,
                        .data_in_num = GPIO_MIC_SD
                    };
                    i2s_set_pin(I2S_PORT, &pin_config);
                    audio_i2s_initialized = true;  // Update the flag
                    ESP_LOGI("STATE", "I2S configured for RX mode (recording)");
                } else {
                    ESP_LOGE("STATE", "Failed to configure I2S for RX mode");
                }
                xSemaphoreGive(i2s_mutex);
            }
        } else if (new_state == CLIENT_STATE_PLAYING && old_state != CLIENT_STATE_PLAYING) {
            // Entering PLAYING state - ensure I2S is in TX mode
            ESP_LOGI("STATE", "Switching I2S to TX mode for playback");
            uninstall_i2s();  // Use the safe mutex-protected uninstall function
            
            // Wait a bit for uninstall to complete
            vTaskDelay(pdMS_TO_TICKS(50));
            
            i2s_config_t i2s_config_tx = {
                .mode = I2S_MODE_MASTER | I2S_MODE_TX,
                .sample_rate = SAMPLE_RATE,
                .bits_per_sample = BITS_PER_SAMPLE,
                .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
                .communication_format = I2S_COMM_FORMAT_STAND_I2S,
                .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
                .dma_buf_count = 4,
                .dma_buf_len = 1024,
                .use_apll = false,
                .tx_desc_auto_clear = true,
                .fixed_mclk = 0,
                .mclk_multiple = I2S_MCLK_MULTIPLE_128,
                .bits_per_chan = I2S_BITS_PER_CHAN_DEFAULT
            };
            
            // Take I2S mutex to safely reinstall
            if (i2s_mutex && xSemaphoreTake(i2s_mutex, pdMS_TO_TICKS(5000)) == pdTRUE) {
                if (i2s_driver_install(I2S_PORT, &i2s_config_tx, 0, NULL) == ESP_OK) {
                    i2s_pin_config_t pin_config = {
                        .bck_io_num = GPIO_BCLK,
                        .ws_io_num = GPIO_LRCLK,
                        .data_out_num = GPIO_DAC_SD,
                        .data_in_num = -1
                    };
                    i2s_set_pin(I2S_PORT, &pin_config);
                    audio_i2s_initialized = true;  // Update the flag
                    ESP_LOGI("STATE", "I2S configured for TX mode (playback)");
                } else {
                    ESP_LOGE("STATE", "Failed to configure I2S for TX mode");
                }
                xSemaphoreGive(i2s_mutex);
            }
        }
        
        // Send appropriate protocol message to server based on state transition
        cJSON *json = NULL;
        
        // Only send specific protocol messages, not generic "state" updates
        // The server expects: client_on, recording_started, recording_stopped,
        // ready_for_playback, playback_complete, image_captured, ping
        
        if (new_state == CLIENT_STATE_IDLE && old_state == CLIENT_STATE_CONNECTED) {
            // Initial transition to idle after connection
            json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "client_on");
        } else if (new_state == CLIENT_STATE_RECORDING && old_state != CLIENT_STATE_RECORDING) {
            // Starting recording
            json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "recording_started");
            cJSON_AddNumberToObject(json, "ts", (double)(esp_timer_get_time() / 1000));
        } else if (old_state == CLIENT_STATE_RECORDING && new_state != CLIENT_STATE_RECORDING) {
            // Stopped recording
            json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "recording_stopped");
        } else if (new_state == CLIENT_STATE_PROCESSING && old_state == CLIENT_STATE_RECORDING) {
            // Already sent recording_stopped above
        } else if (new_state == CLIENT_STATE_PLAYING) {
            // Ready to receive playback audio
            json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "ready_for_playback");
        } else if (old_state == CLIENT_STATE_PLAYING && new_state == CLIENT_STATE_IDLE) {
            // Playback completed
            json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "playback_complete");
        }
        // Note: Other state changes like CONNECTED, STALLED, SHUTDOWN don't need explicit messages
        // The WebSocket connection/disconnection events handle those
        
        if (json) {
            if (!ws_send_json(json)) {
                ESP_LOGE("STATE", "Failed to send state change to server");
            }
            cJSON_Delete(json);
        }
        
        // Update LED pattern
        update_led_pattern();
        
        ESP_LOGI("STATE", "State changed: %s -> %s", 
                 state_to_string(old_state), state_to_string(new_state));
        
        xSemaphoreGive(state_mutex);
    }
}

const char* state_to_string(client_state_t state) {
    switch (state) {
        case CLIENT_STATE_BOOTING: return "BOOTING";
        case CLIENT_STATE_CONNECTED: return "CONNECTED";
        case CLIENT_STATE_IDLE: return "IDLE";
        case CLIENT_STATE_RECORDING: return "RECORDING";
        case CLIENT_STATE_PROCESSING: return "PROCESSING";
        case CLIENT_STATE_PLAYING: return "PLAYING";
        case CLIENT_STATE_CAMERA_CAPTURE: return "CAMERA_CAPTURE";
        case CLIENT_STATE_STALLED: return "STALLED";
        case CLIENT_STATE_SHUTDOWN: return "SHUTDOWN";
        default: return "UNKNOWN";
    }
}

void update_led_pattern() {
    // Update LED based on current state
    switch (current_state) {
        case CLIENT_STATE_IDLE:
            // Slow blink
            gpio_set_level(GPIO_LED, 1);
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(GPIO_LED, 0);
            vTaskDelay(pdMS_TO_TICKS(900));
            break;
            
        case CLIENT_STATE_RECORDING:
            // Fast blink
            gpio_set_level(GPIO_LED, 1);
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(GPIO_LED, 0);
            vTaskDelay(pdMS_TO_TICKS(100));
            break;
            
        case CLIENT_STATE_PROCESSING:
            // Medium blink
            gpio_set_level(GPIO_LED, 1);
            vTaskDelay(pdMS_TO_TICKS(300));
            gpio_set_level(GPIO_LED, 0);
            vTaskDelay(pdMS_TO_TICKS(300));
            break;
            
        case CLIENT_STATE_PLAYING:
            // Continuous on
            gpio_set_level(GPIO_LED, 1);
            break;
            
        case CLIENT_STATE_CAMERA_CAPTURE:
            // Triple quick blink
            for (int i = 0; i < 3; i++) {
                gpio_set_level(GPIO_LED, 1);
                vTaskDelay(pdMS_TO_TICKS(50));
                gpio_set_level(GPIO_LED, 0);
                vTaskDelay(pdMS_TO_TICKS(50));
            }
            break;
            
        default:
            // Turn off LED for other states
            gpio_set_level(GPIO_LED, 0);
            break;
    }
}

bool init_psram_detection() {
    psram_available = esp_psram_is_initialized();
    if (psram_available) {
        size_t psram_size = esp_psram_get_size();
        ESP_LOGI("PSRAM", "PSRAM available: %zu bytes", psram_size);
        pool_size = POOL_COUNT_WITH_PSRAM;
    } else {
        ESP_LOGI("PSRAM", "No PSRAM available, using internal RAM");
        pool_size = POOL_COUNT_NO_PSRAM;
    }
    return true;
}

bool init_chunk_pool() {
    int total_size = pool_size * CHUNK_BYTES;
    
    if (psram_available) {
        // Allocate from PSRAM if available
        chunk_pool = (uint8_t*)heap_caps_malloc(total_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA);
        ESP_LOGI("POOL", "Allocated %d bytes chunk pool from PSRAM", total_size);
    } else {
        // Allocate from internal RAM with DMA capability
        chunk_pool = (uint8_t*)heap_caps_malloc(total_size, MALLOC_CAP_DMA);
        ESP_LOGI("POOL", "Allocated %d bytes chunk pool from internal RAM", total_size);
    }
    
    if (!chunk_pool) {
        ESP_LOGE("POOL", "Failed to allocate chunk pool");
        return false;
    }
    
    // Initialize the free chunks queue with pointers to each chunk
    for (int i = 0; i < pool_size; i++) {
        uint8_t *chunk_ptr = chunk_pool + (i * CHUNK_BYTES);
        if (xQueueSend(q_free_chunks, &chunk_ptr, 0) != pdTRUE) {
            ESP_LOGE("POOL", "Failed to add chunk %d to free queue", i);
            return false;
        }
    }
    
    return true;
}

uint8_t* alloc_chunk() {
    uint8_t *buf = NULL;
    if (xQueueReceive(q_free_chunks, &buf, 0) != pdTRUE) {
        // No free chunks available
        ESP_LOGW("ALLOC", "No free chunks available in pool");
        return NULL;
    }
    return buf;
}

void free_chunk(uint8_t *buf) {
    if (buf) {
        if (xQueueSend(q_free_chunks, &buf, 0) != pdTRUE) {
            // Queue full, should not happen if pool is properly managed
            ESP_LOGE("FREE", "Failed to return chunk to pool");
        }
    }
}

void button_task(void *pvParameters) {
    TickType_t last_press_time = 0;
    int press_count = 0;
    TickType_t long_press_start = 0;
    bool long_press_detected = false;
    
    TickType_t last_debounce_time = xTaskGetTickCount();
    
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        TickType_t current_time = xTaskGetTickCount();
        
        // Read button state (active LOW - button press pulls to GND)
        // GPIO_BUTTON has internal pull-up configured, so:
        // - Released (default): reads HIGH (1)
        // - Pressed (short to GND): reads LOW (0)
        bool button_pressed = (gpio_get_level(GPIO_BUTTON) == 0);
        
        if (button_pressed) {
            if (!long_press_detected && 
                (current_time - last_debounce_time) > pdMS_TO_TICKS(DEBOUNCE_MS)) {
                
                if (long_press_start == 0) {
                    long_press_start = current_time;
                }
                
                // Check for long press
                if ((current_time - long_press_start) >= pdMS_TO_TICKS(LONG_PRESS_MS)) {
                    long_press_detected = true;
                    ESP_LOGI("BUTTON", "Long press detected - initiating shutdown");
                    
                    if (xSemaphoreTake(state_mutex, portMAX_DELAY) == pdTRUE) {
                        if (current_state == CLIENT_STATE_RECORDING) {
                            // Stop recording before shutdown
                            set_state(CLIENT_STATE_PROCESSING);
                        }
                        set_state(CLIENT_STATE_SHUTDOWN);
                        xSemaphoreGive(state_mutex);
                    }
                }
            }
        } else {
            // Button released
            if (long_press_start > 0 && !long_press_detected) {
                // Valid short press
                if ((current_time - last_debounce_time) > pdMS_TO_TICKS(DEBOUNCE_MS)) {
                    last_debounce_time = current_time;
                    
                    // Check for double press
                    if (press_count == 0) {
                        press_count = 1;
                        last_press_time = current_time;
                    } else if (press_count == 1) {
                        if ((current_time - last_press_time) < pdMS_TO_TICKS(DOUBLE_PRESS_WINDOW_MS)) {
                            // Double press detected - camera capture
                            press_count = 0;
                            last_press_time = 0;
                            
                            if (current_state == CLIENT_STATE_IDLE) {
                                set_state(CLIENT_STATE_CAMERA_CAPTURE);
                                if (camera_task_handle) {
                                    xTaskNotifyGive(camera_task_handle);  // Wake up camera task
                                }
                            } else {
                                // Send reject if busy
                                send_reject_message("busy", state_to_string(current_state));
                            }
                        } else {
                            // Single press (not double)
                            press_count = 1;
                            last_press_time = current_time;
                        }
                    }
                }
            }
            
            long_press_start = 0;
            long_press_detected = false;
        }
        
        // Handle single press after timeout window
        if (press_count == 1 && 
            (current_time - last_press_time) >= pdMS_TO_TICKS(DOUBLE_PRESS_WINDOW_MS)) {
            
            // Execute single press action
            if (current_state == CLIENT_STATE_IDLE) {
                set_state(CLIENT_STATE_RECORDING);
            } else if (current_state == CLIENT_STATE_RECORDING) {
                set_state(CLIENT_STATE_PROCESSING);
            } else {
                // Send reject if busy
                send_reject_message("busy", state_to_string(current_state));
            }
            
            press_count = 0;
            last_press_time = 0;
        }
        
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    
    vTaskDelete(NULL);
}

void send_reject_message(const char* reason, const char* current_state_str) {
    cJSON *json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "type", "reject");
    cJSON_AddStringToObject(json, "session", SESSION_ID);
    cJSON_AddStringToObject(json, "reason", reason);
    cJSON_AddStringToObject(json, "current_state", current_state_str);
    
    if (!ws_send_json(json)) {
        ESP_LOGE("BUTTON", "Failed to send reject message to server");
    }
    cJSON_Delete(json);
    
    // Visual/audible feedback for reject
    for (int i = 0; i < 3; i++) {
        gpio_set_level(GPIO_LED, 1);
        vTaskDelay(pdMS_TO_TICKS(100));
        gpio_set_level(GPIO_LED, 0);
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void state_manager_task(void *pvParameters) {
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        // Monitor state changes and handle any special management tasks
        switch (current_state) {
            case CLIENT_STATE_SHUTDOWN:
                // Handle shutdown sequence
                ESP_LOGI("STATE", "Shutdown sequence initiated");
                // Additional shutdown steps can be added here
                break;
                
            case CLIENT_STATE_RECORDING:
                // Ensure audio capture is active
                break;
                
            case CLIENT_STATE_PLAYING:
                // Ensure audio playback is active
                break;
                
            default:
                break;
        }
        
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    
    // Clean up and shutdown
    cleanup_resources();
    ESP_LOGI("STATE", "Firmware shutdown complete");
    vTaskDelete(NULL);
}

void cleanup_resources() {
    // Free chunk pool
    if (chunk_pool) {
        heap_caps_free(chunk_pool);
        chunk_pool = NULL;
    }
    
    // Clean up queues
    if (q_free_chunks) {
        vQueueDelete(q_free_chunks);
        q_free_chunks = NULL;
    }
    
    if (q_capture_to_send) {
        vQueueDelete(q_capture_to_send);
        q_capture_to_send = NULL;
    }
    
    if (q_playback) {
        vQueueDelete(q_playback);
        q_playback = NULL;
    }
    
    // Clean up WebSocket message queue
    if (q_ws_messages) {
        vQueueDelete(q_ws_messages);
        q_ws_messages = NULL;
    }
    
    // Delete mutex
    if (state_mutex) {
        vSemaphoreDelete(state_mutex);
        state_mutex = NULL;
    }
    
    // Uninstall I2S driver
    i2s_driver_uninstall(I2S_PORT);
}

bool init_gpio() {
    ESP_LOGI("GPIO", "Initializing GPIO pins");
    
    // Configure button pin with internal pull-up
    gpio_config_t button_config = {
        .pin_bit_mask = (1ULL << GPIO_BUTTON),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE
    };
    
    esp_err_t err = gpio_config(&button_config);
    if (err != ESP_OK) {
        ESP_LOGE("GPIO", "Failed to configure button GPIO: %s", esp_err_to_name(err));
        return false;
    }
    
    // Configure LED pin
    gpio_config_t led_config = {
        .pin_bit_mask = (1ULL << GPIO_LED),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE
    };
    
    err = gpio_config(&led_config);
    if (err != ESP_OK) {
        ESP_LOGE("GPIO", "Failed to configure LED GPIO: %s", esp_err_to_name(err));
        return false;
    }
    
    // Initialize LED to OFF state
    gpio_set_level(GPIO_LED, 0);
    
    ESP_LOGI("GPIO", "GPIO initialization complete");
    return true;
}