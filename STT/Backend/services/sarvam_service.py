# services/sarvam_service.py

import os
import uuid
import tempfile
import subprocess
import aiofiles
import aiohttp
import time
from pathlib import Path
from typing import Dict
from sarvamai import AsyncSarvamAI
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SarvamService:

    def __init__(self):

        self.api_key = os.getenv("SARVAM_API_KEY")

        if not self.api_key:
            raise ValueError("SARVAM_API_KEY not found")

        self.base_url = "https://api.sarvam.ai"
        self.endpoint = "/speech-to-text-translate"

        self.async_client = AsyncSarvamAI(
            api_subscription_key=self.api_key
        )

        logger.info("SarvamService initialized")

    async def _convert_to_wav(self, file_path: str) -> str:

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

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return temp_file.name

    async def transcribe_audio(self, audio_file_path: Path, options: Dict = None):

        if options is None:
            options = {}

        converted = await self._convert_to_wav(str(audio_file_path))

        url = f"{self.base_url}{self.endpoint}"

        headers = {"api-subscription-key": self.api_key}

        async with aiofiles.open(converted, "rb") as f:
            audio = await f.read()

        form = aiohttp.FormData()

        form.add_field("model", options.get("model", "saaras:v3"))

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
                    os.unlink(converted)
                    return result

                raise RuntimeError(await resp.text())

    async def create_diarization_job(
        self,
        language_code="en-IN",
        model="saarika:v2.5",
        num_speakers=2,
    ):

        return await self.async_client.speech_to_text_job.create_job(
            language_code=language_code,
            model=model,
            with_timestamps=True,
            with_diarization=True,
            num_speakers=num_speakers,
        )

    async def create_vad_stream(
        self,
        language_code="en-IN",
        model="saaras:v3",
        vad_signals=True,
        use_translation=False,
    ):

        config = {
            "language_code": language_code,
            "model": model,
            "vad_signals": vad_signals,
        }

        if use_translation:
            return self.async_client.speech_to_text_translate_streaming.connect(
                **config
            )

        return self.async_client.speech_to_text_streaming.connect(**config)