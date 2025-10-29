/*
 * HotPin Firmware - Network Discovery Header
 * Provides functions to discover and locate the HotPin WebServer
 */

#ifndef NETWORK_DISCOVERY_H
#define NETWORK_DISCOVERY_H

#include <stdbool.h>

/**
 * @brief Discover the HotPin WebServer on the local network
 * 
 * This function attempts to locate the HotPin WebServer using multiple methods:
 * 1. mDNS discovery (if available)
 * 2. Simple HTTP requests to common local IPs
 * 3. Using dynamic configuration endpoint
 * 
 * @param[out] ws_url Output buffer to store the WebSocket URL (should be at least 256 chars)
 * @param[in] buffer_size Size of the output buffer
 * @return true if server was discovered and URL was set, false otherwise
 */
bool discover_server(char *ws_url, size_t buffer_size);

/**
 * @brief Check if a server is responding at a given IP address
 * 
 * @param ip The IP address to check (e.g., "192.168.1.100")
 * @return true if server responds to health check, false otherwise
 */
bool ping_server_at_ip(const char *ip);

#endif // NETWORK_DISCOVERY_H