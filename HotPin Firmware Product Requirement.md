---

# HotPin Firmware — System Design Report (Final, detailed)

**Target MCU:** ESP32-CAM (AI-Thinker / WROVER recommended for PSRAM)
**Primary peripherals:** INMP441 (I²S mic), MAX98357A (I²S DAC), OV2640, push button (GPIO12), status LED (GPIO33)
**Audio:** PCM16 LE, mono, 16 kHz, chunked (0.5 s → 16,000 bytes)
**Comm:** WebSocket (WS/WSS) to HotPin WebServer (hosted on laptop hotspot)
**Firmware framework:** ESP-IDF + FreeRTOS

---

## 1 — High-level goals & constraints

* Keep firmware *minimal* and *robust*: server does heavy ML, firmware streams raw audio/image and plays back audio.
* Single-active-process at all times: RECORDING, PLAYING, CAMERA_CAPTURE, or SHUTDOWN. Firmware rejects attempts to start new heavy processes when one is active.
* Press-toggle recording UX: press once to start, press again to stop (server may request re-records). Double-press → camera capture. Long-press (≥1200 ms) → shutdown.
* No hardware debounce capacitors available — use software debounce.
* Preallocate chunk pool to avoid dynamic malloc/free during normal operation. Use PSRAM when available.
* Clean and deterministic resource cleanup on process switch or error.

---

## 2 — State machine (authoritative local-state reporting)

**States:**
`BOOTING` → `CONNECTED` → `IDLE` → `RECORDING` → `PROCESSING` → `PLAYING` → `IDLE`
Special: `CAMERA_CAPTURE`, `STALLED`, `SHUTDOWN`

**Transition rules (high level):**

* Only transition on local events (button) or confirmed server orchestration (server instructions for playback etc.), but firmware always enforces single-active-process rule.
* On any state transition, firmware immediately sends state/event JSON to server (see message section).
* If server requests a conflicting action, firmware replies `reject` and remains in current state.

---

## 3 — GPIO mapping & hardware rules

* **GPIO2** — INMP441 SD (I²S data in from mic). (Chosen to avoid bootstrap conflicts.)
* **GPIO14** — I²S BCLK (shared to mic & DAC).
* **GPIO15** — I²S LRCLK / WS (shared).
* **GPIO13** — I²S DIN → MAX98357A (DAC data out).
* **GPIO12** — Push button input (external 10 kΩ pulldown to GND; button to 3.3V). Must be LOW at reset.
* **GPIO33** — Status LED (internal/external). Verify polarity; invert logic if needed.

**Important:** Ensure USB 5V supply is stable (recommend 2 A). Common GND for all modules.

---

## 4 — Button behavior & FSM (final)

**Constants (recommended):**

```
DEBOUNCE_MS = 50
DOUBLE_PRESS_WINDOW_MS = 300
LONG_PRESS_MS = 1200   // long press for shutdown
```

**Behavior:**

* Single press (toggle):

  * `IDLE` -> start RECORDING: send `recording_started`, LED pattern, start capturing chunks.
  * `RECORDING` -> stop RECORDING: send `recording_stopped`, set PROCESSING, LED pattern.
* Double-press (within DOUBLE_PRESS_WINDOW_MS):

  * If `IDLE` -> execute CAMERA_CAPTURE: stop audio if running, uninstall I2S, init camera, capture & upload.
* Long-press (>= LONG_PRESS_MS):

  * Trigger `SHUTDOWN`: send `shutdown` to server, stop all tasks, disconnect Wi-Fi+WS, optionally deep-sleep.

**Debounce:** software debounce with polling (task-based) — works without capacitor.

**Rejects:** If user requests action while a heavy process runs (e.g., trying to start recording while PLAYING), firmware will blink LED and send:

```json
{"type":"reject","reason":"busy","current_state":"PLAYING"}
```

---

## 5 — I²S configuration & lifecycle

**Audio spec:** PCM16 LE, 1 channel, 16 kHz, chunk = 0.5 s = 8000 samples = 16,000 bytes.

**I²S settings (ESP-IDF style):**

* `mode = I2S_MODE_MASTER | I2S_MODE_RX` for recording; `I2S_MODE_MASTER | I2S_MODE_TX` for playback.
* `sample_rate = 16000`
* `bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT`
* `use_apll = false` (default)
* `mclk_io_num = I2S_PIN_NO_CHANGE` (disable MCLK)
* Pins: `bclk_io_num = 14`, `ws_io_num = 15`, `data_in = 2` (mic), `data_out = 13` (DAC).

