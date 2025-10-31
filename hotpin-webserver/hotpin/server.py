"""Main server for HotPin WebServer."""
import asyncio
import json
import os
import tempfile
from datetime import datetime
from typing import Optional, Dict, Any
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import Config
from .ws_manager import manager as ws_manager
from .session_manager import session_manager, SessionState, Session
from .audio_ingestor import AudioIngestor
from .stt_worker import stt_worker
from .llm_client import llm_client
from .image_handler import image_handler
from .tts_worker import tts_worker
from .tts_streamer import tts_streamer
from .storage_manager import storage_manager
from .utils import create_logger, validate_audio_chunk
from .discovery import DiscoveryService

# Create logger for this module
logger = create_logger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="HotPin WebServer",
    description="A multimodal assistant server for ESP32-CAM devices",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
audio_ingestor = AudioIngestor()

# Mount static files for test client
try:
    app.mount("/static", StaticFiles(directory="tools"), name="static")
except:
    logger.warning("Could not mount static files - tools directory may not exist")

# Global variable to hold discovery service
discovery_service = None

@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    global discovery_service
    
    # Validate configuration
    validation_errors = Config.validate()
    if validation_errors:
        for error in validation_errors:
            logger.error(f"Configuration error: {error}")
        # For now, just log errors - in production you might want to exit
    
    # Initialize and start discovery service
    discovery_service = DiscoveryService(
        port=Config.WEBSOCKET_PORT,
        path=Config.WEBSOCKET_PATH,
        token=Config.WEBSOCKET_TOKEN if Config.WEBSOCKET_TOKEN != "mysecrettoken123" else None,
        use_tls=Config.USE_TLS
    )
    
    discovery_service.start_advertising(
        mdns_name=Config.HOTPIN_NAME,
        mdns_enable=Config.MDNS_ADVERTISE,
        udp_enable=Config.UDP_BROADCAST,
        udp_port=Config.BROADCAST_PORT,
        udp_interval=Config.BROADCAST_INTERVAL_SEC,
        qr_enable=Config.PRINT_QR
    )
    
    # Start cleanup tasks
    await session_manager.start_cleanup_task()
    await storage_manager.start_cleanup_task()
    
    logger.info("HotPin WebServer started")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    global discovery_service
    
    # Stop cleanup tasks
    session_manager.stop_cleanup_task()
    storage_manager.stop_cleanup_task()
    
    # Close discovery service if it exists
    if discovery_service:
        discovery_service.stop_advertising()
    
    # Close LLM client
    await llm_client.close()
    
    logger.info("HotPin WebServer stopped")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for client connections."""
    # Get session ID from query parameters
    session_id = websocket.query_params.get("session")
    if not session_id:
        await websocket.close(code=1008, reason="Session ID required")
        return
    
    # Validate auth token
    auth_token = websocket.query_params.get("token") or websocket.headers.get("Authorization")
    if auth_token != f"Bearer {Config.WS_TOKEN}" and auth_token != Config.WS_TOKEN:
        await websocket.close(code=1008, reason="Invalid token")
        return
    
    # Connect to session manager
    if not await ws_manager.connect(websocket, session_id):
        return  # Connection already closed by manager
    
    try:
        # Get or create session
        session = session_manager.get_session(session_id)
        if not session:
            session = session_manager.create_session(session_id)
        
        # Update session state
        session.update_state(SessionState.CONNECTED)
        
        # Send ready message
        await ws_manager.send_personal_message({
            "type": "ready"
        }, websocket)
        
        # Main message loop
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # Process the message based on type
                await process_client_message(websocket, session, message)
                
            except WebSocketDisconnect:
                ws_manager.disconnect(websocket)
                if session:
                    session.update_state(SessionState.DISCONNECTED)
                break
            except json.JSONDecodeError:
                logger.error("Invalid JSON received from client")
                try:
                    await ws_manager.send_personal_message({
                        "type": "error",
                        "message": "Invalid JSON format"
                    }, websocket)
                except:
                    pass  # Client might be disconnected
                continue
            except Exception as e:
                logger.error(f"Error processing message for session {session.session_id}: {e}")
                # Try to send error to client
                try:
                    await ws_manager.send_personal_message({
                        "type": "error",
                        "message": "Server error processing message"
                    }, websocket)
                except:
                    pass  # Client might be disconnected
                continue
                
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        if session:
            session.update_state(SessionState.DISCONNECTED)

async def process_client_message(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Process a message from the client."""
    if "type" not in message:
        logger.warning(f"No 'type' field in message for session {session.session_id}")
        await ws_manager.send_personal_message({
            "type": "error",
            "message": "Message missing 'type' field"
        }, websocket)
        return
    
    msg_type = message["type"]
    
    # Log message processing for debugging
    logger.debug(f"Processing message type '{msg_type}' for session {session.session_id}")
    
    if msg_type == "hello":
        await handle_hello(websocket, session, message)
    elif msg_type == "client_on":
        await handle_client_on(websocket, session, message)
    elif msg_type == "recording_started":
        await handle_recording_started(websocket, session, message)
    elif msg_type == "audio_chunk_meta":
        # Process the audio chunk (binary frame should come next)
        await handle_audio_chunk_meta(websocket, session, message)
    elif msg_type == "recording_stopped":
        await handle_recording_stopped(websocket, session, message)
    elif msg_type == "image_captured":
        await handle_image_captured(websocket, session, message)
    elif msg_type == "ready_for_playback":
        await handle_ready_for_playback(websocket, session, message)
    elif msg_type == "playback_complete":
        await handle_playback_complete(websocket, session, message)
    elif msg_type == "ping":
        await handle_ping(websocket, session, message)
    else:
        logger.warning(f"Unknown message type: {msg_type}")
        await ws_manager.send_personal_message({
            "type": "error",
            "message": f"Unknown message type: {msg_type}"
        }, websocket)

