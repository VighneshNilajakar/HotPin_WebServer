# HotPin WebServer — Product Requirements Document (Final, detailed)

**Version:** 2.0
**Target runtime:** Linux laptop (prototype), Python 3.10+ (FastAPI + Uvicorn/uvloop)
**Primary client:** HotPin (ESP32-CAM) — extremely resource constrained
**LLM & Vision:** Groq Cloud `meta-llama/llama-4-maverick-17b-128e-instruct` (multimodal)
**STT:** Vosk `vosk-model-small-en-in-0.4` (Indian English)
**TTS (prototype):** pyttsx3 (local), WAV PCM16@16k

---

## 1 — Mission (one line)

Host an authoritative, forgiving, low-latency multimodal assistant: accept chunked audio + images, perform STT → multimodal LLM reasoning → TTS, and reliably stream results back while “spoon-feeding” the low-memory client (server handles recovery, buffering, and re-record requests).

---

## 2 — Design principles & constraints

* **Client is authoritative about *local* state** (it reports what it’s doing), but **server is authoritative for orchestration** (server decides recovery, playback, and re-record). Client firmware stays tiny (report events + execute single commands).
* **Single active device** by default (simpler resource model). Multi-client later as extension.
* **No retransmit burden on client** — server will request re-record instead of asking for resends.
* **Streaming-first, disk-backed** for long recordings: use memory ring buffers (PSRAM if available) + temp file fallback.
* **Chunk defaults:** 0.5s (8000 samples @ 16 kHz ≈ 16 KB). Accept variable chunk sizes.
* **Audio spec:** PCM16 LE, mono, 16 kHz.
* **Security:** `.env` config, token auth for WS & HTTP. `wss/https` recommended in production.

---

## 3 — Core capabilities (what server must do)

1. **Auth & Accept connection**: WS handshake with token; single session (configurable).
2. **Chunked audio ingestion & ack**: receive binary PCM chunks with seq metadata, append to buffer/file, ack per N chunks.
3. **Streaming STT**: run Vosk streaming for partial + final transcripts; publish partials to client.
4. **Image ingestion**: accept `POST /image` multipart, validate, store as current image context for LLM.
5. **Multimodal LLM calls**: build prompt (system + image context + convo history + transcript) → call Groq Cloud multimodal model.
6. **TTS generation & chunked streaming**: create WAV (PCM16@16k) via pyttsx3 or alternative; stream binary chunks to client with control frames.
7. **Authoritative session & state management**: log client-declared states and drive server actions (e.g., `request_rerecord`, `prepare_playback`, `offer_download`).
8. **Failure handling**: automatically request re-record on empty/noisy/too-short input; implement retry limits; fallback to hosted download if client can't stream.
9. **Resource safety**: per-session disk caps, PSRAM-aware buffers, clean temp files.
10. **Observability & test harness**: structured logs, health endpoint, sample test client and automation.

---

## 4 — Message protocol & schema (developer-ready)

### 4.1 WebSocket endpoint

`ws://<host>:<port>/ws?session=<id>` (use `wss://` in prod)

### 4.2 Client → Server (text control)

* `hello`: `{type: "hello", session, device, capabilities}`
* `client_on`: `{type: "client_on"}` — client booted & ready
* `recording_started`: `{type:"recording_started", ts}`
* `audio_chunk_meta`: `{type:"audio_chunk_meta", seq, len_bytes}` (then binary frame with raw PCM)
* `recording_stopped`: `{type:"recording_stopped"}`
* `image_captured`: `{type:"image_captured", filename, size}` (then upload image over HTTP)
* `ready_for_playback`: `{type:"ready_for_playback"}`
* `playback_complete`: `{type:"playback_complete"}`
* `ping`: `{type:"ping"}`

### 4.3 Server → Client (text control)

* `ready`: `{type:"ready"}`
* `ack`: `{type:"ack", ref:"chunk"|..., seq}`
* `partial`: `{type:"partial", text}`
* `transcript`: `{type:"transcript", text, final:true}`
* `llm`: `{type:"llm", text}`
* `tts_ready`: `{type:"tts_ready", duration_ms, sampleRate:16000, format:"wav"}`
* `tts_chunk_meta`: `{type:"tts_chunk_meta", seq, len_bytes}` (then binary WAV frame)
* `tts_done`: `{type:"tts_done"}`
* `image_received`: `{type:"image_received", filename}`
* `request_rerecord`: `{type:"request_rerecord", reason}`
* `offer_download`: `{type:"offer_download", url}`
* `state_sync`: `{type:"state_sync", server_state, message}`
* `request_user_intervention`: `{type:"request_user_intervention", message}`