**Driver lifecycle rules:**

* ALWAYS call `i2s_stop()` and `i2s_driver_uninstall()` before `esp_camera_init()` and before switching directions.
* Delay ~30–100 ms after uninstall before new init.
* Use the same i2s peripheral instance numbering consistently and avoid conflicting camera use (camera uses parallel interface that may conflict with I2S0).

---

## 6 — Chunking, pool & buffer management (memory-first)

**Chunk parameters:**

* `CHUNK_SAMPLES = 8000`
* `CHUNK_BYTES = CHUNK_SAMPLES * 2 = 16000`

**Chunk pool:** preallocated buffers to avoid runtime malloc/free. Pool count depends on PSRAM:

* If no PSRAM: `POOL_COUNT = 4` → ~64 KB pool
* If PSRAM present: `POOL_COUNT = 16` (or 32) → ~256–512 KB pool

**Allocation:** allocate buffers at startup using:

* If PSRAM available: `heap_caps_malloc(CHUNK_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA)` if DMA needed.
* Otherwise: `heap_caps_malloc(CHUNK_BYTES, MALLOC_CAP_DMA)`.

**Queues:**

* `q_free_chunks` — free buffer pointers (pool management).
* `q_capture_to_send` — audio_chunk_t pointers queued for send.
* `q_playback` — incoming TTS frames (binary pointers) queued for playback.

**Policy on pool exhaustion:** If `alloc_chunk` fails (pool empty), the firmware must stop recording, call cleanup, send `error: buffer_overflow`, and blink LED. Do NOT allocate more memory dynamically.

**Returning buffers:** sender returns buffer pointer to `q_free_chunks` after successful send/playback.

---

## 7 — Task architecture (FreeRTOS)

**Persistent tasks** (created at boot):

* `wifi_task` — manages STA connect and reconnection backoff.
* `ws_task` — maintains WebSocket, parses text frames, routes binary to playback queue, provides `ws_send_json()` and `ws_send_binary()`.
* `button_task` — polls GPIO12, implements press/debounce FSM.
* `audio_capture_task` — waits for RECORDING state; i2s read into prealloc buffer, pushes to `q_capture_to_send`.
* `audio_send_task` — dequeues from `q_capture_to_send`, sends meta JSON then binary frames via ws_task, returns buffer to free pool.
* `audio_playback_task` — receives binary TTS frames (queue), ensures I2S TX, writes to DAC, handles `tts_done`.
* `camera_task` — invoked for capture (stops audio, camera init, capture, upload, cleanup).
* `state_manager` — central state store, handles set_state(), emits state JSON to server & LED patterns.
* `cleanup_task` (optional) — periodic housekeeping (temp file cleanup if used).

**Why persistent tasks:** avoids frequent creation/deletion and helps deterministic resource cleanup. Tasks block on queues and wake when needed.

---

## 8 — WebSocket & message protocol (firmware view)

**On connect** (WS text frame):

```json
{
  "type":"client_on",
  "session":"hotpin-01",
  "capabilities":{"psram":true,"max_chunk_bytes":16000}
}
```

**During recording:**

* Before binary: text control meta:

```json
{"type":"audio_chunk_meta","session":"hotpin-01","seq":12,"len":16000}
```

* Immediately follow with binary frame: raw PCM16 buffer (exact bytes, no extra framing).

**Stop recording:**

```json
{"type":"recording_stopped","session":"hotpin-01","last_seq":n}
```

**Playback handshake & data:**

* Server sends `tts_ready` (metadata). Firmware replies `ready_for_playback`.
* Server sends `tts_chunk_meta` + binary, followed by `tts_done`.
* Firmware sends `playback_complete` at the end.

**Image upload:**

* Firmware does HTTP `POST /image` multipart with Authorization header and `session` header; then sends `image_captured` event if desired.

**Errors & rejects:**

* Firmware sends:

```json
{"type":"error","session":"hotpin-01","error":"i2s_read_timeout","state":"RECORDING","detail":"..."}
{"type":"reject","session":"hotpin-01","reason":"busy","current_state":"PLAYING"}
```

---

## 9 — Camera capture lifecycle & safety

**Sequence:**

