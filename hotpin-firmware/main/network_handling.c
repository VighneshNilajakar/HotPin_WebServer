/*
 * HotPin Firmware - Network and WebSocket Handling
 */

#include "main.h"

// Forward declaration for message processing task
void websocket_message_task(void *pvParameters);

static esp_websocket_client_handle_t ws_client = NULL;
static bool ws_connected = false;
static bool ws_handshake_complete = false;  // Track if initial handshake is done
static char effective_ws_url[256] = {0};

bool init_wifi() {
    ESP_LOGI("WIFI", "Initializing WiFi");
    
    // Initialize TCP/IP stack
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    // Initialize default station
    esp_netif_create_default_wifi_sta();

    // WiFi configuration with error checking
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_err_t err = esp_wifi_init(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE("WIFI", "Failed to initialize WiFi: %s", esp_err_to_name(err));
        return false;
    }

    // Set WiFi mode to station
    err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err != ESP_OK) {
        ESP_LOGE("WIFI", "Failed to set WiFi mode: %s", esp_err_to_name(err));
        return false;
    }

    // WiFi station configuration with validation
    wifi_config_t wifi_config = {
        .sta = {
            .ssid = CONFIG_ESP_WIFI_SSID,
            .password = CONFIG_ESP_WIFI_PASSWORD,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    
    // Validate that SSID is set
    if (strlen((char*)wifi_config.sta.ssid) == 0) {
        ESP_LOGW("WIFI", "WiFi SSID is empty, skipping WiFi connection");
        ESP_LOGW("WIFI", "Please set CONFIG_ESP_WIFI_SSID in menuconfig or Kconfig.projbuild");
        // Continue with WiFi initialized but not connected
    } else {
        // Validate that the SSID length is acceptable
        if (strlen((char*)wifi_config.sta.ssid) > 32) {
            ESP_LOGE("WIFI", "WiFi SSID too long (max 32 characters)");
            return false;
        }
        
        // Validate password length if provided
        if (strlen((char*)wifi_config.sta.password) > 64) {
            ESP_LOGE("WIFI", "WiFi password too long (max 64 characters)");
            return false;
        }
        
        err = esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
        if (err != ESP_OK) {
            ESP_LOGE("WIFI", "Failed to set WiFi configuration: %s", esp_err_to_name(err));
            return false;
        }
        
        // Start WiFi BEFORE connecting
        ESP_LOGI("WIFI", "Starting WiFi...");
        err = esp_wifi_start();
        if (err != ESP_OK) {
            ESP_LOGE("WIFI", "Failed to start WiFi: %s", esp_err_to_name(err));
            return false;
        }
        
        // Only connect if password is provided
        if (strlen((char*)wifi_config.sta.password) > 0) {
            ESP_LOGI("WIFI", "Connecting to WiFi network: %s", wifi_config.sta.ssid);
            err = esp_wifi_connect();
            if (err != ESP_OK) {
                ESP_LOGE("WIFI", "Failed to connect to WiFi: %s", esp_err_to_name(err));
                return false;
            }
        } else {
            ESP_LOGW("WIFI", "No WiFi password provided, assuming open network");
        }
    }

    ESP_LOGI("WIFI", "WiFi initialization complete");
    return true;
}

bool init_websocket() {
    ESP_LOGI("WS", "Initializing WebSocket client");
    
    // Initialize dynamic configuration management
    if (!init_dynamic_config()) {
        ESP_LOGW("WS", "Failed to initialize dynamic configuration, continuing with defaults");
    }
    
    // Get the local IP address to create a WebSocket URL for local connections
    esp_netif_ip_info_t ip_info;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    char local_ws_url[256] = {0};
    
    if (esp_netif_get_ip_info(netif, &ip_info) == ESP_OK) {
        // Format the local WebSocket URL
        uint8_t *ip = (uint8_t*)&ip_info.ip.addr;
        snprintf(local_ws_url, sizeof(local_ws_url), "ws://%d.%d.%d.%d:8000/ws", ip[0], ip[1], ip[2], ip[3]);
        
        // Print the local WebSocket URL that clients can use to connect
        ESP_LOGI("WS", "Local WebSocket URL for client connections: %s", local_ws_url);
        ESP_LOGI("WS", "Connect other devices to this URL to interact with this HotPin device on the local network");
    }
    
    // WebSocket configuration
    // Use the dynamic WebSocket URL if available, otherwise fall back to local or configured URL
    const char* ws_url = get_current_ws_url();
    ESP_LOGI("WS", "Using WebSocket URL: %s", ws_url);
    
    // Set up WebSocket headers with authorization
    char auth_header[256];
    snprintf(auth_header, sizeof(auth_header), "Authorization: Bearer %s\r\n", HOTPIN_WS_TOKEN);
    
    // Initialize WebSocket client with authentication headers
    esp_websocket_client_config_t websocket_cfg = {
        .uri = ws_url,
        .user_agent = "HotPin-Firmware-Client/1.0",
        .headers = auth_header
    };
    
    // Initialize WebSocket client
    ws_client = esp_websocket_client_init(&websocket_cfg);
    
    // Set event handler
    esp_websocket_register_events(ws_client, WEBSOCKET_EVENT_ANY, websocket_event_handler, (void*)ws_client);
    
    // Start WebSocket client
    esp_err_t err = esp_websocket_client_start(ws_client);
    if (err != ESP_OK) {
        ESP_LOGE("WS", "Failed to start WebSocket client: %s", esp_err_to_name(err));
        return false;
    }
    
    ESP_LOGI("WS", "WebSocket client initialized");
    return true;
}

void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;
    
    switch (event_id) {
        case WEBSOCKET_EVENT_CONNECTED:
            ESP_LOGI("WS", "WebSocket connected");
            ws_connected = true;
            
            // DO NOT send messages from event handler - they will fail!
            // The WebSocket internal buffers are not fully ready yet.
            // Messages will be sent from the main task loop after a proper delay.
            break;
            
        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGW("WS", "WebSocket disconnected");
            ws_connected = false;
            ws_handshake_complete = false;  // Reset handshake flag on disconnect
            
            if (current_state != CLIENT_STATE_SHUTDOWN) {
                set_state(CLIENT_STATE_STALLED);
                
                // Attempt to reconnect with exponential backoff
                reconnect_websocket();
            }
            break;
            
        case WEBSOCKET_EVENT_DATA:
            if (data->op_code == WS_TRANSPORT_OPCODES_TEXT) {
                // Handle text message
                handle_text_message((char*)data->data_ptr, data->data_len);
            } else if (data->op_code == WS_TRANSPORT_OPCODES_BINARY) {
                // Handle binary message (TTS audio from server)
                handle_binary_message((uint8_t*)data->data_ptr, data->data_len);
            }
            break;
            
        case WEBSOCKET_EVENT_ERROR:
            ESP_LOGE("WS", "WebSocket error");
            ws_connected = false;
            break;
    }
}

