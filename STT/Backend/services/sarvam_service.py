# services/sarvam_service.py

import os
import tempfile
import subprocess
import aiofiles
import aiohttp
from pathlib import Path
from typing import Dict
from sarvamai import AsyncSarvamAI
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SarvamService:
    """
    Sarvam AI service wrapper for speech-to-text with translation.
    
    Uses saaras:v3 model with mode="translate" and language_code="unknown"
    to auto-detect input language and always output English text.
    """

    def __init__(self):
        self.api_key = os.getenv("SARVAM_API_KEY")

        if not self.api_key:
            raise ValueError("SARVAM_API_KEY not found")

        self.base_url = "https://api.sarvam.ai"
        # Updated endpoint for speech-to-text (not speech-to-text-translate)
        self.endpoint = "/speech-to-text"

        self.async_client = AsyncSarvamAI(
            api_subscription_key=self.api_key
        )

        logger.info("SarvamService initialized with saaras:v3 translate mode")

    async def _convert_to_wav(self, file_path: str) -> str:
        """Convert audio file to 16kHz mono WAV format using ffmpeg."""
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_file.close()

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            file_path,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            temp_file.name,
        ]

        result = subprocess.run(
            cmd, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.PIPE
        )
        
        if result.returncode != 0:
            # Clean up temp file on failure
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
            error_msg = result.stderr.decode('utf-8', errors='replace')
            raise RuntimeError(f"ffmpeg conversion failed: {error_msg}")

        return temp_file.name

    async def transcribe_audio(self, audio_file_path: Path, options: Dict = None):
        """
        Batch transcription with translation to English.
        
        Uses /speech-to-text endpoint with model=saaras:v3 and mode=translate
        to auto-detect language and output English.
        """
        if options is None:
            options = {}

        converted = None
        try:
            converted = await self._convert_to_wav(str(audio_file_path))

            url = f"{self.base_url}{self.endpoint}"
            headers = {"api-subscription-key": self.api_key}

            async with aiofiles.open(converted, "rb") as f:
                audio = await f.read()

            form = aiohttp.FormData()
            form.add_field("model", options.get("model", "saaras:v3"))
            form.add_field("mode", options.get("mode", "translate"))
            form.add_field("language_code", options.get("language_code", "unknown"))
            form.add_field(
                "file",
                audio,
                filename=os.path.basename(converted),
                content_type="audio/wav",
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=form) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result
                    raise RuntimeError(await resp.text())
        finally:
            # Always clean up the converted temp file
            if converted:
                try:
                    os.unlink(converted)
                except OSError:
                    pass

    async def create_diarization_job(
        self,
        language_code: str = "unknown",
        model: str = "saarika:v2.5",
        num_speakers: int = 2,
    ):
        """
        Create a diarization job for speaker identification.
        
        Note: Diarization uses saarika:v2.5 which may not support translate mode.
        Use this for speaker labels only; the live stream provides English text.
        
        Args:
            language_code: "unknown" for auto-detect (default)
            model: Diarization model (saarika:v2.5)
            num_speakers: Expected number of speakers
        """
        return await self.async_client.speech_to_text_job.create_job(
            language_code=language_code,
            model=model,
            with_timestamps=True,
            with_diarization=True,
            num_speakers=num_speakers,
        )

    async def create_vad_stream(
        self,
        model: str = "saaras:v3",
        mode: str = "translate",
        vad_signals: bool = True,
        input_audio_codec: str = "wav",
    ):
        """
        Create a streaming connection for real-time speech-to-text with translation.
        
        Uses speech_to_text_translate_streaming endpoint which:
        - Auto-detects input language (no language_code required)
        - Always outputs English text when mode="translate"
        - Supports saaras:v3 model
        
        Args:
            model: Sarvam model to use (default "saaras:v3")
            mode: Processing mode - "translate" outputs English (default)
            vad_signals: Enable VAD events (default True)
            input_audio_codec: Audio format - "wav" or "pcm_s16le" (default "wav")
        
        Returns:
            WebSocket connection context manager
        """
        config = {
            "model": model,
            "mode": mode,
            "vad_signals": "true" if vad_signals else "false",
            "input_audio_codec": input_audio_codec,
        }
        
        logger.info(f"Creating VAD translate stream with config: {config}")
        
        # Use the dedicated translation streaming endpoint
        return self.async_client.speech_to_text_translate_streaming.connect(**config)