1. If `RECORDING`: stop recording (flush queues and return buffers), uninstall I2S.
2. Delay 50 ms.
3. `esp_camera_init(&cfg)` — handle return; if fail, send `error: camera_init_failed` and try reinstalling I2S.
4. `camera_fb_t *fb = esp_camera_fb_get();` — if `NULL`, error.
5. Upload: use HTTP client to `POST /image` with multipart form data.
6. `esp_camera_fb_return(fb)` and `esp_camera_deinit()`.
7. Delay 50 ms, reinstall I2S (if needed), resume IDLE.

**Important:** always uninstall I2S cleanly before camera init to avoid interrupt conflicts (`intr_alloc`), MCLK failures, or crashes.

---

## 10 — Playback handling

* If server sends WAV header: parse and strip header to feed pure PCM to I2S. Prefer server to send pure PCM frames (easier).
* Before playback, ensure I2S TX driver is installed. If currently in RX, run safe uninstall/install transition with delay.
* Write frames with `i2s_write()`; check return & timeouts.
* On `tts_done`, wait for DMA drain, then send `playback_complete`.
* On error during playback (i2s_write fail or ws disconnect), stop playback, return buffers, send `error: playback_error`.

---

## 11 — Disconnect & reconnect strategies

**WS disconnect events:**

* Mark `STALLED` or preserve `current_state` depending on context.
* Attempt reconnection with exponential backoff: 1s → 2s → 4s → 8s → 16s → 32s → 60s (cap).
* If disconnect occurred during RECORDING:

  * Continue capturing to pool until pool empty.
  * If pool empties, stop recording, call cleanup, set `IDLE` (or `STALLED`), and record `buffer_overflow` error to transmit when reconnected.
* On reconnection, send `client_on` + last known state and optionally `last_seq_sent`. Server will instruct next steps.

**Loss-resilience policy:** server is authoritative; firmware does not attempt complex resume logic — it reports last state and server decides if re-record is required.

---

## 12 — Error detection & reporting (firmware → server)

**Common errors to detect & report:**

* `i2s_read_timeout`, `i2s_write_timeout`
* `buffer_overflow`
* `camera_init_failed`
* `camera_capture_failed`
* `playback_interrupted`
* `psram_missing` (if expected)
* `ws_connection_lost`

**Message format:**

```json
{
  "type":"error",
  "session":"hotpin-01",
  "state":"RECORDING",
  "error":"buffer_overflow",
  "detail":"free chunk pool exhausted",
  "ts":169...
}
```

**Server actions:** server will instruct with `request_rerecord`, `state_sync`, or remediation messages. Firmware acts only on explicit server instructions and user action (button).

---

## 13 — Memory budgeting & pool sizing (recommended)

**Without PSRAM:**

* `POOL_COUNT = 4` → 64 KB pool (safe, conservative)
* Use internal DMA-capable heap for buffers.

**With PSRAM:**

* `POOL_COUNT = 16` (or 32) → 256 KB — 512 KB depending on available PSRAM
* Use `heap_caps_malloc(..., MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA)` if you need DMA & PSRAM.

**Stack sizes (suggested):**

* `audio_capture_task` : 8 KB
* `audio_send_task` : 4 KB
* `audio_playback_task` : 8 KB
* `ws_task` : 6 KB
* `button_task` : 3 KB
* `camera_task` : 12 KB (camera library heavy)

**Heap target:** keep usable heap > 80 KB in no-psram environments; with PSRAM this relaxes but still maintain headroom.

---

## 14 — Observability & logging

* Log to UART: boot, PSRAM detected, Wi-Fi status, WS connect/disconnect, start/stop recording, seq numbers, camera success, playback events, errors.
* Use log levels; in production set to INFO; during development DEBUG.
* Avoid logging full audio data or secret tokens.

---

## 15 — Testing & acceptance criteria

**Unit tests:**

* ButtonFSM correctness: single/double/long press behavior.
* Chunk size integrity: I2S read fills exactly CHUNK_BYTES.
* Pool allocate/free correctness under load.

**Integration tests:**

1. E2E happy path: Press → start recording → server receives chunks → stop → server replies TTS → playback; client completes playback and returns `playback_complete`. Repeat 25 cycles without leak/crash.
2. Camera flow: double-press captures image, POST upload succeeds, server replies `image_received`.
3. Disconnect during record: ensure pool buffer usage, stop on overflow, send `buffer_overflow` on reconnect.
4. Server request re-record: server sends `request_rerecord` → client blinks and user re-records.