### 4.4 HTTP endpoints

* `POST /image` — multipart; headers: `Authorization`, `Session`. Returns `{"type":"image_received",...}`.
* `GET /health` — returns `{"ok":true, models:[...], uptime:...}`.
* `GET /state?session=...` — returns server’s authoritative last-known session state.

---

## 5 — Session & state machine (server-side authoritative view)

**Client reports local events**; server stores them as authoritative *inputs* and performs orchestration.

**States:**

* `disconnected`, `connected`, `idle`, `recording`, `processing`, `playing`, `camera_uploading`, `stalled`, `shutdown`.

**Transition rules (high-level):**

* Client `recording_started` → server stores `recording` and begins buffering.
* Client streams `audio_chunk_meta` + PCM → server appends and sends `ack`.
* Client `recording_stopped` → server finalizes stream, runs final STT, moves to `processing`.
* After STT → server calls LLM (includes image if present) → on success server queues TTS and updates state.
* Server sends `tts_ready`, waits for client `ready_for_playback` or falls back to `offer_download`.
* On `playback_complete` → server goes `idle`.

**Server policies:**

* If STT results empty/low-confidence/too-short → send `request_rerecord` (reason included). Client re-records on user action.
* On disconnect during recording → server marks `stalled` and can request re-record on reconnect (no retransmit).

---

## 6 — Detailed component architecture & responsibilities

### 6.1 WS Manager (FastAPI/Starlette)

* Authenticates via token header in WS handshake.
* Single-session enforcement (configurable).
* Routes control frames & binary frames to Session Manager.

### 6.2 Session Manager

* Stores per-session:

  * Event log (client-reported events).
  * Buffer pointers, temp file path.
  * Conversation history (prune older turns).
  * Image metadata & path.
  * Retries counter for re-record requests.
* Provides `/state`, `state_sync` messages.

### 6.3 Audio Ingestor

* Receives `audio_chunk_meta` + binary frames.
* Writes to:

  * Ring buffer for STT streaming (use memory or PSRAM-backed if available).
  * Append-only temp file on disk for final STT.
* Emits periodic `ack` frames (e.g., every 4 chunks).
* Enforces per-session memory/disk quotas.

### 6.4 STT Worker (Vosk)

* Run in a separate process (recommended) to avoid blocking event loop.
* Accepts streaming PCM chunks.
* Emits:

  * `partial` messages as available.
  * `transcript` on EOS.
* Use a Worker Pool or dedicated process; communicate via asyncio queues or IPC.

### 6.5 LLM Multimodal Client (Groq)

* Build multimodal payload:

  * Send image bytes (or reference) + text prompt.
  * System instruction + image context + conversation + final transcript.
* Implement retry/backoff (3 attempts), timeout (60s default).
* Sanitize/limit prompt tokens (prune history).

### 6.6 TTS Worker (pyttsx3 or alternative)

* Generate WAV PCM16@16k as file (worker process).
* Estimate duration and set `tts_ready`.
* Optionally support streaming while generating if engine allows.

### 6.7 TTS Streamer

* Read WAV in chunks (16 KB recommended), send `tts_chunk_meta` then binary frame.
* After last chunk, send `tts_done`.

### 6.8 Image Handler

* Validate image type/size; store thumbnail.
* Optionally pre-run small vision model or rely on Groq to use image in the multimodal call.
* Replace image context on new upload.

### 6.9 Storage & Resource Manager

* Temp directory configurable via `.env` (`TEMP_DIR`).
* Per-session disk cap (`MAX_SESSION_DISK_MB`).
* Clean up after session end or `shutdown`.

### 6.10 Observability

* Structured JSON logs: events, durations (stt/llm/tts), errors.
* Metrics for latencies and resource usage.
* Health endpoint.

---

## 7 — Error handling & server-led recovery (policy details)

### 7.1 Server-led re-record (primary recovery pattern)

* Triggers:

  * Vosk final transcript empty or below confidence threshold.
  * Audio length < `MIN_RECORD_DURATION` (default 0.5s).
  * Loud clipping, extreme noise, large silent gaps.
  * Disconnect during recording (incomplete).
* Action: server sends `request_rerecord` with `reason`.
* Client reaction: simple UX (beep/LED) and wait for user to re-press and re-record. No retransmit.

**Retry limit:** default 2 re-record requests per interaction; after that send `request_user_intervention`.

### 7.2 Playback fallback

