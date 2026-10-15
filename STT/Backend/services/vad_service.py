# services/vad_service.py

import asyncio
import base64
import io
import json
import time
import wave
from typing import Dict, Any, Callable, Optional
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Minimum buffer size before sending (0.5 seconds of 16kHz 16-bit mono PCM)
MIN_BUFFER_BYTES = 16000 * 2 * 0.5  # 16000 samples/sec * 2 bytes/sample * 0.5 sec = 16000 bytes

# Maximum reconnect attempts
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_BACKOFF_SECONDS = [1.0, 2.0, 4.0]


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """
    Wrap raw PCM data in a WAV header.
    
    The Sarvam SDK's ws.transcribe() expects WAV format, not raw PCM.
    This function creates a proper WAV file in memory.
    
    Args:
        pcm_data: Raw int16 PCM audio bytes
        sample_rate: Sample rate in Hz (default 16000)
        channels: Number of audio channels (default 1 = mono)
        sample_width: Bytes per sample (default 2 = 16-bit)
    
    Returns:
        Complete WAV file as bytes
    """
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()


class VADService:
    """
    Voice Activity Detection service that handles streaming audio to Sarvam API.
    
    Key features:
    - Converts raw PCM to WAV before sending (SDK requirement)
    - Buffers small chunks until 0.5s minimum for better transcription
    - Queue-based sender to ensure ordered delivery
    - Auto-reconnect on unexpected disconnects (up to 3 retries)
    - Always uses mode="translate" for English output
    """

    def __init__(self, sarvam_service):
        self.sarvam_service = sarvam_service
        self.active_streams: Dict[str, Any] = {}

    async def start_vad_stream(
        self,
        session_id: str,
        model: str = "saaras:v3",
        mode: str = "translate",
        event_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Start a VAD stream for the given session.
        
        Args:
            session_id: Unique session identifier
            model: Sarvam model to use (default saaras:v3)
            mode: Processing mode - "translate" for English output (default)
            event_callback: Async callback for VAD events
        
        Returns:
            True if stream started successfully, False otherwise
        """
        if session_id in self.active_streams:
            logger.warning(f"VAD stream already active for session={session_id}")
            return False

        try:
            logger.info(f"Starting VAD stream for session={session_id} with model={model}, mode={mode}")

            ws_context = await self.sarvam_service.create_vad_stream(
                model=model,
                mode=mode,
            )

            ws = await ws_context.__aenter__()

            logger.info(f"WebSocket connected for session={session_id}")

            # Create the audio queue for ordered sending
            audio_queue: asyncio.Queue = asyncio.Queue()

            self.active_streams[session_id] = {
                "websocket": ws,
                "websocket_context": ws_context,
                "event_callback": event_callback,
                "start_time": time.time(),
                "listener_task": None,
                "sender_task": None,
                "connection_active": True,
                "session_ending": False,
                "audio_queue": audio_queue,
                "pcm_buffer": bytearray(),  # Buffer for accumulating small chunks
                "model": model,
                "mode": mode,
                "reconnect_count": 0,
            }

            # Start listener task (receives events from Sarvam)
            listener_task = asyncio.create_task(self._listen_vad_events(session_id))
            self.active_streams[session_id]["listener_task"] = listener_task

            # Start sender task (sends audio from queue to Sarvam)
            sender_task = asyncio.create_task(self._sender_loop(session_id))
            self.active_streams[session_id]["sender_task"] = sender_task

            logger.info(f"VAD stream started for session={session_id}")
            return True

        except Exception as e:
            logger.exception(f"Failed to start VAD stream for session={session_id}: {e}")
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
        """
        Queue audio data for sending to Sarvam.
        
        Audio is buffered until MIN_BUFFER_BYTES (0.5s) before sending.
        Raw PCM is converted to WAV format before transmission.
        
        Args:
            session_id: Session identifier
            audio_data: Raw int16 PCM audio bytes
            encoding: Audio encoding (always converted to audio/wav)
            sample_rate: Sample rate in Hz
        
        Returns:
            True if queued successfully, False otherwise
        """
        if session_id not in self.active_streams:
            logger.warning(f"No VAD stream for session={session_id}")
            return False

        stream = self.active_streams[session_id]

        if not stream["connection_active"]:
            logger.warning(f"Connection not active for session={session_id}")
            return False

        if not audio_data:
            return False

        # Accumulate PCM data in buffer
        stream["pcm_buffer"].extend(audio_data)

        # Only send when we have enough data (0.5 seconds minimum)
        if len(stream["pcm_buffer"]) >= MIN_BUFFER_BYTES:
            pcm_chunk = bytes(stream["pcm_buffer"])
            stream["pcm_buffer"] = bytearray()

            # Queue the chunk for the sender task
            await stream["audio_queue"].put({
                "pcm_data": pcm_chunk,
                "sample_rate": sample_rate,
            })

        return True

    async def _sender_loop(self, session_id: str):
        """
        Sender task that pulls from the queue and sends to Sarvam.
        
        This ensures audio chunks are sent in order and handles
        backpressure gracefully.
        """
        if session_id not in self.active_streams:
            return

        stream = self.active_streams[session_id]
        queue = stream["audio_queue"]

        logger.info(f"Sender loop started for session={session_id}")

        try:
            while stream["connection_active"] or not queue.empty():
                try:
                    # Wait for audio with timeout to check connection_active periodically
                    chunk_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if chunk_data is None:
                    # Poison pill - stop the sender
                    break

                if not stream["connection_active"]:
                    # Connection closed while waiting, re-queue if reconnecting
                    if not stream["session_ending"]:
                        await queue.put(chunk_data)
                    break

                try:
                    pcm_data = chunk_data["pcm_data"]
                    sample_rate = chunk_data["sample_rate"]

                    # Convert PCM to WAV
                    wav_data = pcm_to_wav(pcm_data, sample_rate=sample_rate)
                    audio_b64 = base64.b64encode(wav_data).decode("utf-8")

                    ws = stream["websocket"]

                    # Use translate method for the translation streaming endpoint
                    await ws.translate(
                        audio=audio_b64,
                        encoding="audio/wav",
                        sample_rate=sample_rate,
                    )

                    stream["_sent_count"] = stream.get("_sent_count", 0) + 1
                    if stream["_sent_count"] % 10 == 0:
                        print(f"[DEBUG][VAD-SEND] translate() ok -> Sarvam: count={stream['_sent_count']} "
                              f"session={session_id}")

                except Exception as e:
                    print(f"[DEBUG][VAD-SEND] translate() EXCEPTION session={session_id}: {type(e).__name__}: {e}")
                    logger.error(f"Send error for session={session_id}: {e}")
                    stream["connection_active"] = False
                    # Re-queue the chunk for potential reconnect
                    if not stream["session_ending"]:
                        await queue.put(chunk_data)
                    break

        except asyncio.CancelledError:
            logger.info(f"Sender loop cancelled for session={session_id}")

        except Exception as e:
            logger.exception(f"Sender loop error for session={session_id}: {e}")

        finally:
            logger.info(f"Sender loop ended for session={session_id}")

    async def _listen_vad_events(self, session_id: str):
        """
        Listener task that receives events from Sarvam WebSocket.
        
        Handles:
        - Transcription results
        - VAD signals (speech start/end)
        - Connection errors with reconnect logic
        """
        if session_id not in self.active_streams:
            logger.warning(f"No stream found for session={session_id}")
            return

        stream = self.active_streams[session_id]
        ws = stream["websocket"]
        callback = stream["event_callback"]

        print(f"[DEBUG][VAD-LISTEN] listener STARTED session={session_id}")
        logger.info(f"Listener started for session={session_id}")

        try:
            # NOTE: Removed asyncio.timeout wrapper that was killing the listener after 300s
            async for message in ws:
                print(f"[DEBUG][VAD-LISTEN] <- message from Sarvam session={session_id} type={type(message).__name__}")
                if not stream["connection_active"]:
                    print(f"[DEBUG][VAD-LISTEN] connection_active=False, breaking session={session_id}")
                    logger.info(f"Connection no longer active for session={session_id}")
                    break

                # Pass the message as-is to the callback (don't force JSON parse here)
                # The callback (AudioStreamHandler) will handle normalization
                if callback:
                    try:
                        await callback(session_id, message)
                    except Exception as e:
                        logger.exception(f"Callback error for session={session_id}: {e}")

            print(f"[DEBUG][VAD-LISTEN] 'async for' ENDED NORMALLY (Sarvam closed the stream) session={session_id}")

        except asyncio.CancelledError:
            print(f"[DEBUG][VAD-LISTEN] listener CANCELLED session={session_id}")
            logger.info(f"Listener cancelled for session={session_id}")

        except Exception as e:
            print(f"[DEBUG][VAD-LISTEN] listener EXCEPTION session={session_id}: {type(e).__name__}: {e}")
            logger.exception(f"Listener error for session={session_id}: {e}")

        finally:
            print(f"[DEBUG][VAD-LISTEN] listener ENDED session={session_id} "
                  f"(was_active={stream.get('connection_active')}, ending={stream.get('session_ending')})")
            # Stream closed unexpectedly or normally
            was_active = stream.get("connection_active", False)
            stream["connection_active"] = False

            # Notify frontend about stream closure
            if callback and was_active and not stream.get("session_ending", False):
                try:
                    await callback(session_id, {"type": "stream_closed", "reason": "connection_ended"})
                except Exception as e:
                    logger.error(f"Failed to send stream_closed event: {e}")

            # Attempt reconnect if session is not ending
            if was_active and not stream.get("session_ending", False):
                await self._attempt_reconnect(session_id)

            logger.info(f"Listener ended for session={session_id}")

    async def _attempt_reconnect(self, session_id: str):
        """
        Attempt to reconnect the stream after unexpected disconnection.
        
        Retries up to MAX_RECONNECT_ATTEMPTS times with exponential backoff.
        The audio queue is preserved so pending chunks aren't lost.
        """
        if session_id not in self.active_streams:
            return

        stream = self.active_streams[session_id]

        if stream.get("session_ending", False):
            logger.info(f"Session ending, skipping reconnect for session={session_id}")
            return

        reconnect_count = stream.get("reconnect_count", 0)

        if reconnect_count >= MAX_RECONNECT_ATTEMPTS:
            logger.error(f"Max reconnect attempts reached for session={session_id}")
            # Notify callback about permanent failure
            callback = stream.get("event_callback")
            if callback:
                try:
                    await callback(session_id, {
                        "type": "stream_closed",
                        "reason": "reconnect_failed",
                        "attempts": reconnect_count,
                    })
                except Exception:
                    pass
            return

        backoff = RECONNECT_BACKOFF_SECONDS[min(reconnect_count, len(RECONNECT_BACKOFF_SECONDS) - 1)]
        logger.info(f"Attempting reconnect {reconnect_count + 1}/{MAX_RECONNECT_ATTEMPTS} "
                   f"for session={session_id} after {backoff}s backoff")

        await asyncio.sleep(backoff)

        # Check again if session is ending
        if stream.get("session_ending", False):
            return

        try:
            # Close old context if it exists
            old_context = stream.get("websocket_context")
            if old_context:
                try:
                    await old_context.__aexit__(None, None, None)
                except Exception:
                    pass

            # Create new connection
            ws_context = await self.sarvam_service.create_vad_stream(
                model=stream.get("model", "saaras:v3"),
                mode=stream.get("mode", "translate"),
            )
            ws = await ws_context.__aenter__()

            # Update stream state
            stream["websocket"] = ws
            stream["websocket_context"] = ws_context
            stream["connection_active"] = True
            stream["reconnect_count"] = reconnect_count + 1

            # Restart listener and sender tasks
            stream["listener_task"] = asyncio.create_task(self._listen_vad_events(session_id))
            stream["sender_task"] = asyncio.create_task(self._sender_loop(session_id))

            logger.info(f"Reconnected successfully for session={session_id}")

            # Notify callback about reconnection
            callback = stream.get("event_callback")
            if callback:
                try:
                    await callback(session_id, {"type": "stream_reconnected"})
                except Exception:
                    pass

        except Exception as e:
            logger.exception(f"Reconnect failed for session={session_id}: {e}")
            stream["reconnect_count"] = reconnect_count + 1
            # Try again
            await self._attempt_reconnect(session_id)

    async def flush_buffer(self, session_id: str) -> bool:
        """
        Flush any remaining buffered audio before stopping.
        
        Call this before stop_vad_stream to ensure the last utterance is sent.
        """
        if session_id not in self.active_streams:
            return False

        stream = self.active_streams[session_id]

        # Send any remaining buffered PCM
        if stream["pcm_buffer"]:
            pcm_chunk = bytes(stream["pcm_buffer"])
            stream["pcm_buffer"] = bytearray()

            if len(pcm_chunk) > 0:
                await stream["audio_queue"].put({
                    "pcm_data": pcm_chunk,
                    "sample_rate": 16000,
                })
                logger.info(f"Flushed {len(pcm_chunk)} bytes for session={session_id}")

        return True

    async def stop_vad_stream(self, session_id: str) -> bool:
        """
        Stop the VAD stream for a session.
        
        Properly cancels listener and sender tasks, closes WebSocket connection.
        """
        if session_id not in self.active_streams:
            return False

        try:
            stream = self.active_streams[session_id]
            stream["session_ending"] = True
            stream["connection_active"] = False

            # Send poison pill to stop sender
            await stream["audio_queue"].put(None)

            # Cancel listener task
            listener_task = stream.get("listener_task")
            if listener_task and not listener_task.done():
                listener_task.cancel()
                try:
                    await listener_task
                except asyncio.CancelledError:
                    pass

            # Wait for sender to finish (it should stop on poison pill or connection_active=False)
            sender_task = stream.get("sender_task")
            if sender_task and not sender_task.done():
                try:
                    await asyncio.wait_for(sender_task, timeout=2.0)
                except asyncio.TimeoutError:
                    sender_task.cancel()
                    try:
                        await sender_task
                    except asyncio.CancelledError:
                        pass

            # Close WebSocket context
            ws_context = stream.get("websocket_context")
            if ws_context:
                try:
                    await ws_context.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning(f"Error closing WebSocket context: {e}")

            del self.active_streams[session_id]

            logger.info(f"Stopped VAD stream for session={session_id}")
            return True

        except Exception:
            logger.exception(f"Error stopping VAD stream for session={session_id}")
            # Clean up anyway
            if session_id in self.active_streams:
                del self.active_streams[session_id]
            return False

    async def stop_all_streams(self):
        """Stop all active VAD streams."""
        sessions = list(self.active_streams.keys())
        for session_id in sessions:
            await self.stop_vad_stream(session_id)

    def is_stream_active(self, session_id: str) -> bool:
        """Check if a stream is currently active."""
        if session_id not in self.active_streams:
            return False
        return self.active_streams[session_id]["connection_active"]

    async def get_stream_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a stream."""
        if session_id not in self.active_streams:
            return None

        stream = self.active_streams[session_id]

        return {
            "session_id": session_id,
            "start_time": stream["start_time"],
            "duration": time.time() - stream["start_time"],
            "connection_active": stream["connection_active"],
            "reconnect_count": stream.get("reconnect_count", 0),
            "queue_size": stream["audio_queue"].qsize(),
            "buffer_size": len(stream["pcm_buffer"]),
        }