void handle_text_message(char *message, size_t len) {
    cJSON *json = cJSON_Parse(message);
    if (!json) {
        ESP_LOGE("WS", "Failed to parse WebSocket text message");
        return;
    }
    
    const char *type = cJSON_GetStringValue(cJSON_GetObjectItem(json, "type"));
    if (!type) {
        cJSON_Delete(json);
        return;
    }
    
    if (strcmp(type, "ready") == 0) {
        ESP_LOGI("WS", "Server ready message received");
        set_state(CLIENT_STATE_IDLE);
    }
    else if (strcmp(type, "partial") == 0) {
        ESP_LOGI("WS", "Partial STT: %s", cJSON_GetStringValue(cJSON_GetObjectItem(json, "text")));
    }
    else if (strcmp(type, "llm") == 0) {
        ESP_LOGI("WS", "LLM Response: %s", cJSON_GetStringValue(cJSON_GetObjectItem(json, "text")));
    }
    else if (strcmp(type, "tts_ready") == 0) {
        // Server indicates TTS is ready for streaming
        ESP_LOGI("WS", "TTS ready received");
        
        // Check if we can play back audio
        if (current_state == CLIENT_STATE_IDLE || current_state == CLIENT_STATE_PROCESSING) {
            // Send ready_for_playback to server
            cJSON *ready_json = cJSON_CreateObject();
            cJSON_AddStringToObject(ready_json, "type", "ready_for_playback");
            cJSON_AddStringToObject(ready_json, "session", SESSION_ID);
            
            ws_send_json(ready_json);
            // Note: ws_send_json takes ownership of ready_json, so we don't delete it here
            
            set_state(CLIENT_STATE_PLAYING);
        } else {
            // Busy - send reject
            send_reject_message("busy", state_to_string(current_state));
        }
    }
    else if (strcmp(type, "tts_chunk_meta") == 0) {
        // Server sends TTS chunk metadata, binary data follows
        // The binary data will be handled separately
        ESP_LOGD("WS", "TTS chunk metadata received");
    }
    else if (strcmp(type, "tts_done") == 0) {
        // Server indicates TTS streaming is complete
        ESP_LOGI("WS", "TTS streaming complete");
        
        // Send playback complete message
        cJSON *complete_json = cJSON_CreateObject();
        cJSON_AddStringToObject(complete_json, "type", "playback_complete");
        cJSON_AddStringToObject(complete_json, "session", SESSION_ID);
        
        ws_send_json(complete_json);
        // Note: ws_send_json takes ownership of complete_json, so we don't delete it here
        
        set_state(CLIENT_STATE_IDLE);
    }
    else if (strcmp(type, "image_received") == 0) {
        ESP_LOGI("WS", "Image received by server");
        // Could provide user feedback here
    }
    else if (strcmp(type, "request_rerecord") == 0) {
        // Server requests re-recording
        const char *reason = cJSON_GetStringValue(cJSON_GetObjectItem(json, "reason"));
        ESP_LOGW("WS", "Server requested re-record: %s", reason ? reason : "unknown");
        
        if (current_state == CLIENT_STATE_IDLE) {
            // Indicate need for user to re-record
            // Could flash LED or play sound
            for (int i = 0; i < 5; i++) {
                gpio_set_level(GPIO_LED, 1);
                vTaskDelay(pdMS_TO_TICKS(200));
                gpio_set_level(GPIO_LED, 0);
                vTaskDelay(pdMS_TO_TICKS(200));
            }
        } else if (current_state == CLIENT_STATE_PROCESSING) {
            // Still in processing state, just note the request
            set_state(CLIENT_STATE_IDLE); // Clear processing state
            
            // Flash LED to indicate re-recording needed
            for (int i = 0; i < 5; i++) {
                gpio_set_level(GPIO_LED, 1);
                vTaskDelay(pdMS_TO_TICKS(200));
                gpio_set_level(GPIO_LED, 0);
                vTaskDelay(pdMS_TO_TICKS(200));
            }
        } else {
            // Can't re-record now, server will request again
            send_reject_message("busy", state_to_string(current_state));
        }
    }
    else if (strcmp(type, "offer_download") == 0) {
        const char *url = cJSON_GetStringValue(cJSON_GetObjectItem(json, "url"));
        ESP_LOGW("WS", "Server offered download: %s", url ? url : "unknown");
        
        // For now, we'll just log it since we expect streaming
    }
    else if (strcmp(type, "state_sync") == 0) {
        const char *server_state = cJSON_GetStringValue(cJSON_GetObjectItem(json, "server_state"));
        const char *message = cJSON_GetStringValue(cJSON_GetObjectItem(json, "message"));
        
        ESP_LOGI("WS", "State sync from server: %s - %s", 
                 server_state ? server_state : "unknown",
                 message ? message : "no message");
    }
    else if (strcmp(type, "request_user_intervention") == 0) {
        const char *message = cJSON_GetStringValue(cJSON_GetObjectItem(json, "message"));
        ESP_LOGW("WS", "Server requires user intervention: %s", message ? message : "unknown");
        
        // Rapid flash LED to indicate issue
        for (int i = 0; i < 10; i++) {
            gpio_set_level(GPIO_LED, 1);
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(GPIO_LED, 0);
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }
    else if (strcmp(type, "ack") == 0) {
        // Acknowledgment from server
        int seq = cJSON_GetNumberValue(cJSON_GetObjectItem(json, "seq"));
        const char *ref = cJSON_GetStringValue(cJSON_GetObjectItem(json, "ref"));
        ESP_LOGD("WS", "Ack received for %s seq %d", ref ? ref : "unknown", seq);
    }
    
    cJSON_Delete(json);
}

void handle_binary_message(const uint8_t *data, size_t data_len) {
    if (current_state == CLIENT_STATE_PLAYING) {
        // Allocate a chunk for the binary data
        uint8_t *buf = alloc_chunk();
        if (buf && data_len <= CHUNK_BYTES) {
            // Copy data to our buffer
            memcpy(buf, data, data_len);
            
            // Create audio chunk for playback queue
            audio_chunk_t chunk;
            chunk.data = buf;
            chunk.len = data_len;
            chunk.seq = 0;  // Not used for playback
            chunk.timestamp = xTaskGetTickCount();
            
            // Send to playback queue
            if (xQueueSend(q_playback, &chunk, portMAX_DELAY) != pdTRUE) {
                ESP_LOGE("WS", "Failed to send TTS chunk to playback queue");
                free_chunk(buf);
            }
        } else {
            ESP_LOGE("WS", "Failed to allocate buffer for TTS data or data too large");
        }
    } else {
        ESP_LOGW("WS", "Received binary data while not in playing state, ignoring");
    }
}

bool ws_send_json(cJSON *json) {
    if (!ws_client) {
        ESP_LOGW("WS", "WebSocket client not initialized");
        // Clean up the JSON object since we're not sending it
        if (json) {
            cJSON_Delete(json);
        }
        return false;
    }
    
    // Use the official is_connected check
    if (!esp_websocket_client_is_connected(ws_client)) {
        ESP_LOGW("WS", "WebSocket not connected, cannot send JSON");
        // Clean up the JSON object since we're not sending it
        if (json) {
            cJSON_Delete(json);
        }
        return false;
    }
    
    // Create message structure for queue
    struct {
        cJSON *json;
        bool is_binary;
        uint8_t *data;
        size_t len;
    } message = {
        .json = json,
        .is_binary = false,
        .data = NULL,
        .len = 0
    };
    
    // Add message to queue
    if (xQueueSend(q_ws_messages, &message, pdMS_TO_TICKS(100)) != pdTRUE) {
        ESP_LOGE("WS", "Failed to queue WebSocket JSON message");
        // Clean up the JSON object since we couldn't queue it
        if (json) {
            cJSON_Delete(json);
        }
        return false;
    }
    
    return true;
}

bool ws_send_binary(uint8_t *data, size_t len) {
    if (!ws_client) {
        ESP_LOGW("WS", "WebSocket client not initialized");
        // Clean up the data since we're not sending it
        if (data) {
            free(data);
        }
        return false;
    }
    
    // Use the official is_connected check
    if (!esp_websocket_client_is_connected(ws_client)) {
        ESP_LOGW("WS", "WebSocket not connected, cannot send binary");
        // Clean up the data since we're not sending it
        if (data) {
            free(data);
        }
        return false;
    }
    
    // Create message structure for queue
    struct {
        cJSON *json;
        bool is_binary;
        uint8_t *data;
        size_t len;
    } message = {
        .json = NULL,
        .is_binary = true,
        .data = data,
        .len = len
    };
    
    // Add message to queue
    if (xQueueSend(q_ws_messages, &message, pdMS_TO_TICKS(100)) != pdTRUE) {
        ESP_LOGE("WS", "Failed to queue WebSocket binary message");
        // Clean up the data since we couldn't queue it
        if (data) {
            free(data);
        }
        return false;
    }
    
    return true;
}

esp_websocket_client_handle_t get_ws_client() {
    return ws_client;
}

void reconnect_websocket() {
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s cap
    int delay_seconds = 1;
    const int max_delay = 60; // 60 seconds max
    
    while (current_state != CLIENT_STATE_SHUTDOWN && !ws_connected) {
        ESP_LOGI("WS", "Attempting WebSocket reconnection in %d seconds...", delay_seconds);
        
        vTaskDelay(pdMS_TO_TICKS(delay_seconds * 1000));
        
        if (esp_websocket_client_is_connected(ws_client)) {
            // Already connected somehow
            break;
        }
        
        esp_err_t err = esp_websocket_client_start(ws_client);
        if (err == ESP_OK) {
            ESP_LOGI("WS", "WebSocket reconnected successfully");
            break;
        } else {
            ESP_LOGE("WS", "WebSocket reconnection failed: %s", esp_err_to_name(err));
            
            // Exponential backoff
            delay_seconds *= 2;
            if (delay_seconds > max_delay) {
                delay_seconds = max_delay;
            }
        }
    }
}

/**
 * @brief WebSocket message processing task
 * 
 * This task processes WebSocket messages from the queue to ensure they're
 * sent at appropriate times when the WebSocket connection is fully ready.
 * 
 * @param pvParameters Task parameters (unused)
 */
void websocket_task(void *pvParameters)
{
    ESP_LOGI("WS", "Starting WebSocket task - handling handshake and connection management");
    
    // Wait for WebSocket to be connected
    int wait_count = 0;
    const int max_wait = 50; // 5 seconds at 100ms intervals
    
    while (current_state != CLIENT_STATE_SHUTDOWN && wait_count < max_wait) {
        if (ws_connected && ws_handshake_complete) {
            ESP_LOGI("WS", "WebSocket already connected and handshake complete");
            break;
        } else if (ws_connected && !ws_handshake_complete) {
            ESP_LOGI("WS", "WebSocket connected, performing handshake...");
            
            // Send client_on message to complete handshake
            cJSON *hello_json = cJSON_CreateObject();
            cJSON_AddStringToObject(hello_json, "type", "client_on");
            cJSON_AddStringToObject(hello_json, "session", SESSION_ID);
            cJSON_AddStringToObject(hello_json, "version", "1.0"); // Add version info
            
            if (ws_send_json(hello_json)) {
                ESP_LOGI("WS", "Handshake message sent successfully");
                ws_handshake_complete = true;
                
                // Set state to IDLE after successful handshake
                set_state(CLIENT_STATE_IDLE);
            } else {
                ESP_LOGE("WS", "Failed to send handshake message");
            }
            break;
        } else {
            ESP_LOGD("WS", "Waiting for WebSocket connection... (%d/%d)", wait_count, max_wait);
            vTaskDelay(pdMS_TO_TICKS(100));
            wait_count++;
        }
    }
    
    if (current_state == CLIENT_STATE_SHUTDOWN) {
        ESP_LOGI("WS", "WebSocket task shutting down due to client shutdown");
        vTaskDelete(NULL);
    }
    
    if (!ws_connected) {
        ESP_LOGW("WS", "WebSocket connection not established after timeout, will continue to monitor");
    }
    
    // Continue monitoring connection status and handle reconnection if needed
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        if (!ws_connected) {
            // Attempt to reconnect
            ESP_LOGI("WS", "Attempting to reconnect WebSocket...");
            reconnect_websocket();
        }
        
        vTaskDelay(pdMS_TO_TICKS(1000)); // Check connection status every second
    }
    
    ESP_LOGI("WS", "WebSocket task stopping");
    vTaskDelete(NULL);
}

