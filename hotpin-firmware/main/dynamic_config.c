/*
 * HotPin Firmware - Dynamic Configuration Management
 * 
 * This module handles dynamic configuration updates from the webserver,
 * including WebSocket URL discovery and automatic parameter synchronization.
 */

#include "main.h"
#include "esp_http_client.h"
#include "cJSON.h"
#include "network_discovery.h"
#include <string.h>

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
 * @brief Fetch dynamic configuration from a specific server IP
 * 
 * This function contacts the webserver to fetch the latest configuration
 * including the current WebSocket URL for this device.
 * 
 * @param server_ip The IP address of the server to fetch config from
 * @return true if configuration was successfully fetched, false otherwise
 */
static bool fetch_dynamic_config_from_ip(const char *server_ip) {
    ESP_LOGI("CONFIG", "Fetching dynamic configuration from server IP: %s", server_ip);
    
    // Early exit if we're in a critical state where stack overflow is likely
    if (current_state == CLIENT_STATE_BOOTING) {
        ESP_LOGW("CONFIG", "Skipping HTTP fetch during critical boot phase to prevent stack overflow");
        return false;
    }
    
    // Format the configuration URL
    char config_url[256];
    snprintf(config_url, sizeof(config_url), "http://%s:8000/config", server_ip);
    
    ESP_LOGD("CONFIG", "Configuration URL: %s", config_url);
    
    // Create HTTP client configuration with shorter timeout
    esp_http_client_config_t config = {
        .url = config_url,
        .event_handler = http_event_handler,
        .timeout_ms = 2000,  // Shorter timeout to prevent long blocking
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
    
    // Get response length and validate it's reasonable
    int content_length = esp_http_client_get_content_length(client);
    if (content_length <= 0 || content_length > 512) {  // Limit response size to prevent stack overflow
        ESP_LOGW("CONFIG", "Invalid content length: %d", content_length);
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Read response data - use smaller buffer to reduce stack usage
    char response_buffer[512];  // Smaller buffer to reduce stack usage
    int read_len = esp_http_client_read(client, response_buffer, sizeof(response_buffer) - 1);
    if (read_len <= 0) {
        ESP_LOGW("CONFIG", "Failed to read HTTP response");
        esp_http_client_cleanup(client);
        return false;
    }
    
    // Null terminate the response
    response_buffer[read_len] = '\0';
    
    // Parse JSON response - do this carefully to avoid stack issues
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
    
    // Check if the URL already contains query parameters - use smaller buffer
    char full_ws_url[256];  // Reasonable size for URL with params
    if (strchr(ws_url, '?')) {
        // URL already has query params, append with &
        if (snprintf(full_ws_url, sizeof(full_ws_url), "%s&session=%s&token=%s", ws_url, SESSION_ID, HOTPIN_WS_TOKEN) >= sizeof(full_ws_url)) {
            ESP_LOGE("CONFIG", "Full WebSocket URL would be too long");
            cJSON_Delete(json);
            esp_http_client_cleanup(client);
            return false;
        }
    } else {
        // URL has no query params, append with ?
        if (snprintf(full_ws_url, sizeof(full_ws_url), "%s?session=%s&token=%s", ws_url, SESSION_ID, HOTPIN_WS_TOKEN) >= sizeof(full_ws_url)) {
            ESP_LOGE("CONFIG", "Full WebSocket URL would be too long");
            cJSON_Delete(json);
            esp_http_client_cleanup(client);
            return false;
        }
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
 * @brief Fetch dynamic configuration from webserver
 * 
 * This function contacts the webserver to fetch the latest configuration
 * including the current WebSocket URL for this device.
 * First tries network discovery to find the server, then fetches config.
 * 
 * @return true if configuration was successfully fetched, false otherwise
 */
bool fetch_dynamic_config() {
    ESP_LOGI("CONFIG", "Fetching dynamic configuration from webserver");
    
    // First try to discover the server using our network discovery
    char discovered_server_ip[256] = {0};
    
    // Try network discovery
    if (discover_server(discovered_server_ip, sizeof(discovered_server_ip))) {
        // Extract just the IP part from the returned WebSocket URL
        // Format is ws://IP:port/path
        char *start = strstr(discovered_server_ip, "ws://");
        if (start) {
            start += 5; // Skip "ws://"
            char *end = strchr(start, ':'); // Find the port separator
            if (end) {
                size_t ip_len = end - start;
                char server_ip[64];
                strncpy(server_ip, start, ip_len);
                server_ip[ip_len] = '\0';
                
                // Now try to fetch config from the discovered server IP
                if (fetch_dynamic_config_from_ip(server_ip)) {
                    return true;
                }
            }
        }
    }
    
    // If discovery + fetch failed, try the original approach with our own IP
    // (This is for cases where the server has different architecture)
    esp_netif_ip_info_t ip_info;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    
    if (esp_netif_get_ip_info(netif, &ip_info) == ESP_OK) {
        uint8_t *ip = (uint8_t*)&ip_info.ip.addr;
        char server_own_ip[32];
        snprintf(server_own_ip, sizeof(server_own_ip), "%d.%d.%d.%d", ip[0], ip[1], ip[2], ip[3]);
        
        if (fetch_dynamic_config_from_ip(server_own_ip)) {
            return true;
        }
    }
    
    ESP_LOGW("CONFIG", "Failed to fetch dynamic configuration from any server");
    return false;
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

/**
 * @brief Initialize dynamic configuration management
 * 
 * Sets up the dynamic configuration system and fetches initial configuration.
 * Prioritizes using the pre-configured URL from .env file with authentication.
 * Only attempts to fetch configuration from server if URL seems incomplete.
 * If that fails, attempts network discovery as fallback.
 * 
 * @return true if initialization was successful, false otherwise
 */
bool init_dynamic_config() {
    ESP_LOGI("CONFIG", "Initializing dynamic configuration management");
    
    // If the pre-configured URL is valid, use it directly with authentication parameters
    // This avoids HTTP requests during initialization which can cause stack overflow
    if (strlen(HOTPIN_WS_URL) > 10 && strstr(HOTPIN_WS_URL, "localhost") == NULL && 
        strstr(HOTPIN_WS_URL, "127.0.0.1") == NULL) {
        
        ESP_LOGI("CONFIG", "Found pre-configured URL, applying authentication parameters without server fetch");
        
        // Format the pre-configured URL with authentication parameters directly
        // This avoids HTTP requests during initialization which can cause stack overflow
        if (strchr(HOTPIN_WS_URL, '?')) {
            // URL already has query params, append with &
            if (snprintf(dynamic_ws_url, sizeof(dynamic_ws_url), "%s&session=%s&token=%s", 
                         HOTPIN_WS_URL, SESSION_ID, HOTPIN_WS_TOKEN) < sizeof(dynamic_ws_url)) {
                dynamic_config_available = true;
                ESP_LOGI("CONFIG", "Dynamic configuration initialized with pre-configured URL: %s", dynamic_ws_url);
                return true;
            }
        } else {
            // URL has no query params, append with ?
            if (snprintf(dynamic_ws_url, sizeof(dynamic_ws_url), "%s?session=%s&token=%s", 
                         HOTPIN_WS_URL, SESSION_ID, HOTPIN_WS_TOKEN) < sizeof(dynamic_ws_url)) {
                dynamic_config_available = true;
                ESP_LOGI("CONFIG", "Dynamic configuration initialized with pre-configured URL: %s", dynamic_ws_url);
                return true;
            }
        }
        
        ESP_LOGW("CONFIG", "Failed to format pre-configured URL with auth parameters");
    }
    
    // Only try to fetch configuration from server if we have a valid URL but it seems incomplete
    // This avoids unnecessary HTTP requests during initialization
    if (strlen(HOTPIN_WS_URL) > 10) {
        // Check if the URL appears to be incomplete (missing port, path, etc.)
        bool url_seems_complete = (strstr(HOTPIN_WS_URL, ":8000/") != NULL) || 
                                  (strstr(HOTPIN_WS_URL, ":8000") != NULL);
        
        if (!url_seems_complete) {
            ESP_LOGI("CONFIG", "Pre-configured URL seems incomplete, attempting to fetch config from server");
            
            // Extract the server IP from the configured URL to try fetching config from it
            char server_ip[64] = {0};
            
            // Parse the IP from the WebSocket URL: ws://IP:port/path -> extract IP
            char *start = strstr(HOTPIN_WS_URL, "ws://");
            if (start) {
                start += 5; // Skip "ws://"
                char *end = strchr(start, ':'); // Find the port separator
                if (end) {
                    size_t ip_len = end - start;
                    strncpy(server_ip, start, ip_len);
                    server_ip[ip_len] = '\0';
                    
                    ESP_LOGI("CONFIG", "Attempting to fetch config from server IP: %s", server_ip);
                    
                    // Try to fetch config from the pre-configured server IP
                    if (fetch_dynamic_config_from_ip(server_ip)) {
                        ESP_LOGI("CONFIG", "Dynamic configuration initialized successfully by fetching from server: %s", server_ip);
                        return true;
                    } else {
                        ESP_LOGW("CONFIG", "Failed to fetch config from server, will try network discovery");
                    }
                }
            }
        } else {
            ESP_LOGI("CONFIG", "Pre-configured URL appears complete, skipping server fetch to avoid stack overflow");
        }
    }
    
    // If we can't use the pre-configured URL directly and it's not incomplete, 
    // try network discovery as fallback but only if we really need to
    char discovered_ws_url[256];
    if (discover_server(discovered_ws_url, sizeof(discovered_ws_url))) {
        // Use the discovered URL as the dynamic WebSocket URL
        strncpy(dynamic_ws_url, discovered_ws_url, sizeof(dynamic_ws_url) - 1);
        dynamic_ws_url[sizeof(dynamic_ws_url) - 1] = '\0';  // Ensure null termination
        dynamic_config_available = true;
        
        ESP_LOGI("CONFIG", "Dynamic configuration initialized via network discovery: %s", dynamic_ws_url);
        return true;
    }
    
    ESP_LOGW("CONFIG", "Failed to initialize configuration from pre-configured URL, fetch, or discovery. Using defaults.");
    return true; // Continue with defaults
}