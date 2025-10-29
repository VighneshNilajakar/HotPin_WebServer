"""Python WebSocket test client for HotPin WebServer."""
import asyncio
import json
import websockets
import uuid
from typing import Optional

class HotPinTestClient:
    """A test client for the HotPin WebServer."""
    
    def __init__(self, server_url: str, token: str, session_id: Optional[str] = None):
        self.server_url = server_url
        self.token = token
        self.session_id = session_id or str(uuid.uuid4())
        self.websocket = None
        self.connected = False
        self.seq_number = 0
        
    async def connect(self):
        """Connect to the WebSocket server."""
        try:
            # Construct URL with session and token
            url = f"{self.server_url}?session={self.session_id}&token={self.token}"
            
            self.websocket = await websockets.connect(url)
            self.connected = True
            print(f"Connected to {url}")
            
            # Listen for messages in the background
            asyncio.create_task(self._listen_for_messages())
            
            # Send hello message
            await self.send_hello()
            
        except Exception as e:
            print(f"Connection failed: {e}")
    
    async def _listen_for_messages(self):
        """Listen for messages from the server."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    print(f"Received: {json.dumps(data, indent=2)}")
                    
                    # Handle special server responses
                    if data.get("type") == "request_rerecord":
                        print(f"Server requested re-record: {data.get('reason')}")
                    
                    elif data.get("type") == "llm":
                        print(f"LLM Response: {data.get('text')}")
                        
                except json.JSONDecodeError:
                    print(f"Received non-JSON message: {message}")
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
            self.connected = False
    
    async def send_hello(self):
        """Send hello message to server."""
        if not self.connected:
            print("Not connected")
            return
            
        hello_msg = {
            "type": "hello",
            "session": self.session_id,
            "device": "python_test_client",
            "capabilities": {
                "psram": False,
                "max_chunk_bytes": 16000
            }
        }
        await self.websocket.send(json.dumps(hello_msg))
        print(f"Sent: {json.dumps(hello_msg)}")
    
    async def send_client_on(self):
        """Send client_on message."""
        if not self.connected:
            print("Not connected")
            return
            
        msg = {"type": "client_on"}
        await self.websocket.send(json.dumps(msg))
        print(f"Sent: {json.dumps(msg)}")
    
    async def start_recording(self):
        """Simulate starting recording."""
        if not self.connected:
            print("Not connected")
            return
            
        msg = {"type": "recording_started", "ts": asyncio.get_event_loop().time()}
        await self.websocket.send(json.dumps(msg))
        print(f"Sent: {json.dumps(msg)}")
    
    async def send_audio_chunk(self):
        """Send a dummy audio chunk."""
        if not self.connected:
            print("Not connected")
            return
            
        # Send chunk metadata
        chunk_meta = {
            "type": "audio_chunk_meta",
            "seq": self.seq_number,
            "len_bytes": 160  # Dummy size
        }
        await self.websocket.send(json.dumps(chunk_meta))
        print(f"Sent: {json.dumps(chunk_meta)}")
        
        # Send dummy binary audio data (160 bytes of zeros)
        dummy_audio = b"\x00" * 160
        await self.websocket.send(dummy_audio)
        print(f"Sent audio chunk {self.seq_number} ({len(dummy_audio)} bytes)")
        self.seq_number += 1
    
    async def stop_recording(self):
        """Simulate stopping recording."""
        if not self.connected:
            print("Not connected")
            return
            
        msg = {"type": "recording_stopped"}
        await self.websocket.send(json.dumps(msg))
        print(f"Sent: {json.dumps(msg)}")
    
    async def send_ready_for_playback(self):
        """Indicate ready for playback."""
        if not self.connected:
            print("Not connected")
            return
            
        msg = {"type": "ready_for_playback"}
        await self.websocket.send(json.dumps(msg))
        print(f"Sent: {json.dumps(msg)}")
    
    async def send_playback_complete(self):
        """Indicate playback is complete."""
        if not self.connected:
            print("Not connected")
            return
            
        msg = {"type": "playback_complete"}
        await self.websocket.send(json.dumps(msg))
        print(f"Sent: {json.dumps(msg)}")
    
    async def disconnect(self):
        """Disconnect from the server."""
        if self.websocket:
            await self.websocket.close()
        self.connected = False
        print("Disconnected from server")
    
    async def interactive_test(self):
        """Run an interactive test session."""
        print("Interactive HotPin Test Client")
        print("Commands:")
        print("  1 - Send hello")
        print("  2 - Send client_on")
        print("  3 - Start recording")
        print("  4 - Send audio chunk")
        print("  5 - Stop recording")
        print("  6 - Ready for playback")
        print("  7 - Playback complete")
        print("  q - Quit")
        print()
        
        await self.connect()
        
        while self.connected:
            try:
                cmd = input("Enter command: ").strip().lower()
                
                if cmd == '1':
                    await self.send_hello()
                elif cmd == '2':
                    await self.send_client_on()
                elif cmd == '3':
                    await self.start_recording()
                elif cmd == '4':
                    await self.send_audio_chunk()
                elif cmd == '5':
                    await self.stop_recording()
                elif cmd == '6':
                    await self.send_ready_for_playback()
                elif cmd == '7':
                    await self.send_playback_complete()
                elif cmd == 'q':
                    break
                else:
                    print("Unknown command")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
        
        await self.disconnect()

async def main():
    """Main function to run the test client."""
    # Default values - in real usage these would come from config
    server_url = "ws://localhost:8000/ws"
    token = "mysecrettoken123"
    
    client = HotPinTestClient(server_url, token)
    await client.interactive_test()

if __name__ == "__main__":
    asyncio.run(main())