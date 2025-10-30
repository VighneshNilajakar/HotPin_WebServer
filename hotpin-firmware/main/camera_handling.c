/*
 * HotPin Firmware - Camera Capture and Image Handling
 */

#include "main.h"

#ifdef CONFIG_CAMERA_ENABLED
// Include camera header if available
#include "camera.h"
#include "esp_camera.h"
#endif

extern TaskHandle_t camera_task_handle;

#ifdef CONFIG_CAMERA_ENABLED

void camera_task(void *pvParameters) {
    camera_task_handle = xTaskGetCurrentTaskHandle();
    
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        // Wait for notification to capture image
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        
        if (current_state != CLIENT_STATE_CAMERA_CAPTURE) {
            continue; // Don't capture if not in camera capture state
        }

        ESP_LOGI("CAMERA", "Starting camera capture sequence");

        // If currently recording, stop and clean up I2S
        if (current_state == CLIENT_STATE_RECORDING) {
            set_state(CLIENT_STATE_PROCESSING);
            
            // Small delay to allow audio tasks to clean up
            vTaskDelay(pdMS_TO_TICKS(50));
        }

        // Uninstall I2S before camera init to avoid conflicts
        if (!uninstall_i2s()) {
            ESP_LOGE("CAMERA", "Failed to uninstall I2S before camera init");
        }

        // Small delay after uninstalling I2S
        vTaskDelay(pdMS_TO_TICKS(50));

#ifdef CONFIG_CAMERA_MODEL_AI_THINKER
        // Camera configuration
        camera_config_t config = {
            .pin_pwdn = PWDN_GPIO_NUM,
            .pin_reset = RESET_GPIO_NUM,
            .pin_xclk = XCLK_GPIO_NUM,
            .pin_sscb_sda = SIOD_GPIO_NUM,
            .pin_sscb_scl = SIOC_GPIO_NUM,
            .pin_d7 = Y9_GPIO_NUM,
            .pin_d6 = Y8_GPIO_NUM,
            .pin_d5 = Y7_GPIO_NUM,
            .pin_d4 = Y6_GPIO_NUM,
            .pin_d3 = Y5_GPIO_NUM,
            .pin_d2 = Y4_GPIO_NUM,
            .pin_d1 = Y3_GPIO_NUM,
            .pin_d0 = Y2_GPIO_NUM,
            .pin_vsync = VSYNC_GPIO_NUM,
            .pin_href = HREF_GPIO_NUM,
            .pin_pclk = PCLK_GPIO_NUM,

            // XCLK 20MHz or 10MHz for OV2640 double FPS (Experimental)
            .xclk_freq_hz = 20000000,
            .ledc_timer = LEDC_TIMER_0,
            .ledc_channel = LEDC_CHANNEL_0,

            .pixel_format = PIXFORMAT_JPEG, // JPEG for smaller size
            .frame_size = FRAMESIZE_VGA,    // 640x480, adjust as needed
            .jpeg_quality = 12,             // 0-63, smaller number = higher quality
            .fb_count = 1                   // Use PSRAM if available
        };

        // PSRAM enabled?
        if (psram_available) {
            config.fb_location = CAMERA_FB_IN_PSRAM;
            config.frame_size = FRAMESIZE_SVGA;  // Could use larger frame sizes with PSRAM
        } else {
            config.fb_location = CAMERA_FB_IN_DRAM;
        }

        // Initialize the camera
        esp_err_t err = esp_camera_init(&config);
        if (err != ESP_OK) {
            ESP_LOGE("CAMERA", "Camera init failed with error: %s", esp_err_to_name(err));
            
            // Send error to server
            cJSON *json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "error");
            cJSON_AddStringToObject(json, "session", SESSION_ID);
            cJSON_AddStringToObject(json, "state", "CAMERA_CAPTURE");
            cJSON_AddStringToObject(json, "error", "camera_init_failed");
            cJSON_AddStringToObject(json, "detail", esp_err_to_name(err));
            
            // ws_send_json takes ownership of the JSON object
            // It will delete the object whether it succeeds or fails
            ws_send_json(json);
            // NOTE: json object is already deleted by ws_send_json
            // Do not call cJSON_Delete(json) here to avoid double-free
            
            // Try to reinstall I2S if possible
            init_i2s();
            
            set_state(CLIENT_STATE_IDLE);
            continue;
        }

        // Capture frame
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGE("CAMERA", "Camera capture failed - no frame buffer");
            
            // Send error to server
            cJSON *json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "error");
            cJSON_AddStringToObject(json, "session", SESSION_ID);
            cJSON_AddStringToObject(json, "state", "CAMERA_CAPTURE");
            cJSON_AddStringToObject(json, "error", "camera_capture_failed");
            cJSON_AddStringToObject(json, "detail", "Failed to get frame buffer");
            
            ws_send_json(json);
            // NOTE: json object is already deleted by ws_send_json
            // Do not call cJSON_Delete(json) here to avoid double-free
            
            // Deinit camera and reinstall I2S
            esp_camera_deinit();
            init_i2s();
            
            set_state(CLIENT_STATE_IDLE);
            continue;
        }

        ESP_LOGI("CAMERA", "Image captured, size: %zu bytes", fb->len);

        // Send image_captured notification to server
        cJSON *captured_json = cJSON_CreateObject();
        cJSON_AddStringToObject(captured_json, "type", "image_captured");
        cJSON_AddStringToObject(captured_json, "session", SESSION_ID);
        cJSON_AddStringToObject(captured_json, "filename", "image.jpg");
        cJSON_AddNumberToObject(captured_json, "size", fb->len);
        
        ws_send_json(captured_json);
        // NOTE: captured_json object is already deleted by ws_send_json
        // Do not call cJSON_Delete(captured_json) here to avoid double-free

        // Upload image via HTTP POST
        bool upload_success = upload_image_to_server(fb->buf, fb->len);
        if (upload_success) {
            ESP_LOGI("CAMERA", "Image uploaded successfully");
            
            // Send success notification to server
            cJSON *success_json = cJSON_CreateObject();
            cJSON_AddStringToObject(success_json, "type", "image_received");
            cJSON_AddStringToObject(success_json, "session", SESSION_ID);
            cJSON_AddStringToObject(success_json, "filename", "image.jpg");
            
            ws_send_json(success_json);
            // NOTE: success_json object is already deleted by ws_send_json
            // Do not call cJSON_Delete(success_json) here to avoid double-free
        } else {
            ESP_LOGE("CAMERA", "Image upload failed");
        }

        // Return frame buffer and deinitialize camera
        esp_camera_fb_return(fb);
        esp_camera_deinit();

        // Small delay after camera deinit
        vTaskDelay(pdMS_TO_TICKS(50));

        // Reinstall I2S for audio
        if (!init_i2s()) {
            ESP_LOGW("CAMERA", "Failed to reinstall I2S after camera capture");
        }

        // Set state back to idle
        set_state(CLIENT_STATE_IDLE);
        
        ESP_LOGI("CAMERA", "Camera capture sequence complete");

