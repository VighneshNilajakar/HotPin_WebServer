/*
 * HotPin Firmware - Audio Capture, Send and Playback
 */

#include "main.h"

// Global handles for tasks
TaskHandle_t audio_capture_task_handle = NULL;
TaskHandle_t audio_send_task_handle = NULL;
TaskHandle_t audio_playback_task_handle = NULL;

// audio_i2s_initialized and i2s_mutex are defined in globals.c

bool init_i2s() {
    // Create I2S mutex if not exists
    if (!i2s_mutex) {
        i2s_mutex = xSemaphoreCreateMutex();
        if (!i2s_mutex) {
            ESP_LOGE("I2S", "Failed to create I2S mutex");
            return false;
        }
    }
    
    if (xSemaphoreTake(i2s_mutex, pdMS_TO_TICKS(5000)) != pdTRUE) {
        ESP_LOGE("I2S", "Failed to take I2S mutex");
        return false;
    }
    
    if (audio_i2s_initialized) {
        // Already initialized
        xSemaphoreGive(i2s_mutex);
        return true;
    }

    i2s_config_t i2s_config_rx = {
        .mode = I2S_MODE_MASTER | I2S_MODE_RX,
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = BITS_PER_SAMPLE,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,  // Mono
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

    i2s_pin_config_t pin_config = {
        .bck_io_num = GPIO_BCLK,
        .ws_io_num = GPIO_LRCLK,
        .data_out_num = -1,  // Not used for RX
        .data_in_num = GPIO_MIC_SD
    };

    esp_err_t err = i2s_driver_install(I2S_PORT, &i2s_config_rx, 0, NULL);
    if (err != ESP_OK) {
        ESP_LOGE("I2S", "Failed to install I2S driver: %s", esp_err_to_name(err));
        return false;
    }

    err = i2s_set_pin(I2S_PORT, &pin_config);
    if (err != ESP_OK) {
        ESP_LOGE("I2S", "Failed to set I2S pin: %s", esp_err_to_name(err));
        i2s_driver_uninstall(I2S_PORT);
        xSemaphoreGive(i2s_mutex);
        return false;
    }

    audio_i2s_initialized = true;
    ESP_LOGI("I2S", "I2S initialized successfully");
    xSemaphoreGive(i2s_mutex);
    return true;
}

bool uninstall_i2s() {
    if (!i2s_mutex) {
        ESP_LOGW("I2S", "I2S mutex not initialized");
        return false;
    }
    
    if (xSemaphoreTake(i2s_mutex, pdMS_TO_TICKS(5000)) != pdTRUE) {
        ESP_LOGE("I2S", "Failed to take I2S mutex for uninstall");
        return false;
    }
    
    if (!audio_i2s_initialized) {
        xSemaphoreGive(i2s_mutex);
        return true;  // Already uninstalled
    }

    esp_err_t err = i2s_driver_uninstall(I2S_PORT);
    if (err != ESP_OK) {
        ESP_LOGE("I2S", "Failed to uninstall I2S driver: %s", esp_err_to_name(err));
        xSemaphoreGive(i2s_mutex);
        return false;
    }

    audio_i2s_initialized = false;
    ESP_LOGI("I2S", "I2S driver uninstalled");
    xSemaphoreGive(i2s_mutex);
    return true;
}

void audio_capture_task(void *pvParameters) {
    audio_capture_task_handle = xTaskGetCurrentTaskHandle();
    
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        if (current_state == CLIENT_STATE_RECORDING) {
            // Check if I2S is initialized before attempting to read
            if (!audio_i2s_initialized) {
                ESP_LOGW("AUDIO", "I2S not initialized, waiting...");
                vTaskDelay(pdMS_TO_TICKS(100));
                continue;
            }
            
            // Allocate a chunk for audio data
            uint8_t *buf = alloc_chunk();
            if (!buf) {
                // Chunk pool exhausted
                ESP_LOGE("AUDIO", "Buffer pool exhausted during recording");
                
                // Send error to server
                cJSON *json = cJSON_CreateObject();
                cJSON_AddStringToObject(json, "type", "error");
                cJSON_AddStringToObject(json, "session", SESSION_ID);
                cJSON_AddStringToObject(json, "state", "RECORDING");
                cJSON_AddStringToObject(json, "error", "buffer_overflow");
                cJSON_AddStringToObject(json, "detail", "Free chunk pool exhausted");
                
                // ws_send_json takes ownership of the JSON object
                // It will delete the object whether it succeeds or fails
                ws_send_json(json);
                // NOTE: json object is already deleted by ws_send_json
                // Do not call cJSON_Delete(json) here to avoid double-free
                
                // Transition to processing state
                set_state(CLIENT_STATE_PROCESSING);
                continue;
            }

            // Read audio data from I2S with mutex protection
            size_t bytes_read = 0;
            esp_err_t err = ESP_FAIL;
            
            if (i2s_mutex && xSemaphoreTake(i2s_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                if (audio_i2s_initialized) {
                    err = i2s_read(I2S_PORT, buf, CHUNK_BYTES, &bytes_read, pdMS_TO_TICKS(1000));
                }
                xSemaphoreGive(i2s_mutex);
            } else {
                ESP_LOGW("AUDIO", "Could not take I2S mutex, skipping read");
                free_chunk(buf);
                vTaskDelay(pdMS_TO_TICKS(10));
                continue;
            }
            
            if (err != ESP_OK || bytes_read != CHUNK_BYTES) {
                ESP_LOGE("AUDIO", "I2S read failed: %s, bytes read: %d", 
                         esp_err_to_name(err), bytes_read);
                
                // Return buffer to pool
                free_chunk(buf);
                
                // Send error to server
                cJSON *json = cJSON_CreateObject();
                cJSON_AddStringToObject(json, "type", "error");
                cJSON_AddStringToObject(json, "session", SESSION_ID);
                cJSON_AddStringToObject(json, "state", "RECORDING");
                cJSON_AddStringToObject(json, "error", "i2s_read_timeout");
                cJSON_AddStringToObject(json, "detail", "Failed to read expected bytes from I2S");
                
                ws_send_json(json);
                // NOTE: json object is already deleted by ws_send_json
                // Do not call cJSON_Delete(json) here to avoid double-free
                
                // Transition to processing state
                set_state(CLIENT_STATE_PROCESSING);
                continue;
            }

            // Create audio chunk structure
            audio_chunk_t chunk;
            chunk.data = buf;
            chunk.len = bytes_read;
            chunk.seq = next_seq++;
            chunk.timestamp = xTaskGetTickCount();

            // Send to send queue
            if (xQueueSend(q_capture_to_send, &chunk, portMAX_DELAY) != pdTRUE) {
                ESP_LOGE("AUDIO", "Failed to send chunk to capture queue");
                free_chunk(buf);
            }
        } else {
            // Not recording, wait a bit before checking again
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }

    vTaskDelete(NULL);
}

void audio_send_task(void *pvParameters) {
    audio_send_task_handle = xTaskGetCurrentTaskHandle();
    
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        audio_chunk_t chunk;
        if (xQueueReceive(q_capture_to_send, &chunk, pdMS_TO_TICKS(100)) == pdTRUE) {
            // Wait for WebSocket to be ready before sending
            int retry_count = 0;
            esp_websocket_client_handle_t ws = get_ws_client();
            while (!esp_websocket_client_is_connected(ws) && retry_count < 50) {
                vTaskDelay(pdMS_TO_TICKS(10));
                retry_count++;
            }
            
            if (!esp_websocket_client_is_connected(ws)) {
                ESP_LOGW("AUDIO", "WebSocket not connected, dropping audio chunk %"PRIu32, chunk.seq);
                free_chunk(chunk.data);
                continue;
            }
            
            // Send chunk metadata
            cJSON *meta_json = cJSON_CreateObject();
            cJSON_AddStringToObject(meta_json, "type", "audio_chunk_meta");
            cJSON_AddStringToObject(meta_json, "session", SESSION_ID);
            cJSON_AddNumberToObject(meta_json, "seq", chunk.seq);
            cJSON_AddNumberToObject(meta_json, "len", chunk.len);

            // ws_send_json takes ownership of the JSON object
            // It will delete the object whether it succeeds or fails
            if (!ws_send_json(meta_json)) {
                ESP_LOGE("AUDIO", "Failed to send audio chunk metadata for seq %"PRIu32, chunk.seq);
                // NOTE: meta_json object is already deleted by ws_send_json on failure
                // Do not call cJSON_Delete(meta_json) here to avoid double-free
                free_chunk(chunk.data);
                continue;
            }
            // NOTE: meta_json object is now owned by the WebSocket system on success
            // Do not call cJSON_Delete(meta_json) here to avoid premature deletion

            // Small delay to let metadata be processed
            vTaskDelay(pdMS_TO_TICKS(20));

            // Send binary chunk data
            if (!ws_send_binary(chunk.data, chunk.len)) {
                ESP_LOGE("AUDIO", "Failed to send audio chunk binary data for seq %"PRIu32, chunk.seq);
                free_chunk(chunk.data);
                continue;
            }

            // Return buffer to pool after successful send
            free_chunk(chunk.data);
            
            // Delay before next chunk to prevent overwhelming the WebSocket
            // At 16kHz mono PCM16, 16KB = 0.5s of audio
            // So this adds ~25ms overhead per 500ms chunk = 5% overhead
            vTaskDelay(pdMS_TO_TICKS(25));
        }
    }

    vTaskDelete(NULL);
}

void audio_playback_task(void *pvParameters) {
    audio_playback_task_handle = xTaskGetCurrentTaskHandle();
    
    // I2S configuration is now handled by set_state() function
    // when transitioning to/from PLAYING state

    while (current_state != CLIENT_STATE_SHUTDOWN) {
        audio_chunk_t chunk;
        if (xQueueReceive(q_playback, &chunk, pdMS_TO_TICKS(100)) == pdTRUE) {
            // Write audio data to I2S
            size_t bytes_written = 0;
            esp_err_t err = i2s_write(I2S_PORT, chunk.data, chunk.len, &bytes_written, portMAX_DELAY);
            
            if (err != ESP_OK || bytes_written != chunk.len) {
                ESP_LOGE("AUDIO", "I2S write failed: %s, bytes written: %d", 
                         esp_err_to_name(err), bytes_written);
                
                // Send error to server
                cJSON *json = cJSON_CreateObject();
                cJSON_AddStringToObject(json, "type", "error");
                cJSON_AddStringToObject(json, "session", SESSION_ID);
                cJSON_AddStringToObject(json, "state", "PLAYING");
                cJSON_AddStringToObject(json, "error", "playback_error");
                cJSON_AddStringToObject(json, "detail", "Failed to write to I2S for playback");
                
                ws_send_json(json);
                // NOTE: json object is already deleted by ws_send_json
                // Do not call cJSON_Delete(json) here to avoid double-free
                
                // Free the chunk data
                free_chunk(chunk.data);
                continue;
            }

            // Free the chunk data after playback
            free_chunk(chunk.data);
        } else {
            // No data to play, check if state has changed
            if (current_state != CLIENT_STATE_PLAYING) {
                break; // Exit if not in playing state
            }
        }
    }

    // I2S mode switching is now handled by set_state() function
    // No need to manually reconfigure here

    vTaskDelete(NULL);
}

// Helper function to handle WAV headers from server
uint8_t* strip_wav_header(uint8_t *data, size_t *len) {
    if (*len < 44) {
        return data; // Not enough data for WAV header
    }
    
    // Check for RIFF header
    if (data[0] == 'R' && data[1] == 'I' && data[2] == 'F' && data[3] == 'F' &&
        data[8] == 'W' && data[9] == 'A' && data[10] == 'V' && data[11] == 'E') {
        // This is a WAV file, skip header (44 bytes)
        *len -= 44;
        return data + 44;
    }
    
    return data; // Not a WAV file, return as-is
}