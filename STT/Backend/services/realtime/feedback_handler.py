# services/realtime/feedback_handler.py

import json
from datetime import datetime
from typing import Dict
from fastapi import WebSocket


class FeedbackHandler:

    def __init__(self, session_manager, s3_storage_service):
        self.session_manager = session_manager
        self.s3_storage_service = s3_storage_service

    async def handle_feedback(self, websocket: WebSocket, data: Dict):
        session_id = data.get("session_id")
        feedback_type = data.get("feedback_type")
        feedback_text = data.get("feedback_text")
        panel = data.get("panel", "unknown")

        # Validate session
        if not session_id or not self.session_manager.exists(session_id):
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Invalid session for feedback"
            }))
            return

        session = self.session_manager.get_session(session_id)

        user_id = (
            session.get("username")
            or data.get("username")
            or data.get("user_id")
        )

        # Normalize feedback text
        feedback_text = str(feedback_text or "").strip()

        # Timestamp handling
        timestamp = data.get("timestamp")
        try:
            ts = (
                datetime.fromtimestamp(float(timestamp) / 1000)
                if timestamp
                else datetime.now()
            )
        except Exception:
            ts = datetime.now()

        # Store in session
        if "feedback" not in session:
            session["feedback"] = []

        feedback_entry = {
            "user_id": user_id,
            "type": feedback_type,
            "text": feedback_text,
            "panel": panel,
            "timestamp": ts.isoformat(),
            "csv_stored": False
        }

        session["feedback"].append(feedback_entry)

        # Store to CSV in S3
        try:
            feedback_data = {
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": feedback_type,
                "feedback_text": feedback_text,
                "panel": panel,
                "timestamp": ts
            }

            csv_success = await self.s3_storage_service.store_feedback_to_csv(feedback_data)

            if csv_success:
                feedback_entry["csv_stored"] = True

            await websocket.send_text(json.dumps({
                "type": "feedback_received",
                "session_id": session_id,
                "csv_stored": csv_success
            }))

        except Exception as e:
            await websocket.send_text(json.dumps({
                "type": "feedback_received",
                "session_id": session_id,
                "csv_stored": False,
                "error": str(e)
            }))
