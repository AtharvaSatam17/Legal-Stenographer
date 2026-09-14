from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from services.realtime.realtime_service import RealTimeTranscriptionService

app = FastAPI()

# Add CORS middleware to allow frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize your existing service
realtime_service = RealTimeTranscriptionService()

@app.on_event("startup")
async def startup_event():
    await realtime_service._test_s3_connection() 

@app.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🔗 WebSocket connection accepted")

    try:
        while True:
            message = await websocket.receive_text()
            await realtime_service.handle_websocket_message(websocket, message)

    except WebSocketDisconnect:
        print("🔌 WebSocket disconnected")

        # Cleanup all sessions attached to this websocket

        for session_id in realtime_service.session_manager.list_sessions():
            session = realtime_service.session_manager.get_session(session_id)
            if session and session.get("websocket") == websocket:
                await realtime_service._cleanup_session(session_id)


    except Exception as e:
        print(f"❌ WebSocket error: {e}")