* If client fails to respond with `ready_for_playback` within `PLAYBACK_READY_TIMEOUT` (default 5s), server sends `offer_download` URL for client to fetch.

### 7.3 Timeouts & stalls

* Chunk arrival timeout (during recording): 5s → mark `stalled` and request re-record.
* Session idle cleanup: after `IDLE_GRACE` (default 30s) free temp files.

### 7.4 LLM & external failures

* Groq call timed out/fails → log & send `error` to client; optionally send `llm` fallback text: “I’m having trouble — please try again.”

---

## 8 — Performance & sizing defaults

* Chunk default: 0.5s (~16 KB).
* Ring buffer: 64 KB (no PSRAM) / 256 KB (with PSRAM).
* Temp file per-session cap: `MAX_SESSION_DISK_MB` (default 100).
* Vosk partial latency target: partials <1s, final transcript <2s for short utterances.
* Groq latency: depends — aim to keep LLM prompt size small for speed; default timeout 60s.
* TTS latency: target <5s for replies <5s; else stream.

---

## 9 — Security & config (`.env` usage)

### Required `.env` keys (example)

```bash
HOST=0.0.0.0
PORT=8000
WS_TOKEN=mysecrettoken123
MODEL_PATH_VOSK=/path/to/vosk-model-small-en-in-0.4
GROQ_API_KEY=sk-xxxx
TEMP_DIR=/tmp/hotpin
LOG_LEVEL=INFO
MAX_SESSION_DISK_MB=100
CHUNK_SIZE_BYTES=16000
MIN_RECORD_DURATION_SEC=0.5
MAX_RERECORD_ATTEMPTS=2
PLAYBACK_READY_TIMEOUT_SEC=5
```

**Implementation notes**

* Use `python-dotenv` to load `.env` at startup.
* Provide a `config.py` that reads env vars with safe defaults.
* Do **not** commit `.env` to repo; include `.env.example` in repo.

---

## 10 — Testing, QA & acceptance criteria

### Tests to implement

* **Unit**: STT worker decode sample PCM files; TTS produce WAV of expected format.
* **Integration**:

  1. Happy path: connect, stream 2s audio in 0.5s chunks, get `transcript`, LLM response, TTS back, client plays.
  2. Re-record path: send silent audio → server sends `request_rerecord`.
  3. Image path: upload image → server includes image in LLM prompt and response references image context.
  4. Playback fallback: server offers download when client doesn’t `ready_for_playback`.
  5. Disconnect during recording → server marks `stalled` and recovers on reconnect.
* **Stress**: 50 cycles of record→process→playback without memory growth or crash.

### Acceptance criteria

* No crashes during 50 cycles (record→process→playback).
* STT partials <1s latency; final transcript <2s for short utterances.
* Server reliably requests re-record on empty/noisy audio.
* TTS streams successfully and client plays audio or accepts download.
* Observability: logs show STT/LLM/TTS durations, errors are graceful.

---

## 11 — Deployment & runbook (quickstart)

1. Prepare environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env && edit .env
   ```
2. Start server:

   ```bash
   uvicorn hotpin.server:app --host $HOST --port $PORT --loop uvloop
   ```
3. Test with JS test client or Android test device: connect with `WS_TOKEN`, stream PCM chunks.
4. Monitor `/health` and logs.

---

## 12 — Milestones & deliverables (implementation plan)

**Milestone 1 — Transport & STT**

* Implement WS Manager, Session Manager, Audio Ingestor, Vosk integration, partial & final transcripts.

**Milestone 2 — LLM & Image support**

* Groq multimodal integration, `POST /image` handling, image context management.

**Milestone 3 — TTS & streaming**

* Integrate pyttsx3 worker, TTS generation, chunked streaming with `tts_ready`/`tts_done`.

**Milestone 4 — Robustness & policies**

* Implement server-led re-record, retries, quotas, state sync endpoint, temp cleanup.

**Milestone 5 — Tests & docs**

* Integration tests, example client, README, `.env.example`, runbook.

**Deliverables**

* Working repo branch with tests, OpenAPI for HTTP endpoints, WS message schemas, runbook, sample test client.

---

## 13 — Extra notes (firmware integration reminders)

* **Match formats exactly**: PCM16@16k, chunk size ~0.5s, seq numbers occasionally to detect severe mismatches (server will not ask for retransmit; it'll request re-record).
* **Client must implement only a few actions**: report events, send chunks, upload image, blink/play beep on `request_rerecord`, respond `ready_for_playback` and `playback_complete`.
* **Server handles all heavy logic**: Vosk, Groq, TTS, buffering, retries, timeouts.

---