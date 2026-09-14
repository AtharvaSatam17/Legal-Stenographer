# services/realtime/background_processor.py

import os
from datetime import datetime
from typing import Dict
from services.legal_transcript_formatter import LegalTranscriptFormatter


class BackgroundProcessor:

    def __init__(
        self,
        diarization_service,
        s3_storage_service,
    ):
        self.diarization_service = diarization_service
        self.s3_storage_service = s3_storage_service

    # ============================================================
    # BACKGROUND ENTRY

    async def process(self, session_data: Dict):

        session_id = session_data["session_id"]
        user_sub = session_data.get("user_sub")
        client_role = session_data.get("client_role", "plaintiff").upper()
        speaker_tags = session_data.get("speaker_tags", {})
        speaker_corrections = session_data.get("speaker_corrections", {})

        try:
            print(f"🔄 [BACKGROUND] Processing: {session_id}")

            # Build role mapping from manual speaker tags or default
            if speaker_tags:
                role_mapping = speaker_tags
            else:
                role_mapping = {
                    "SPEAKER_1": "LAWYER",
                    "SPEAKER_2": client_role,
                }

            # Create formatter with session-specific role mapping
            legal_formatter = LegalTranscriptFormatter(
                client_role=client_role,
                custom_role_mapping=role_mapping
            )

            # ----------------------------------------------------
            # DIARIZATION
            #
            # NOTE: Diarization is currently DISABLED. The system now
            # produces a single continuous petition (lawyer-only prose)
            # instead of a speaker-attributed consultation transcript.
            # The diarization pipeline below is intentionally commented
            # out (not removed) so it can be re-enabled later.
            #
            # To re-enable: uncomment the block below and remove/adjust
            # the "PETITION PROSE" section that follows it.
            # ----------------------------------------------------

            diarization_results = None
            audio_file_path = None
            legal_transcript = None
            legal_transcript_json = None

            content_corrections = session_data.get("content_corrections", [])

            # --- DIARIZATION PIPELINE (DISABLED) -----------------------------
            # if session_data.get("audio_buffer"):
            #     try:
            #         audio_file_path = await self.diarization_service.save_conversation_audio(
            #             session_id=session_id,
            #             audio_chunks=session_data["audio_buffer"],
            #             sample_rate=16000,
            #             channels=1
            #         )
            #
            #         if audio_file_path:
            #             diarization_results = await self.diarization_service.process_diarization(
            #                 audio_file_path=audio_file_path,
            #                 num_speakers=2,  # Consultation: Lawyer + Client
            #                 model="saarika:v2.5"
            #             )
            #
            #             # Format transcript if diarization succeeded
            #             if diarization_results and diarization_results.get('success'):
            #                 segments = diarization_results.get('diarized_segments', [])
            #
            #                 # Generate formatted transcript
            #                 # Precedence: manual correction > diarization > heuristic
            #                 # Phase 1, Step 7: content corrections also applied here
            #                 legal_transcript = legal_formatter.format_legal_transcript(
            #                     diarized_segments=segments,
            #                     speaker_corrections=speaker_corrections,
            #                     content_corrections=content_corrections,
            #                     remove_fillers=False,
            #                     include_duration=False
            #                 )
            #
            #                 # Generate structured JSON format
            #                 legal_transcript_json = legal_formatter.format_legal_transcript_json(
            #                     diarized_segments=segments,
            #                     metadata={
            #                         "session_id": session_id,
            #                         "case_id": session_data.get("case_id"),
            #                         "matter_type": session_data.get("matter_type"),
            #                         "client_role": client_role,
            #                         "date": session_data["start_time"].isoformat(),
            #                         "duration_seconds": (session_data["end_time"] - session_data["start_time"]).total_seconds()
            #                     },
            #                     speaker_corrections=speaker_corrections,
            #                     content_corrections=content_corrections,
            #                     remove_fillers=False
            #                 )
            #
            #                 print(f"✅ [BACKGROUND] Consultation transcript formatted for: {session_id}")
            #
            #     except Exception as e:
            #         print(f"❌ [BACKGROUND] Diarization failed: {e}")
            # ------------------------------------------------------------------

            # --- PETITION PROSE (diarization-free) ----------------------------
            # Still persist the raw audio so recordings remain available, then
            # build the petition as continuous prose from the live segments.
            if session_data.get("audio_buffer"):
                try:
                    audio_file_path = await self.diarization_service.save_conversation_audio(
                        session_id=session_id,
                        audio_chunks=session_data["audio_buffer"],
                        sample_rate=16000,
                        channels=1
                    )
                except Exception as e:
                    print(f"❌ [BACKGROUND] Audio save failed: {e}")

            try:
                live_segments = session_data.get("segments", [])
                legal_transcript = legal_formatter.format_petition_prose(
                    segments=live_segments,
                    content_corrections=content_corrections,
                    remove_fillers=False,
                )
                print(f"✅ [BACKGROUND] Petition prose generated for: {session_id}")
            except Exception as e:
                print(f"❌ [BACKGROUND] Petition prose generation failed: {e}")

            # ----------------------------------------------------
            # S3 UPLOAD

            if user_sub:
                try:
                    # Phase 1, Step 6 — content corrections summary for metadata
                    content_corrections = session_data.get("content_corrections", [])
                    content_corrections_summary = {
                        "total_proposed": sum(1 for c in content_corrections if c.get("kind") in ("scratch", "replace")),
                        "total_accepted": sum(1 for c in content_corrections if c.get("kind") in ("scratch", "replace") and c.get("confirmed_by") not in (None, "") and not str(c.get("confirmed_by", "")).startswith("rejected_by:")),
                        "total_auto_committed": sum(1 for c in content_corrections if c.get("confirmed_by") in ("auto_timeout", "ended_session_auto")),
                        "total_rejected": sum(1 for c in content_corrections if c.get("kind") == "rejected"),
                        "total_reversed": sum(1 for c in content_corrections if c.get("kind") == "reverse"),
                    }

                    session_metadata = {
                        "session_id": session_id,
                        "start_time": session_data["start_time"].isoformat(),
                        "end_time": session_data["end_time"].isoformat(),
                        "duration": (
                            session_data["end_time"] - session_data["start_time"]
                        ).total_seconds(),
                        "case_id": session_data.get("case_id"),
                        "matter_type": session_data.get("matter_type"),
                        "client_role": client_role,
                        "speaker_tags": speaker_tags,
                        "corrections_count": len(speaker_corrections),
                        "context": session_data.get("context"),
                        # Phase 1, Step 6
                        "content_corrections_summary": content_corrections_summary,
                        "content_corrections_language_scope": "en-IN,en",
                    }

                    await self.s3_storage_service.upload_session_data(
                        user_sub=user_sub,
                        session_id=session_id,
                        audio_file_path=audio_file_path,
                        transcript=session_data.get("raw_transcript_buffer", "") or session_data.get("transcript_buffer", ""),
                        diarization_results=diarization_results,
                        legal_transcript=legal_transcript or "",
                        legal_transcript_json=legal_transcript_json,
                        session_metadata=session_metadata,
                        content_corrections=content_corrections if content_corrections else None,
                    )

                    print(f"✅ [BACKGROUND] S3 upload completed for: {session_id}")

                except Exception as e:
                    print(f"❌ [BACKGROUND] S3 upload failed: {e}")

            # ----------------------------------------------------
            # CLEANUP TEMP FILE

            if audio_file_path and os.path.exists(audio_file_path):
                try:
                    os.remove(audio_file_path)
                except Exception:
                    pass

            print(f"✅ [BACKGROUND] Completed: {session_id}")

        except Exception as e:
            print(f"❌ [BACKGROUND] Fatal error: {e}")