async def handle_hello(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle hello message from client."""
    # Update session with client capabilities
    capabilities_data = message.get("capabilities", {})
    if capabilities_data:
        from .session_manager import ClientCapabilities
        session.client_capabilities = ClientCapabilities(
            psram=capabilities_data.get("psram", False),
            max_chunk_bytes=capabilities_data.get("max_chunk_bytes", Config.CHUNK_SIZE_BYTES)
        )
    
    session.log_event("hello_received", message)
    logger.info(f"Session {session.session_id} capabilities: {capabilities_data}")

async def handle_client_on(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle client_on message."""
    session.update_state(SessionState.IDLE)
    session.log_event("client_on", message)

async def handle_recording_started(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle recording started message."""
    session.update_state(SessionState.RECORDING)
    
    # Start audio ingestion session
    await audio_ingestor.start_recording_session(session)
    
    # Start STT recognition session
    stt_worker.start_recognition_session(session.session_id)
    
    # Set STT callbacks
    def partial_callback(sid, text, is_partial):
        asyncio.create_task(send_partial_transcript(sid, text))
    
    def final_callback(sid, text):
        # This would be called when recognition is complete
        pass
    
    stt_worker.set_partial_callback(session.session_id, partial_callback)
    
    session.log_event("recording_started", message)
    logger.info(f"Recording started for session {session.session_id}")

async def handle_audio_chunk_meta(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle audio chunk metadata message."""
    seq = message.get("seq")
    len_bytes = message.get("len_bytes")
    
    if seq is None or len_bytes is None:
        await ws_manager.send_personal_message({
            "type": "error",
            "message": "Missing seq or len_bytes in audio_chunk_meta"
        }, websocket)
        return
    
    # Receive the binary audio chunk
    try:
        audio_chunk = await websocket.receive_bytes()
        
        # Validate the chunk size matches the metadata
        if len(audio_chunk) != len_bytes:
            logger.warning(f"Chunk size mismatch for session {session.session_id}: expected {len_bytes}, got {len(audio_chunk)}")
            await ws_manager.send_personal_message({
                "type": "error",
                "message": f"Chunk size mismatch: expected {len_bytes}, got {len(audio_chunk)}"
            }, websocket)
            return
        
        # Validate the chunk format
        if not validate_audio_chunk(audio_chunk):
            logger.warning(f"Invalid audio chunk received for session {session.session_id}")
            await ws_manager.send_personal_message({
                "type": "error",
                "message": "Invalid audio chunk format"
            }, websocket)
            return
        
        # Ingest the chunk
        success = await audio_ingestor.ingest_chunk(session, seq, audio_chunk)
        if not success:
            logger.error(f"Failed to ingest audio chunk for session {session.session_id}")
            # The audio_ingestor already logs the specific error
            return
        
        # Process with STT (if STT is available)
        if stt_worker.available:
            stt_worker.accept_audio_chunk(session.session_id, audio_chunk)
        else:
            logger.warning(f"STT not available, skipping STT processing for session {session.session_id}")
        
        # Send acknowledgment every N chunks
        if session.audio_buffer.chunks_received % 4 == 0:  # Ack every 4 chunks
            await ws_manager.send_personal_message({
                "type": "ack",
                "ref": "chunk",
                "seq": seq
            }, websocket)
        
    except WebSocketDisconnect:
        logger.info(f"Client disconnected while receiving audio chunk for session {session.session_id}")
        ws_manager.disconnect(websocket)
        # Don't try to send error message since client is disconnected
        return
    except Exception as e:
        logger.error(f"Error receiving audio chunk for session {session.session_id}: {e}")
        try:
            await ws_manager.send_personal_message({
                "type": "error",
                "message": f"Error receiving audio chunk: {str(e)}"
            }, websocket)
        except:
            pass  # Client might be disconnected

async def handle_recording_stopped(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle recording stopped message."""
    session.update_state(SessionState.PROCESSING)
    
    # Finalize audio ingestion
    audio_file_path = await audio_ingestor.finalize_recording(session)
    if not audio_file_path:
        logger.error(f"Failed to finalize recording for session {session.session_id}")
        # Request re-record
        await request_rerecord(websocket, session, "Failed to finalize recording")
        return
    
    # Get final STT result
    transcript = stt_worker.finalize_recognition(session.session_id)
    
    # Check if transcript is valid
    if not transcript or len(transcript.strip()) == 0:
        logger.warning(f"Empty transcript for session {session.session_id}")
        # Request re-record
        await request_rerecord(websocket, session, "Empty transcript")
        return
    
    # Check transcript length and quality
    if len(transcript.strip()) < 3:  # Very short transcript
        logger.warning(f"Very short transcript for session {session.session_id}: '{transcript}'")
        await request_rerecord(websocket, session, "Transcript too short")
        return
    
    # Add transcript to conversation history
    session.add_conversation_turn("user", transcript)
    
    # Call LLM with transcript and image if available
    image_data = None
    if session.current_image_path:
        image_data = await image_handler.get_image_for_llm(session.current_image_path)
    
    # Prepare conversation history
    conversation_history = []
    for turn in session.conversation_history[-5:]:  # Use last 5 turns
        conversation_history.append({
            "role": turn["role"],
            "content": turn["content"]
        })
    
    # Get LLM response
    llm_response = None
    if image_data:
        llm_response = await llm_client.chat_with_image_and_text(
            text=transcript,
            image_data=image_data,
            conversation_history=conversation_history
        )
    else:
        llm_response = await llm_client.simple_chat(
            text=transcript,
            conversation_history=conversation_history
        )
    
    if not llm_response:
        logger.error(f"LLM call failed for session {session.session_id}")
        await ws_manager.send_personal_message({
            "type": "error",
            "code": "llm_unavailable",
            "message": "LLM API failure"
        }, websocket)
        # Add fallback response
        llm_response = "I'm having trouble thinking right now — please try again"
    
    # Add LLM response to conversation history
    session.add_conversation_turn("assistant", llm_response)
    
    # Send LLM response to client
    await ws_manager.send_personal_message({
        "type": "llm",
        "text": llm_response
    }, websocket)
    
    # Generate TTS
    tts_file_path = await tts_worker.generate_speech(llm_response, session.session_id)
    if tts_file_path:
        session.tts_file_path = tts_file_path
        session.tts_ready = True
        
        # Wait for client to be ready for playback or timeout
        # In a real implementation, you'd track this state more carefully
        await asyncio.sleep(0.1)  # Brief pause
        
        # If client hasn't signaled readiness, send download offer
        # In a full implementation, you'd track if client is ready
        if session.state == SessionState.PROCESSING:
            # Offer download as fallback
            download_url = await tts_streamer.create_download_url(tts_file_path)
            if download_url:
                await ws_manager.send_personal_message({
                    "type": "offer_download",
                    "url": download_url
                }, websocket)
    else:
        logger.error(f"TTS generation failed for session {session.session_id}")
        await ws_manager.send_personal_message({
            "type": "error",
            "message": "TTS generation failed"
        }, websocket)
    
    session.log_event("recording_stopped", message)

async def handle_image_captured(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle image captured message - client should upload via HTTP POST."""
    # This message just notifies that an image was captured
    # The actual upload happens via HTTP POST /image
    session.log_event("image_captured_notification", message)

async def handle_ready_for_playback(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle client ready for playback."""
    if session.tts_file_path and session.tts_ready:
        # Stream the TTS to the client
        async def send_callback(msg, binary=False):
            if binary:
                await websocket.send_bytes(msg)
            else:
                await ws_manager.send_personal_message(msg, websocket)
        
        success = await tts_streamer.stream_tts_to_client(
            session.tts_file_path,
            send_callback,
            session.session_id
        )
        
        if success:
            session.update_state(SessionState.PLAYING)
        else:
            logger.error(f"TTS streaming failed for session {session.session_id}")
            # Offer download as fallback
            download_url = await tts_streamer.create_download_url(session.tts_file_path)
            if download_url:
                await ws_manager.send_personal_message({
                    "type": "offer_download",
                    "url": download_url
                }, websocket)
    else:
        logger.warning(f"No TTS ready for session {session.session_id}")
        await ws_manager.send_personal_message({
            "type": "error",
            "message": "No TTS audio ready"
        }, websocket)

async def handle_playback_complete(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle playback complete message."""
    session.update_state(SessionState.IDLE)
    
    # Clean up audio files
    if session.audio_buffer.temp_file_path:
        await audio_ingestor.cleanup_recording_session(session)
    
    session.log_event("playback_complete", message)

async def handle_ping(websocket: WebSocket, session: Session, message: Dict[str, Any]):
    """Handle ping message."""
    await ws_manager.send_personal_message({
        "type": "pong"
    }, websocket)

async def send_partial_transcript(session_id: str, text: str):
    """Send a partial transcript to the client."""
    # Find the websocket for this session
    websocket = ws_manager.active_connections.get(session_id)
    if websocket:
        try:
            await ws_manager.send_personal_message({
                "type": "partial",
                "text": text,
                "stable": False
            }, websocket)
        except Exception as e:
            logger.error(f"Error sending partial transcript: {e}")

async def request_rerecord(websocket: WebSocket, session: Session, reason: str):
    """Request the client to re-record."""
    if session.can_rerecord():
        session.increment_rerecord_attempt()
        await ws_manager.send_personal_message({
            "type": "request_rerecord",
            "reason": reason
        }, websocket)
        session.update_state(SessionState.IDLE)
    else:
        # Too many re-record attempts
        await ws_manager.send_personal_message({
            "type": "request_user_intervention",
            "message": f"Too many re-recording attempts. Reason: {reason}"
        }, websocket)
        session.update_state(SessionState.STALLED)

@app.post("/image")
async def upload_image(
    session: str = Query(..., description="Session ID"),
    file: UploadFile = File(..., description="Image file to upload")
):
    """Endpoint for uploading images."""
    # Get the session
    session_obj = session_manager.get_session(session)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Read the image file
    image_data = await file.read()
    
    # Handle the image upload
    result = await image_handler.handle_image_upload(session, image_data)
    
    if result["success"]:
        # Update session with image info
        session_obj.current_image_path = result["path"]
        session_obj.current_image_metadata = {
            "filename": result["filename"],
            "format": result["format"],
            "dimensions": result["dimensions"],
            "size": result["size"]
        }
        
        # Send confirmation to client
        websocket = ws_manager.active_connections.get(session)
        if websocket:
            await ws_manager.send_personal_message({
                "type": "image_received",
                "filename": result["filename"]
            }, websocket)
        
        session_obj.log_event("image_uploaded", result)
        
        return JSONResponse(content={
            "type": "image_received",
            "filename": result["filename"],
            "path": result["path"]
        })
    else:
        session_obj.log_event("image_upload_failed", {"error": result["error"]})
        raise HTTPException(status_code=400, detail=result["error"])

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    disk_usage = storage_manager.get_disk_usage()
    active_sessions = session_manager.get_session_stats()
    
    return {
        "ok": True,
        "timestamp": datetime.utcnow().isoformat(),
        "models": ["groq-whisper", "groq-llm"],
        "uptime": "N/A",  # Would track actual uptime in a real implementation
        "disk_usage": disk_usage,
        "active_sessions": active_sessions
    }

@app.get("/state")
async def get_session_state(session: str = Query(..., description="Session ID")):
    """Get the authoritative state of a session."""
    session_obj = session_manager.get_session(session)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_obj.session_id,
        "state": session_obj.state.value,
        "client_capabilities": {
            "psram": session_obj.client_capabilities.psram if session_obj.client_capabilities else None,
            "max_chunk_bytes": session_obj.client_capabilities.max_chunk_bytes if session_obj.client_capabilities else None
        } if session_obj.client_capabilities else None,
        "audio_buffer": {
            "chunks_received": session_obj.audio_buffer.chunks_received,
            "total_bytes": session_obj.audio_buffer.total_bytes,
            "temp_file_path": session_obj.audio_buffer.temp_file_path
        },
        "rerecord_attempts": session_obj.rerecord_attempts,
        "disk_usage_bytes": session_obj.disk_usage_bytes,
        "conversation_history_count": len(session_obj.conversation_history),
        "current_image_path": session_obj.current_image_path,
        "tts_ready": session_obj.tts_ready
    }

def run_server():
    """Run the server."""
    uvicorn.run(
        "hotpin.server:app", 
        host=Config.HOST, 
        port=Config.PORT, 
        reload=False,  # Set to True for development
        log_level=Config.LOG_LEVEL.lower()
    )

if __name__ == "__main__":
    run_server()