/*
 * HotPin Firmware - Dynamic Configuration Management Header
 */

#ifndef DYNAMIC_CONFIG_H
#define DYNAMIC_CONFIG_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Fetch dynamic configuration from webserver
 * 
 * @return true if configuration was successfully fetched, false otherwise
 */
bool fetch_dynamic_config();

/**
 * @brief Get the current WebSocket URL
 * 
 * @return Pointer to the WebSocket URL string
 */
const char* get_current_ws_url();

/**
 * @brief Update dynamic configuration from webserver
 */
void update_dynamic_config();

/**
 * @brief Initialize dynamic configuration management
 * 
 * @return true if initialization was successful, false otherwise
 */
bool init_dynamic_config();

#ifdef __cplusplus
}
#endif

#endif /* DYNAMIC_CONFIG_H */