**Acceptance criteria:**

* No memory leak over 50 cycles.
* Chunk loss due to buffer exhaustion handled by stopping recording and reporting error (not crash).
* Camera init/uninit cycle clean (no `intr_alloc` or MCLK errors).
* Long-press shutdown reliably triggers only on deliberate press (>=1200 ms).

---

## 16 — Example pseudocode sketches (concise)

**State change helper**

```c
void set_state(client_state_t s) {
  current_state = s;
  send_json_ws({"type":"state","session":SID,"state":state_to_string(s)});
  update_led_pattern_for_state(s);
}
```

**Audio capture loop**

```c
while (recording) {
  uint8_t *buf = alloc_chunk_blocking(50 / portTICK_PERIOD_MS);
  if (!buf) {
    send_error("buffer_overflow");
    stop_recording_cleanup();
    break;
  }
  size_t read = i2s_read_bytes(I2S_NUM_0, buf, CHUNK_BYTES, portMAX_DELAY);
  if (read != CHUNK_BYTES) { // handle partial reads conservatively
    send_error("i2s_read_timeout");
    free_chunk(buf);
    stop_recording_cleanup();
    break;
  }
  audio_chunk_t pkt = { .data = buf, .len = CHUNK_BYTES, .seq = next_seq++ };
  xQueueSend(q_capture_to_send, &pkt, portMAX_DELAY);
}
```

**Audio send loop**

```c
while (true) {
  audio_chunk_t pkt;
  if (xQueueReceive(q_capture_to_send, &pkt, portMAX_DELAY) == pdTRUE) {
    ws_send_json({"type":"audio_chunk_meta","seq":pkt.seq,"len":pkt.len});
    if (!ws_send_binary(pkt.data, pkt.len)) {
       // WS failed
       send_error("ws_send_failed");
       free_chunk(pkt.data);
       // On failure strategy: attempt reconnect; if reconnect fails, report buffer overflow if needed
    } else {
       free_chunk(pkt.data);
    }
  }
}
```
---

# HotPin Client — Circuit Diagram Report (detailed)

**Target:** ESP32-CAM (AI-Thinker / WROVER with PSRAM)
**Peripherals:** OV2640 (on-module), INMP441 (I²S MEMS mic), MAX98357A (I²S DAC + amp), 8 Ω speaker, push button on GPIO12, status LED on GPIO33.
**Power source:** 5 V USB supply (recommended 2 A capability) feeding ESP32-CAM VIN (board regulator) and MAX98357A VIN (if using 5 V for speaker). Common ground required.

---

## 1 — High-level block diagram (text)

```
[5V USB] ──┬───────────────┐
          │               │
          │               └──> MAX98357A VIN (speaker amp)
          │
          └──> ESP32-CAM VIN (on-board regulator → 3.3V)
                    ├─ OV2640 (on module)
                    ├─ 3.3V → INMP441 VDD
                    ├─ GPIO14 (BCLK) → INMP441 SCK & MAX98357 BCLK
                    ├─ GPIO15 (LRCLK) → INMP441 WS & MAX98357 LRC
                    ├─ GPIO2 (or GPIO12 alt) → INMP441 SD (data in)
                    ├─ GPIO13 → MAX98357 DIN (data out)
                    ├─ GPIO12 → Button (pull-down to GND; pressed → 3.3V)
                    └─ GPIO33 → Status LED (internal/external)
```

---

## 2 — BOM (recommended parts)

* ESP32-CAM AI-Thinker (WROVER variant if PSRAM required)
* INMP441 I²S MEMS microphone module (3.3 V)
* MAX98357A I²S DAC amplifier breakout (mono)
* 8 Ω, 0.5 W (or 1 W) speaker with JST 2-pin connector
* Push button (momentary tactile)
* Resistors/caps:

  * 10 kΩ resistor (GPIO12 pull-down)
  * 330 Ω (if external LED used)
  * 0.1 μF ceramic decoupling capacitors (x2 near power pins)
  * 10 μF electrolytic (near MAX98357 VIN)
  * 100 nF ceramic on GPIO12 for debounce (optional)
* Wires, headers, optional proto PCB or small perf board
* USB 5 V supply (2 A recommended)
* Optional: JST connectors, testpoint pins

---

## 3 — Pin mapping & wiring table (explicit)

> Use this table to wire modules exactly. All grounds must be common.

