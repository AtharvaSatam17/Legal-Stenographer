# services/vad_service.py

import asyncio
import contextlib
import json
import base64
import time
from typing import Dict, Any, Callable, Optional
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class VADService:

    def __init__(self, sarvam_service):
        self.sarvam_service = sarvam_service
        self.active_streams: Dict[str, Any] = {}

    async def start_vad_stream(
        self,
        session_id: str,
        model: str = "saaras:v3",
        target_language: Optional[str] = None,
        event_callback: Optional[Callable] = None,
        timeout: int = 300,
    ) -> bool:

        if session_id in self.active_streams:
            print(f"⚠️ VAD start_vad_stream: Stream already active for session={session_id}")
            return False

        try:
            print(f"🚀 VAD start_vad_stream: Starting VAD stream for session={session_id} with model={model}")

            ws_context = await self.sarvam_service.create_vad_stream(
                model=model,
                use_translation=bool(target_language),
            )

            print(f"✅ VAD start_vad_stream: VAD stream context created for session={session_id}")

            ws = await ws_context.__aenter__()

            print(f"✅ VAD start_vad_stream: WebSocket connected for session={session_id}")

            self.active_streams[session_id] = {
                "websocket": ws,
                "websocket_context": ws_context,
                "target_language": target_language,
                "event_callback": event_callback,
                "timeout": timeout,
                "is_processing": False,
                "start_time": time.time(),
                "listener_task": None,
                "connection_active": True,
            }

            listener_task = asyncio.create_task(self._listen_vad_events(session_id))
            self.active_streams[session_id]["listener_task"] = listener_task

            print(f"✅ VAD start_vad_stream: Listener task started for session={session_id}")
            return True

        except Exception as e:
            print(f"❌ VAD start_vad_stream: Failed to start VAD stream for session={session_id}: {e}")
            import traceback
            traceback.print_exc()
            if session_id in self.active_streams:
                del self.active_streams[session_id]
            return False

    async def send_audio_chunk(
        self,
        session_id: str,
        audio_data: bytes,
        encoding: str = "audio/wav",
        sample_rate: int = 16000,
    ) -> bool:

        if session_id not in self.active_streams:
            print(f"⚠️ VAD send_audio_chunk: No VAD stream for session={session_id}")
            return False

        stream = self.active_streams[session_id]

        if not stream["connection_active"]:
            print(f"⚠️ VAD send_audio_chunk: Connection not active for session={session_id}")
            return False

        if stream["is_processing"]:
            print(f"⚠️ VAD send_audio_chunk: Still processing previous chunk for session={session_id}")
            return False

        try:
            if not audio_data:
                print(f"⚠️ VAD send_audio_chunk: Empty audio data for session={session_id}")
                return False

            audio_b64 = base64.b64encode(audio_data).decode("utf-8")

            ws = stream["websocket"]
            target_language = stream["target_language"]

            print(f"🎵 VAD send_audio_chunk: Sending {len(audio_data)} bytes to Sarvam API for session={session_id}")

            stream["is_processing"] = True

            try:
                if target_language:
                    await ws.translate(
                        audio=audio_b64,
                        encoding=encoding,
                        sample_rate=sample_rate,
                    )
                    print(f"✅ VAD: Sent translation request for session={session_id}")
                else:
                    await ws.transcribe(
                        audio=audio_b64,
                        encoding=encoding,
                        sample_rate=sample_rate,
                    )
                    print(f"✅ VAD: Sent transcription request for session={session_id}")

                return True

            finally:
                stream["is_processing"] = False

        except Exception as e:
            print(f"❌ VAD send_audio_chunk failed for session={session_id}: {e}")
            import traceback
            traceback.print_exc()
            stream["connection_active"] = False
            stream["is_processing"] = False
            return False

    async def _listen_vad_events(self, session_id: str):

        if session_id not in self.active_streams:
            print(f"⚠️ VAD _listen_vad_events: No stream found for session={session_id}")
            return

        stream = self.active_streams[session_id]
        ws = stream["websocket"]
        callback = stream["event_callback"]
        timeout = stream["timeout"]

        print(f"🎧 VAD _listen_vad_events: Starting listener for session={session_id}")

        try:
            with contextlib.suppress(asyncio.TimeoutError):
                async with asyncio.timeout(timeout):
                    async for message in ws:

                        if not stream["connection_active"]:
                            print(f"⚠️ VAD _listen_vad_events: Connection no longer active for session={session_id}")
                            break

                        print(f"📢 VAD _listen_vad_events: Received message for session={session_id}: {message}")

                        if isinstance(message, str):
                            try:
                                message = json.loads(message)
                            except json.JSONDecodeError:
                                print(f"⚠️ VAD _listen_vad_events: Failed to parse JSON message for session={session_id}")
                                continue

                        if callback:
                            try:
                                print(f"🔄 VAD _listen_vad_events: Calling callback for session={session_id}")
                                await callback(session_id, message)
                            except Exception as e:
                                print(f"❌ VAD callback error for session={session_id}: {e}")
                                import traceback
                                traceback.print_exc()

        except asyncio.CancelledError:
            print(f"🛑 VAD listener cancelled for {session_id}")

        except Exception as e:
            print(f"❌ VAD listener error for {session_id}: {e}")
            import traceback
            traceback.print_exc()

        finally:
            if session_id in self.active_streams:
                self.active_streams[session_id]["connection_active"] = False
            print(f"🏁 VAD _listen_vad_events: Listener ended for session={session_id}")

    async def stop_vad_stream(self, session_id: str) -> bool:

        if session_id not in self.active_streams:
            return False

        try:
            stream = self.active_streams[session_id]
            stream["connection_active"] = False

            if stream.get("listener_task"):
                stream["listener_task"].cancel()
                await asyncio.sleep(0.1)

            ws_context = stream.get("websocket_context")

            if ws_context:
                await ws_context.__aexit__(None, None, None)

            del self.active_streams[session_id]

            logger.info(f"Stopped VAD stream for {session_id}")
            return True

        except Exception:
            logger.exception(f"Error stopping VAD stream for {session_id}")
            return False

    async def stop_all_streams(self):

        sessions = list(self.active_streams.keys())

        for session_id in sessions:
            await self.stop_vad_stream(session_id)

    def is_stream_active(self, session_id: str) -> bool:

        if session_id not in self.active_streams:
            return False

        return self.active_streams[session_id]["connection_active"]

    async def get_stream_stats(self, session_id: str):

        if session_id not in self.active_streams:
            return None

        stream = self.active_streams[session_id]

        return {
            "session_id": session_id,
            "target_language": stream["target_language"],
            "start_time": stream["start_time"],
            "duration": time.time() - stream["start_time"],
            "connection_active": stream["connection_active"],
        }