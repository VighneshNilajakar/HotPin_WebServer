/*
 * HotPin Firmware - Network Discovery Implementation
 * Provides functions to discover and locate the HotPin WebServer
 */

#include "main.h"
#include "network_discovery.h"
#include "esp_http_client.h"
#include "esp_netif.h"
#include <string.h>
#include <stdio.h>

// Common local network IP ranges to scan
static const char* common_local_ips[] = {
    "192.168.0.100",    // Common router range
    "192.168.1.100",    // Common router range
    "192.168.1.150",    // Common router range
    "10.0.0.100",       // Alternative range
    "10.143.111.100",   // Close to the original hardcoded IP
    "10.143.111.1",     // Gateway IP
    "127.0.0.1",        // Localhost (for testing)
    NULL
};

/**
 * @brief HTTP event handler for discovery requests
 */
static esp_err_t discovery_http_event_handler(esp_http_client_event_t *evt)
{
    return ESP_OK; // Simple handler, not doing anything special
}

/**
 * @brief Check if a server is responding at a given IP address
 * 
 * @param ip The IP address to check (e.g., "192.168.1.100")
 * @return true if server responds to health check, false otherwise
 */
bool ping_server_at_ip(const char *ip)
{
    char health_url[256];
    snprintf(health_url, sizeof(health_url), "http://%s:8000/health", ip);

    esp_http_client_config_t config = {
        .url = health_url,
        .event_handler = discovery_http_event_handler,
        .timeout_ms = 3000,  // 3 second timeout for discovery
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return false;
    }

    esp_err_t err = esp_http_client_perform(client);
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }

    int status_code = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    // Check if this is a HotPin server by looking at the response
    // 200 - server running and accessible
    // 401/403 - server running but requires auth (still valid for HotPin)
    // We need to distinguish from other services running on port 8000
    return (status_code == 200 || status_code == 401 || status_code == 403);
}

/**
 * @brief Check if the server at given IP is specifically a HotPin server
 * 
 * @param ip The IP address to check
 * @return true if it's a HotPin server, false otherwise
 */
bool is_hotpin_server_at_ip(const char *ip)
{
    char health_url[256];
    snprintf(health_url, sizeof(health_url), "http://%s:8000/health", ip);

    esp_http_client_config_t config = {
        .url = health_url,
        .event_handler = discovery_http_event_handler,
        .timeout_ms = 3000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return false;
    }

    esp_err_t err = esp_http_client_perform(client);
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }

    int status_code = esp_http_client_get_status_code(client);
    
    // Read the response body to check for HotPin-specific response
    if (status_code == 200) {
        // Try to read response body to confirm it's a HotPin server
        char response_buffer[512];
        int content_length = esp_http_client_get_content_length(client);
        
        if (content_length > 0 && content_length < sizeof(response_buffer) - 1) {
            int read_len = esp_http_client_read(client, response_buffer, sizeof(response_buffer) - 1);
            if (read_len > 0) {
                response_buffer[read_len] = '\0';
                
                // Check if response contains HotPin-specific identifiers
                if (strstr(response_buffer, "HotPin") || 
                    strstr(response_buffer, "hotpin") || 
                    strstr(response_buffer, "models") || 
                    strstr(response_buffer, "groq")) {
                    esp_http_client_cleanup(client);
                    return true;
                }
            }
        }
    } else if (status_code == 401 || status_code == 403) {
        // Even if unauthorized, check if it's a HotPin server by headers
        esp_http_client_cleanup(client);
        return true; // Assume it's a HotPin server if it responds to auth-protected endpoints
    }

    esp_http_client_cleanup(client);
    return false;
}

/**
 * @brief Discover the HotPin WebServer on the local network
 * 
 * This function attempts to locate the HotPin WebServer using multiple methods:
 * 1. Scanning common local IPs
 * 2. Using the local network gateway
 * 
 * @param[out] ws_url Output buffer to store the WebSocket URL (should be at least 256 chars)
 * @param[in] buffer_size Size of the output buffer
 * @return true if server was discovered and URL was set, false otherwise
 */
bool discover_server(char *ws_url, size_t buffer_size)
{
    ESP_LOGI("DISCOVERY", "Starting server discovery...");
    
    // Check if we can get our own IP and use the gateway as a hint
    esp_netif_ip_info_t ip_info;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    
    if (esp_netif_get_ip_info(netif, &ip_info) == ESP_OK) {
        // Try changing the last octet to scan IPs in the same subnet
        uint8_t *ip = (uint8_t*)&ip_info.ip.addr;
        for (int i = 1; i <= 254; i++) {  // Scan all IPs in the subnet (except broadcast)
            if (i == ip[3]) continue;  // Skip our own IP
            
            char server_ip[16];
            snprintf(server_ip, sizeof(server_ip), "%d.%d.%d.%d", ip[0], ip[1], ip[2], i);
            
            ESP_LOGD("DISCOVERY", "Scanning IP: %s", server_ip);
            if (is_hotpin_server_at_ip(server_ip)) {
                snprintf(ws_url, buffer_size, "ws://%s:8000/ws", server_ip);
                ESP_LOGI("DISCOVERY", "HotPin server found: %s", ws_url);
                return true;
            }
        }
        
        // If subnet scan didn't work, try the gateway as well
        char gateway_ip[16];
        uint8_t *gw = (uint8_t*)&ip_info.gw.addr;
        snprintf(gateway_ip, sizeof(gateway_ip), "%d.%d.%d.%d", gw[0], gw[1], gw[2], gw[3]);
        
        if (is_hotpin_server_at_ip(gateway_ip)) {
            snprintf(ws_url, buffer_size, "ws://%s:8000/ws", gateway_ip);
            ESP_LOGI("DISCOVERY", "HotPin server found at gateway: %s", ws_url);
            return true;
        }
    }
    
    // Try common local IPs if the above didn't work
    for (int i = 0; common_local_ips[i] != NULL; i++) {
        ESP_LOGD("DISCOVERY", "Trying common IP: %s", common_local_ips[i]);
        if (is_hotpin_server_at_ip(common_local_ips[i])) {
            snprintf(ws_url, buffer_size, "ws://%s:8000/ws", common_local_ips[i]);
            ESP_LOGI("DISCOVERY", "HotPin server found: %s", ws_url);
            return true;
        }
    }
    
    ESP_LOGW("DISCOVERY", "Server discovery failed - no HotPin server detected");
    return false;
}