| Signal / Net       |                From (Module) |              To (ESP32-CAM)             | Notes                                                        |
| ------------------ | ---------------------------: | :-------------------------------------: | ------------------------------------------------------------ |
| Power 5V           |                5V USB supply |              ESP32-CAM VIN              | Feed board VIN; confirm board regulator expects 5V           |
| Power 5V           |                5V USB supply |              MAX98357A VIN              | Recommended 5V for louder playback (check MAX board spec)    |
| 3.3V               |             ESP32 3V3 output |               INMP441 VDD               | MEMS mic is 3.3V device                                      |
| GND (common)       | 5V USB / ESP32 / peripherals |               All GND pins              | Single ground net; star ground / short returns advised       |
| I²S BCLK / SCK     |               GPIO14 (ESP32) |       INMP441 SCK ; MAX98357 BCLK       | Shared clock (ESP32 as master)                               |
| I²S LRCLK / WS     |               GPIO15 (ESP32) |        INMP441 WS ; MAX98357 LRC        | Shared LR/WS                                                 |
| I²S DATA IN (MIC)  |                   INMP441 SD | GPIO2 (preferred) or GPIO12 (alternate) | Microphone → ESP32 input; ensure not used by camera          |
| I²S DATA OUT (DAC) |                 MAX98357 DIN |              GPIO13 (ESP32)             | ESP32 → DAC data out                                         |
| Pushbutton         |  3.3V → push button → GPIO12 |                  GPIO12                 | Use external **10 kΩ pull-down** to GND; default LOW at boot |
| Status LED         |               GPIO33 (ESP32) |          LED → GND (with 330Ω)          | If using module internal LED pin; check active polarity      |
| Speaker +          |                MAX98357 OUT+ |                Speaker +                | JST 2-pin connector                                          |
| Speaker -          |                MAX98357 OUT- |                Speaker -                | JST 2-pin connector                                          |

---

## 4 — Wiring and component notes (important)

### 4.1 I²S shared clocks

* BCLK (GPIO14) and LRCLK (GPIO15) **must** be generated by the ESP32 (I²S master). Do **not** let INMP441 or MAX98357 be masters.
* Microphone SD and DAC DIN must remain **separate** lines; do not tie them together.
* In firmware, set `mclk_io_num = I2S_PIN_NO_CHANGE` (no MCLK) to avoid MCLK mux conflicts.

### 4.2 Pushbutton on GPIO12 (boot strap caution)

* GPIO12 (MTDI) is a **strapping/boot** pin on many ESP32 modules: it **must be LOW at reset/boot**.
* Use an **external 10 kΩ pull-down** from GPIO12 → GND to ensure safe boot.
* Wire button between **3.3V and GPIO12** so pressing the button forces HIGH.
* Optional RC debounce: 100 nF from GPIO12 → GND (simple hardware debounce).
* Verify boot behavior after wiring before soldering to board.

### 4.3 Speaker power & MAX98357A supply

* For audible volume, power the MAX98357A from 5 V (VIN). Many MAX98357A boards accept 3.3V but at reduced volume.
* Place a **10 μF electrolytic + 0.1 μF ceramic** decoupling near MAX VIN to smooth supply and reduce audio noise.
* MAX98357 data input logic levels are typically 3.3V tolerant. Confirm your breakout’s spec sheet.

### 4.4 Decoupling & filtering

* Place **0.1 μF ceramic** close to INMP441 and MAX98357 VIN pins.
* Use **10 μF** or **22 μF** electrolytic beside MAX98357A.
* For power noise reduction, put an optional **ferrite bead** or LC filter on speaker supply if necessary.

---

## 5 — Power & grounding recommendations

* Use a **2 A, stable 5 V USB supply**. Wi-Fi TX + speaker peaks can draw hundreds of mA.
* Keep **a single ground plane** if making a PCB; avoid long ground traces. If wiring on perf board, use a star ground (single point).
* Place decoupling capacitors as near as possible to each module’s power pins.
* Keep analog and digital grounds contiguous — avoid routing speaker ground past microphone to reduce audible noise coupling.

---

## 6 — PCB / Layout guidance (if you PCB this later)

