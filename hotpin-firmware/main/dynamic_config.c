/*
 * HotPin Firmware - Dynamic Configuration Management
 * 
 * This module handles dynamic configuration updates from the webserver,
 * including WebSocket URL discovery and automatic parameter synchronization.
 */

#include "main.h"
#include "esp_http_client.h"
#include "cJSON.h"

// Global configuration variables
static char dynamic_ws_url[256] = {0};
static bool dynamic_config_available = false;

/**
 * @brief HTTP event handler for configuration requests
 * 
 * @param evt HTTP event data
 * @return esp_err_t ESP_OK on success
 */
static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    switch(evt->event_id) {
        case HTTP_EVENT_ERROR:
            ESP_LOGD("HTTP", "HTTP_EVENT_ERROR");
            break;
        case HTTP_EVENT_ON_CONNECTED:
            ESP_LOGD("HTTP", "HTTP_EVENT_ON_CONNECTED");
            break;
        case HTTP_EVENT_HEADER_SENT:
            ESP_LOGD("HTTP", "HTTP_EVENT_HEADER_SENT");
            break;
        case HTTP_EVENT_ON_HEADER:
            ESP_LOGD("HTTP", "HTTP_EVENT_ON_HEADER, key=%s, value=%s", evt->header_key, evt->header_value);
            break;
        case HTTP_EVENT_ON_DATA:
            ESP_LOGD("HTTP", "HTTP_EVENT_ON_DATA, len=%d", evt->data_len);
            if (!esp_http_client_is_chunked_response(evt->client)) {
                ESP_LOGD("HTTP", "Data received: %.*s", evt->data_len, (char*)evt->data);
            }
            break;
        case HTTP_EVENT_ON_FINISH:
            ESP_LOGD("HTTP", "HTTP_EVENT_ON_FINISH");
            break;
        case HTTP_EVENT_DISCONNECTED:
            ESP_LOGD("HTTP", "HTTP_EVENT_DISCONNECTED");
            break;
        case HTTP_EVENT_REDIRECT:
            ESP_LOGD("HTTP", "HTTP_EVENT_REDIRECT");
            break;
    }
    return ESP_OK;
}

/**
 * @brief Fetch dynamic configuration from webserver
 * 
 * This function contacts the webserver to fetch the latest configuration
 * including the current WebSocket URL for this device.
 * 
 * @return true if configuration was successfully fetched, false otherwise
 */