#else
        // Camera not configured in build
        ESP_LOGE("CAMERA", "Camera support not enabled");
        
        // Send error to server
        cJSON *json = cJSON_CreateObject();
        cJSON_AddStringToObject(json, "type", "error");
        cJSON_AddStringToObject(json, "session", SESSION_ID);
        cJSON_AddStringToObject(json, "state", "CAMERA_CAPTURE");
        cJSON_AddStringToObject(json, "error", "camera_not_supported");
        cJSON_AddStringToObject(json, "detail", "Camera support not enabled in firmware");
        
        ws_send_json(json);
        // NOTE: json object is already deleted by ws_send_json
        // Do not call cJSON_Delete(json) here to avoid double-free
        
        set_state(CLIENT_STATE_IDLE);
#endif
    }

    vTaskDelete(NULL);
}

bool upload_image_to_server(uint8_t *image_data, size_t image_len) {
    char task_url[256];
    snprintf(task_url, sizeof(task_url), "%s/image?session=%s", 
             HOTPIN_WS_URL, SESSION_ID);

    esp_http_client_config_t config = {
        .url = task_url,
        .method = HTTP_METHOD_POST,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE("CAMERA", "Failed to initialize HTTP client for image upload");
        return false;
    }

    // Set headers
    esp_http_client_set_header(client, "Authorization", HOTPIN_WS_TOKEN);
    esp_http_client_set_header(client, "Content-Type", "application/octet-stream");

    // Send the image data
    esp_http_client_set_post_field(client, (char*)image_data, image_len);

    esp_err_t err = esp_http_client_perform(client);
    if (err != ESP_OK) {
        ESP_LOGE("CAMERA", "HTTP POST request failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return false;
    }

    int status_code = esp_http_client_get_status_code(client);
    ESP_LOGI("CAMERA", "Image upload response: %d", status_code);

    esp_http_client_cleanup(client);

    return status_code == 200;
}

#else  // CONFIG_CAMERA_ENABLED is not defined

// Provide empty stubs when camera is not enabled
void camera_task(void *pvParameters) {
    // Camera functionality is disabled
    ESP_LOGW("CAMERA", "Camera task started but camera is disabled");
    
    // Send error to server when camera capture is requested but not available
    while (current_state != CLIENT_STATE_SHUTDOWN) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        
        if (current_state == CLIENT_STATE_CAMERA_CAPTURE) {
            // Send error to server
            cJSON *json = cJSON_CreateObject();
            cJSON_AddStringToObject(json, "type", "error");
            cJSON_AddStringToObject(json, "session", SESSION_ID);
            cJSON_AddStringToObject(json, "state", "CAMERA_CAPTURE");
            cJSON_AddStringToObject(json, "error", "camera_not_supported");
            cJSON_AddStringToObject(json, "detail", "Camera support not enabled in firmware");
            
            ws_send_json(json);
            // NOTE: json object is already deleted by ws_send_json
            // Do not call cJSON_Delete(json) here to avoid double-free
            
            set_state(CLIENT_STATE_IDLE);
        }
    }
    
    vTaskDelete(NULL);
}

bool upload_image_to_server(uint8_t *image_data, size_t image_len) {
    ESP_LOGW("CAMERA", "Image upload called but camera is disabled");
    return false;
}

#endif  // CONFIG_CAMERA_ENABLED