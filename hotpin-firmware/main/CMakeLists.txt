idf_component_register(
    SRCS "main.c" 
         "state_management.c"
         "audio_handling.c" 
         "camera_handling.c"
         "network_handling.c"
         "globals.c"
         "dynamic_config.c"
    INCLUDE_DIRS "."
    REQUIRES esp_websocket_client esp_http_client esp_timer json driver nvs_flash esp_event spi_flash esp_wifi esp_psram
)