bool fetch_dynamic_config() {
    ESP_LOGI("CONFIG", "Fetching dynamic configuration from webserver");
    
    // Get the local IP address to create a configuration URL
    esp_netif_ip_info_t ip_info;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    
    if (esp_netif_get_ip_info(netif, &ip_info) != ESP_OK) {
        ESP_LOGW("CONFIG", "Failed to get local IP for dynamic configuration");
        return false;
    }
    
    // Format the configuration URL
    char config_url[256];
    uint8_t *ip = (uint8_t*)&ip_info.ip.addr;
    snprintf(config_url, sizeof(config_url), "http://%d.%d.%d.%d:8000/config", ip[0], ip[1], ip[2], ip[3]);
    
    ESP_LOGD("CONFIG", "Configuration URL: %s", config_url);
    
    // Create HTTP client configuration
    esp_http_client_config_t config = {
        .url = config_url,
        .event_handler = http_event_handler,
        .timeout_ms = 5000,  // 5 second timeout
    };
    
    // Initialize HTTP client
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE("CONFIG", "Failed to initialize HTTP client");
        return false;
    }
    
    // Perform HTTP GET request
    esp_err_t err = esp_http_client_perform(client);
    if (err != ESP_OK) {
        ESP_LOGE("CONFIG", "HTTP GET request failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Check HTTP response code
    int status_code = esp_http_client_get_status_code(client);
    if (status_code != 200) {
        ESP_LOGW("CONFIG", "HTTP GET returned status code: %d", status_code);
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Get response length
    int content_length = esp_http_client_get_content_length(client);
    if (content_length <= 0 || content_length > sizeof(dynamic_ws_url)) {
        ESP_LOGW("CONFIG", "Invalid content length: %d", content_length);
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Read response data
    char response_buffer[sizeof(dynamic_ws_url)];
    int read_len = esp_http_client_read(client, response_buffer, sizeof(response_buffer) - 1);
    if (read_len <= 0) {
        ESP_LOGW("CONFIG", "Failed to read HTTP response");
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Null terminate the response
    response_buffer[read_len] = '\0';
    
    // Parse JSON response
    cJSON *json = cJSON_Parse(response_buffer);
    if (!json) {
        ESP_LOGW("CONFIG", "Failed to parse JSON response: %s", response_buffer);
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Extract WebSocket URL from JSON
    cJSON *ws_url_item = cJSON_GetObjectItem(json, "websocket_url");
    if (!ws_url_item || !cJSON_IsString(ws_url_item)) {
        ESP_LOGW("CONFIG", "WebSocket URL not found in configuration response");
        cJSON_Delete(json);
        esp_http_client_cleanup(client);
        return false;
    }
    
    const char *ws_url = cJSON_GetStringValue(ws_url_item);
    if (!ws_url || strlen(ws_url) == 0) {
        ESP_LOGW("CONFIG", "WebSocket URL is empty in configuration response");
        cJSON_Delete(json);
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Check if the URL already contains query parameters
    char full_ws_url[256];
    if (strchr(ws_url, '?')) {
        // URL already has query params, append with &
        snprintf(full_ws_url, sizeof(full_ws_url), "%s&session=%s&token=%s", ws_url, SESSION_ID, HOTPIN_WS_TOKEN);
    } else {
        // URL has no query params, append with ?
        snprintf(full_ws_url, sizeof(full_ws_url), "%s?session=%s&token=%s", ws_url, SESSION_ID, HOTPIN_WS_TOKEN);
    }
    
    // Update dynamic configuration
    strncpy(dynamic_ws_url, full_ws_url, sizeof(dynamic_ws_url) - 1);
    dynamic_ws_url[sizeof(dynamic_ws_url) - 1] = '\0';  // Ensure null termination
    dynamic_config_available = true;
    
    ESP_LOGI("CONFIG", "Dynamic WebSocket URL updated: %s", dynamic_ws_url);
    
    // Clean up
    cJSON_Delete(json);
    esp_http_client_cleanup(client);
    
    return true;
}

/**
 * @brief Get the current WebSocket URL
 * 
 * Returns the WebSocket URL to use, preferring dynamic configuration
 * when available, falling back to compiled configuration.
 * 
 * @return Pointer to the WebSocket URL string
 */
const char* get_current_ws_url() {
    static char fallback_ws_url[256];
    
    if (dynamic_config_available && strlen(dynamic_ws_url) > 0) {
        return dynamic_ws_url;
    }
    
    // Format the fallback URL with session and token parameters
    if (strchr(HOTPIN_WS_URL, '?')) {
        // URL already has query params, append with &
        snprintf(fallback_ws_url, sizeof(fallback_ws_url), "%s&session=%s&token=%s", HOTPIN_WS_URL, SESSION_ID, HOTPIN_WS_TOKEN);
    } else {
        // URL has no query params, append with ?
        snprintf(fallback_ws_url, sizeof(fallback_ws_url), "%s?session=%s&token=%s", HOTPIN_WS_URL, SESSION_ID, HOTPIN_WS_TOKEN);
    }
    
    return fallback_ws_url;
}

/**
 * @brief Update dynamic configuration from webserver
 * 
 * This function should be called periodically to check for configuration updates.
 * In a real implementation, this would contact the webserver's configuration API.
 */
void update_dynamic_config() {
    ESP_LOGD("CONFIG", "Checking for configuration updates");
    
    // In a real implementation, this would:
    // 1. Contact a configuration endpoint on the webserver
    // 2. Fetch the latest WebSocket URL and other settings
    // 3. Update the dynamic configuration
    // 4. Apply changes if needed
    
    // For now, we just refresh the local IP-based URL
    fetch_dynamic_config();
}

#include "network_discovery.h"

/**
 * @brief Initialize dynamic configuration management
 * 
 * Sets up the dynamic configuration system and fetches initial configuration.
 * If HTTP-based config fetch fails, attempts network discovery as fallback.
 * 
 * @return true if initialization was successful, false otherwise
 */
bool init_dynamic_config() {
    ESP_LOGI("CONFIG", "Initializing dynamic configuration management");
    
    // Try to fetch initial configuration via HTTP
    if (fetch_dynamic_config()) {
        ESP_LOGI("CONFIG", "Dynamic configuration initialized successfully via HTTP");
        return true;
    }
    
    // If HTTP fetch failed, try network discovery as fallback
    char discovered_ws_url[256];
    if (discover_server(discovered_ws_url, sizeof(discovered_ws_url))) {
        // Use the discovered URL as the dynamic WebSocket URL
        strncpy(dynamic_ws_url, discovered_ws_url, sizeof(dynamic_ws_url) - 1);
        dynamic_ws_url[sizeof(dynamic_ws_url) - 1] = '\0';  // Ensure null termination
        dynamic_config_available = true;
        
        ESP_LOGI("CONFIG", "Dynamic configuration initialized via network discovery: %s", dynamic_ws_url);
        return true;
    }
    
    ESP_LOGW("CONFIG", "Failed to fetch dynamic configuration and network discovery failed, using compiled defaults");
    return true; // Continue with defaults
}