void websocket_message_task(void *pvParameters)
{
    ESP_LOGI("WS", "Starting WebSocket message processing task");
    
    // Message structure for queue
    struct {
        cJSON *json;        // JSON message to send (NULL if binary)
        bool is_binary;     // Flag indicating if this is a binary message
        uint8_t *data;      // Binary data (if is_binary is true)
        size_t len;         // Length of binary data
    } message;
    
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        // Wait for messages in the queue with a timeout
        if (xQueueReceive(q_ws_messages, &message, pdMS_TO_TICKS(1000)) == pdTRUE) {
            // Process the message directly without recursion
            if (message.is_binary) {
                // Send binary message directly using ESP-IDF API
                if (message.data && message.len > 0 && ws_client) {
                    if (esp_websocket_client_is_connected(ws_client)) {
                        esp_err_t err = esp_websocket_client_send_bin(ws_client, (char*)message.data, message.len, pdMS_TO_TICKS(5000));
                        if (err != ESP_OK) {
                            ESP_LOGE("WS", "Failed to send WebSocket binary: %s (0x%x)", esp_err_to_name(err), err);
                        }
                    } else {
                        ESP_LOGW("WS", "WebSocket not connected, cannot send binary message");
                    }
                    free(message.data);
                }
            } else {
                // Send JSON message directly using ESP-IDF API
                if (message.json && ws_client) {
                    if (esp_websocket_client_is_connected(ws_client)) {
                        char *json_str = cJSON_PrintUnformatted(message.json);
                        if (json_str) {
                            size_t json_len = strlen(json_str);
                            esp_err_t err = esp_websocket_client_send_text(ws_client, json_str, json_len, pdMS_TO_TICKS(5000));
                            if (err != ESP_OK) {
                                ESP_LOGE("WS", "Failed to send WebSocket text: %s (0x%x)", esp_err_to_name(err), err);
                            }
                            free(json_str);
                        } else {
                            ESP_LOGE("WS", "Failed to serialize JSON for sending");
                        }
                    } else {
                        ESP_LOGW("WS", "WebSocket not connected, cannot send JSON message");
                    }
                    cJSON_Delete(message.json);
                }
            }
        }
        
        // Small delay to prevent busy looping
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    
    ESP_LOGI("WS", "WebSocket message processing task stopping");
    vTaskDelete(NULL);
}