# services/ai_drafting_service.py
#
# AI paragraph drafting via AWS Bedrock (Amazon Nova Pro).
#
# Given a single transcript/petition paragraph and a free-form instruction
# from the user (e.g. "make this more formal", "fix grammar", "rewrite as a
# legal petition statement"), returns a reframed version of that one
# paragraph. The model is instructed to output ONLY the rewritten paragraph
# text — no preamble, no explanation, no quotes.
#
# Credentials reuse the existing AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
# environment variables (same as the S3 service). Region and model id are
# overridable via BEDROCK_REGION / BEDROCK_MODEL_ID.

import os
import json
import asyncio
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# Default to the APAC regional inference profile for Nova Pro (required for
# Nova models in ap-south-1). Override with BEDROCK_MODEL_ID if your account
# uses a different region/profile (e.g. "amazon.nova-pro-v1:0" in us-east-1).
_DEFAULT_REGION = os.getenv("BEDROCK_REGION", "ap-south-1")
_DEFAULT_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-pro-v1:0")

_SYSTEM_PROMPT = (
    "You are a legal drafting assistant helping a lawyer refine a single "
    "paragraph of a legal consultation transcript / petition. You will be "
    "given one source paragraph and an instruction describing how to reframe "
    "it. Rewrite ONLY that paragraph according to the instruction.\n\n"
    "Rules:\n"
    "- Preserve the factual content, names, dates, figures and legal meaning. "
    "Do not invent facts or add claims that are not supported by the source.\n"
    "- Write in clear, professional English suitable for a legal petition "
    "unless the instruction says otherwise.\n"
    "- Return ONLY the rewritten paragraph text. No preamble, no explanation, "
    "no surrounding quotes, no numbering, no markdown.\n"
    "- Keep it to a single paragraph."
)

# Guardrails on output size.
_MAX_OUTPUT_TOKENS = 1200


class AIDraftingService:
    """Thin wrapper around Bedrock Converse for single-paragraph drafting."""

    def __init__(self):
        self.region = _DEFAULT_REGION
        self.model_id = _DEFAULT_MODEL_ID
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        self._client = None
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            logger.warning(
                "AI drafting disabled: AWS credentials not found in environment."
            )
            return

        try:
            self._client = boto3.client(
                "bedrock-runtime",
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.region,
            )
            logger.info(
                f"AIDraftingService initialized (region={self.region}, model={self.model_id})"
            )
        except Exception as e:
            logger.exception(f"Failed to initialize Bedrock client: {e}")
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def _invoke_sync(self, paragraph: str, instruction: str) -> str:
        """Blocking Bedrock Converse call. Run via a thread executor."""
        user_message = (
            f"Instruction:\n{instruction.strip()}\n\n"
            f"Source paragraph:\n{paragraph.strip()}"
        )

        response = self._client.converse(
            modelId=self.model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={
                "maxTokens": _MAX_OUTPUT_TOKENS,
                "temperature": 0.3,
                "topP": 0.9,
            },
        )

        # Converse response shape: output.message.content[].text
        content = (
            response.get("output", {})
            .get("message", {})
            .get("content", [])
        )
        parts = [c.get("text", "") for c in content if isinstance(c, dict)]
        text = "".join(parts).strip()
        # Strip wrapping quotes the model may add despite instructions.
        if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
            text = text[1:-1].strip()
        return text

    async def draft_paragraph(self, paragraph: str, instruction: str) -> str:
        """
        Reframe a single paragraph per the instruction.

        Raises RuntimeError on failure (caller translates to a ws error).
        """
        if not self.available:
            raise RuntimeError("ai_unavailable")

        if not paragraph or not paragraph.strip():
            raise RuntimeError("empty_paragraph")
        if not instruction or not instruction.strip():
            raise RuntimeError("empty_instruction")

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, self._invoke_sync, paragraph, instruction
            )
        except (BotoCoreError, ClientError) as e:
            logger.exception(f"Bedrock drafting call failed: {e}")
            raise RuntimeError("bedrock_error") from e
        except Exception as e:
            logger.exception(f"Unexpected drafting error: {e}")
            raise RuntimeError("drafting_failed") from e

        if not result:
            raise RuntimeError("empty_result")
        return result