* **Microphone location:** keep the INMP441 away from the speaker and from switching regulators; prefer a small acoustic opening in enclosure.
* **Speaker:** separate from mic physically; run speaker wires twisted and short.
* **I²S traces:** keep traces for BCLK & LRCLK short and parallel (to reduce skew).
* **High-current traces:** VIN and speaker traces should be wider to handle transient currents.
* **Ground plane:** use continuous ground plane, stitched with vias if multi-layer.
* **Test points:** expose TP for BCLK (GPIO14), LRCLK (GPIO15), MIC SD, DAC DIN, VIN, 3.3V, GND, GPIO12 (button), GPIO33 (LED).
* **Boot strap pins:** label and expose pins used for boot strapping (GPIO0, GPIO2, GPIO12, GPIO15) for debugging.

---

## 7 — Test points & debug header

Add a 2×5 or 1×6 header for:

* UART0 TX/RX (U0TXD/U0RXD) for serial monitor (use TX/RX pins on board)
* 5V, 3.3V, GND
* GPIO14 (BCLK), GPIO15 (LRCLK), GPIO2 (MIC SD), GPIO13 (DAC DIN)
* GPIO12 (BUTTON) and GPIO33 (LED) test points

This makes bench debugging and oscilloscope probing much easier.

---

## 8 — Assembly & test procedure (step-by-step)

1. **Power only ESP32-CAM** — verify boot via serial at 115200. Check PSRAM message.
2. **Wire INMP441 (power & ground & I²S signals)** — leave MAX98357 unpowered initially. Verify BCLK & LRCLK toggling when firmware starts I²S (use scope) and that no boot issues occur.
3. **Connect MAX98357 VIN only after verifying ESP32 power** — verify no audible pops; run a known test tone or sample PCM stream from ESP32 to MAX; confirm speaker output.
4. **Wire button with 10 kΩ pull-down** — verify GPIO12 reads LOW at reset and goes HIGH when pressed; ensure module boots successfully with button unpressed.
5. **Connect LED to GPIO33** — test LED blink patterns from firmware.
6. **Full system test**: long-press → stream audio chunks to server; double-press → take photo; confirm beep after image ack; confirm playback audio plays.

---

## 9 — Common failure modes & troubleshooting

* **Boot fail after wiring button**

  * Symptom: infinite boot loop or no serial output after button wiring.
  * Cause: GPIO12 HIGH at reset (bad wiring or missing pull-down).
  * Fix: add/verify 10 kΩ pull-down between GPIO12 and GND; re-test.

* **I²S errors in serial logs**

  * Symptom: `i2s_check_set_mclk: mclk configure failed` or `intr_alloc` errors.
  * Cause: trying to enable MCLK or camera/I²S conflict.
  * Fix: set `mclk_io_num = I2S_PIN_NO_CHANGE` in firmware; uninstall I²S before camera init; consider using I2S1 for audio if conflicts persist.

* **No mic data**

  * Symptom: Vosk receives silence or garbage.
  * Cause: incorrect SD pin, wrong sample rate, or miswired clocks.
  * Fix: check connections for SCK/WS/SD; confirm BCLK & LRCLK present with scope; confirm sample rate set to 16 kHz.

* **Speaker noise / distortion**

  * Symptom: buzz or distortion at volume.
  * Cause: poor decoupling, inadequate power supply, long speaker wires, ground loops.
  * Fix: add 10 μF + 0.1 μF near MAX VIN, improve ground layout, shorten wires.

---

## 10 — Optional improvements & variants

* **Use I2S1 for audio**: avoids camera/I2S0 conflicts but requires careful pin remapping and possibly different hardware pins; useful if you need to avoid dynamic uninstall/reinit cycles.
* **Use 3.3 V for MAX98357 VIN** if space/power small and you can accept lower volume.
* **Add small amplifier board** (e.g., PAM8302) if higher volume needed (but PAM requires analog input or different approach).

---

## 11 — Appendix — quick wiring summary (one-page)

* ESP32 3V3 → INMP441 VDD
* ESP32 GND → INMP441 GND ; MAX98357 GND ; Speaker -
* ESP32 GPIO14 → INMP441 SCK ; MAX98357 BCLK
* ESP32 GPIO15 → INMP441 WS ; MAX98357 LRC
* ESP32 GPIO2 (or 12) → INMP441 SD
* ESP32 GPIO13 → MAX98357 DIN
* 5V USB → MAX98357 VIN ; ESP32 VIN
* Speaker + → MAX98357 OUT+ ; Speaker - → OUT-
* 10 kΩ pull-down between GPIO12 and GND; button between GPIO12 and 3.3V
* LED (GPIO33) → LED → 330Ω → GND

---
