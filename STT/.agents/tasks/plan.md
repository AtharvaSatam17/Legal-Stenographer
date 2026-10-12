# Implementation Plan — "New Paragraph" voice command + paragraph display + remove scratch/replace

This plan is grounded in the actual code read during exploration. It implements three things from the
original user request:

1. A **"new paragraph" voice command** (phrases: `new paragraph`, `new para`, `next paragraph`, `new line`,
   case-insensitive, matched only as the LEADING content of a segment) that inserts a paragraph break
   instantly (no propose/accept/reject), is NOT shown as transcript text anywhere, and is reflected in the
   live display, the S3 petition prose, and the PDF/TXT export.
2. **Paragraph (prose) rendering** of the live transcript, with a new paragraph starting at each command.
3. **Complete removal** of the voice-driven content-correction (scratch / "change that to X") feature.

Speaker tagging / speaker correction, the always-English translate pipeline, VAD, Sarvam, S3
audio/transcript/metadata upload, and session lifecycle must keep working. Diarization stays disabled.

---

## Key design decisions (chosen, not left open)

- **Paragraph-break representation = a marker segment inside `session['segments']`.**
  When a "new paragraph" command is detected, append a lightweight dict to `session['segments']`:
  `{"segment_id": "<id>", "is_paragraph_break": True, "transcript": "", "timestamp": ..., "start_time_seconds": ..., "end_time_seconds": ...}`.
  Rationale: `session['segments']` already flows unchanged into `session_data_copy['segments']` in
  `end_real_time_session` and then into `format_petition_prose`, so the ordering of breaks relative to
  content is preserved end-to-end for free. A content segment is distinguished from a break by the
  `is_paragraph_break` flag. The marker is NEVER broadcast as a `transcription_update` and carries no text.

- **New WebSocket message name = `paragraph_break`** (same name backend→frontend).
  Shape: `{"type": "paragraph_break", "session_id": <id>, "segment_id": <marker id>}`.
  The command segment itself is not broadcast, so this message is how the frontend learns of the break.

- **Phrase matching** uses a single pre-compiled regex, anchored at both ends like the existing
  `_SCRATCH_PATTERN`, case-insensitive, allowing surrounding whitespace and an optional trailing period:
  `^\s*(new\s+paragraph|new\s+para|next\s+paragraph|new\s+line)\.?\s*$` with `re.IGNORECASE`.
  Normalization (lowercase/strip/collapse-whitespace) is applied first, matching the existing parser style.
  This enforces "leading content of a segment" the same way the current parser does (`^ ... $` on the
  whole normalized segment).

- **`command_parser.classify_segment` is repurposed**: remove scratch/replace; return
  `{"kind": "paragraph_break"}` for a matched phrase, else `None`. Keep the English-only short-circuit
  (`_ENGLISH_LANGUAGE_CODES`) since the transcript is always English by the time it is classified.

- **`content_correction_handler.py` and `transcript_materializer.py` are DELETED** — they exist only for
  scratch/replace. The new-paragraph command is handled inline in `audio_stream_handler._handle_transcript`
  (it is a trivial, instant marker append + one websocket send; no lifecycle handler is warranted).

- **Frontend transcript state** keeps the existing per-segment `messages` array but each entry gains an
  optional `isParagraphBreak` flag; a `paragraph_break` message pushes a break marker entry. Rendering
  groups consecutive text entries into `<p>` paragraphs, splitting at each break marker. The TXT/PDF export
  joins each paragraph's text with spaces and separates paragraphs with a blank line (`\n\n`).

## Things that could NOT be fully verified by reading alone (implementer must verify at runtime)

- Whether Sarvam ever emits "new paragraph" / "new line" as a single leading segment vs. splitting it mid-
  utterance. The command only fires when the phrase is the LEADING (and whole) content of a segment, same
  constraint as the existing scratch command. Verify with a live mic test that saying "new paragraph"
  produces a break and is not shown as text.
- Exact live-display paragraph behavior (auto-scroll, Tailwind spacing) — verify visually in the browser.
- The frontend has NO test runner configured (no `test` script in `Frontend/package.json`, no jest). All
  frontend verification is manual (`npm run build` for compile, plus a browser smoke test).

---

# Backend

- [ ] 1. Repurpose the command parser: remove scratch/replace, add the paragraph-break command.
      In `command_parser.py` delete `_SCRATCH_PATTERN` and `_REPLACE_PATTERN`; add
      `_NEW_PARAGRAPH_PATTERN = re.compile(r"^\s*(new\s+paragraph|new\s+para|next\s+paragraph|new\s+line)\.?\s*$", re.IGNORECASE)`.
      Rewrite `classify_segment(text, language=None)` to keep the English-only short-circuit and the
      normalization, then return `{"kind": "paragraph_break"}` on a match, else `None`. Update the module
      docstring to describe the new scope.
      Files: `Backend/services/realtime/command_parser.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -m pytest tests/test_command_parser.py -q` — passes
      after the test file is rewritten in item 10.

- [ ] 2. Remove content-correction fields from session init; keep everything else.
      In `SessionManager.create_session`, delete the `content_corrections`, `pending_content_corrections`,
      and `content_correction_seq` keys. Leave `segments`, `speaker_tags`, `speaker_corrections`,
      `raw_transcript_buffer`, etc. untouched (no new field needed — paragraph breaks are stored as marker
      entries inside the existing `segments` list).
      Files: `Backend/core/session_manager.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -c "from core.session_manager import SessionManager"` — imports clean (no syntax error). Full suite runs in item 12.

- [ ] 3. Delete the content-correction handler and the transcript materializer.
      Delete `content_correction_handler.py` and `transcript_materializer.py` (both exist only for
      scratch/replace). Also delete their `__pycache__` `.pyc` files if present.
      Files (delete): `Backend/services/realtime/content_correction_handler.py`,
      `Backend/services/realtime/transcript_materializer.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -c "import glob; print(glob.glob('services/realtime/content_correction_handler.py') + glob.glob('services/realtime/transcript_materializer.py'))"` prints `[]`.

- [ ] 4. Handle the paragraph-break command inline in the audio stream handler.
      In `audio_stream_handler.py`: remove the `content_correction_handler` constructor param and attribute.
      In `_handle_transcript`, replace the current command block (which built `command_segment_data` and
      dispatched to `content_correction_handler.propose`, or sent `correction_failed`) with: when
      `classify_segment(transcript, language="en-IN")` returns `{"kind": "paragraph_break"}`, append a marker
      dict to `session["segments"]`
      (`{"segment_id": segment_id, "is_paragraph_break": True, "transcript": "", "timestamp": datetime.now().isoformat(), "start_time_seconds": start_time_seconds, "end_time_seconds": end_time_seconds}`),
      do NOT touch `transcript_buffer`/`raw_transcript_buffer`, send
      `{"type": "paragraph_break", "session_id": session_id, "segment_id": segment_id}` to the websocket, and
      `return` (no `transcription_update`). Keep the normal content path exactly as-is.
      Files: `Backend/services/realtime/audio_stream_handler.py`
      Verify: covered by the rewritten integration test in item 11 (`test_command_detection_integration.py`).

- [ ] 5. Remove content-correction wiring from the realtime service; keep speaker + resync + lifecycle.
      In `realtime_service.py`: remove the `ContentCorrectionHandler` import and instantiation; stop passing
      `content_correction_handler` into `AudioStreamHandler`. Delete the `content_correction_accept`,
      `content_correction_reject`, `content_correction_reverse`, and `content_correction_push` branches in
      `handle_websocket_message` (and the `uuid`/push helper code they use, if now unused). In
      `end_real_time_session`, delete the "Step 7" force-commit block and remove `content_corrections` from
      `session_data_copy`. In `_handle_session_resync`, drop `content_corrections` and
      `pending_content_corrections` from `state_payload` (keep `segments`, `transcript_buffer`,
      `session_active`). Keep `tag_speaker`, `correct_speaker`, `update_transcript`, start/end session intact.
      Files: `Backend/services/realtime/realtime_service.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -c "import ast; ast.parse(open('services/realtime/realtime_service.py', encoding='utf-8').read())"` — parses clean. Behavior covered by item 12 suite.

- [ ] 6. Strip content-correction logic from the background processor.
      In `background_processor.py`: remove `content_corrections = session_data.get(...)` reads, the
      `content_corrections_summary` block and the two `content_corrections_*` keys in `session_metadata`,
      and stop passing `content_corrections=` to `format_petition_prose` and to
      `s3_storage_service.upload_session_data`. The commented-out diarization block references
      `content_corrections` — update those comments/args too so re-enabling later won't reference removed
      state (or leave the commented block but delete the `content_corrections=` kwargs inside it). Keep the
      petition-prose path and audio save/upload otherwise unchanged.
      Files: `Backend/services/realtime/background_processor.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -c "import ast; ast.parse(open('services/realtime/background_processor.py', encoding='utf-8').read())"` — parses clean.

- [ ] 7. Make `format_petition_prose` emit paragraphs at break markers and drop content-correction logic.
      In `legal_transcript_formatter.py`: rewrite `format_petition_prose(segments, remove_fillers=False)` to
      remove the `content_corrections` parameter and the `_resolve_content_corrections_by_time` call. Iterate
      segments: on `seg.get("is_paragraph_break")` flush the current paragraph (join its cleaned pieces with
      `" "`) and start a new one; otherwise clean the text and append to the current paragraph. Join
      non-empty paragraphs with `"\n\n"`. Also delete the now-unused `_resolve_content_corrections_by_time`
      static method and remove the `content_corrections=` params from `format_legal_transcript` and
      `format_legal_transcript_json` (keep `speaker_corrections` and `_resolve_corrections_by_time` — those
      serve speaker correction and must stay). Remove the `†`/content-edit handling inside those two methods.
      Files: `Backend/services/legal_transcript_formatter.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -m pytest tests/test_legal_transcript_formatter.py -q` — existing speaker-correction tests still pass; new paragraph test from item 10 passes.

- [ ] 8. Remove the `corrections.json` S3 artifact and the `content_corrections` upload param.
      In `s3_storage_service.py`: delete the `content_corrections` parameter from `upload_session_data`,
      delete section "6. Upload corrections.json", and remove `content_corrections` from the docstring. Keep
      audio/transcription/diarization/legal_transcript/legal_transcript_json/metadata uploads unchanged.
      Files: `Backend/services/s3_storage_service.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -c "import ast; ast.parse(open('services/s3_storage_service.py', encoding='utf-8').read())"` — parses clean; and `grep` confirms no remaining `corrections.json` reference (sanity check only, not the primary verification).

- [ ] 9. Delete obsolete scratch/replace test files.
      Delete the test files that exist only to cover the removed feature:
      `test_content_correction_handler.py`, `test_content_corrections_in_formatter.py`,
      `test_corrections_json_artifact.py`, `test_push_to_command.py`, `test_transcript_materializer.py`
      (and their `__pycache__` `.pyc` files).
      Files (delete): the five files above under `Backend/tests/`.
      Verify: `cd Backend && .\venv\Scripts\python.exe -m pytest tests -q --collect-only` — collects with no
      import errors (no references to the deleted modules remain).

- [ ] 10. Rewrite `test_command_parser.py` for the new-paragraph command.
      Replace scratch/replace assertions with tests that: all four phrases
      (`new paragraph`, `new para`, `next paragraph`, `new line`) return `{"kind": "paragraph_break"}`
      case-insensitively and with surrounding whitespace / trailing period; mid-segment occurrences
      (e.g. `"start a new paragraph here"`) return `None`; normal content returns `None`; and the non-English
      short-circuit still returns `None` for `language="hi-IN"` etc.
      Files: `Backend/tests/test_command_parser.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -m pytest tests/test_command_parser.py -q` — all pass.

- [ ] 11. Rewrite `test_command_detection_integration.py` for the paragraph-break behavior.
      Keep the normal-content assertions (segment appended + `transcription_update` broadcast). Replace the
      scratch/replace cases with: feeding `"new paragraph"` does NOT append a content segment with that text
      and does NOT emit `transcription_update`; instead the last websocket message is
      `{"type": "paragraph_break", ...}` and `session["segments"]` gains exactly one entry whose
      `is_paragraph_break` is `True` and whose `transcript` is empty. Also assert normal content after a
      break is still appended and broadcast. Construct `AudioStreamHandler` without the correction handler
      arg (removed in item 4).
      Files: `Backend/tests/test_command_detection_integration.py`
      Verify: `cd Backend && .\venv\Scripts\python.exe -m pytest tests/test_command_detection_integration.py -q` — passes.

- [ ] 12. Update `test_session_resync.py` to drop content-correction coupling; add a formatter paragraph test.
      In `test_session_resync.py`: remove the `ContentCorrectionHandler` import and the
      `test_resync_updates_websocket_reference` test (it depends on the deleted handler) — or replace it with
      a resync assertion that only checks `segments`/`transcript_buffer`/`session_active`; drop the
      `content_corrections` seeding and assertions, keeping the segment/resync coverage.
      Add a new test (either a new `test_petition_prose_paragraphs.py` or a function in
      `test_legal_transcript_formatter.py`): given segments `[text, {is_paragraph_break}, text]`,
      `format_petition_prose` returns two paragraphs separated by `"\n\n"`, and a plain content-only list
      returns a single paragraph with no `"\n\n"`.
      Files: `Backend/tests/test_session_resync.py`, and new/edited
      `Backend/tests/test_legal_transcript_formatter.py` (or `Backend/tests/test_petition_prose_paragraphs.py`)
      Verify: `cd Backend && .\venv\Scripts\python.exe -m pytest tests -q` — the FULL suite passes (was 51
      passing at baseline; expect green after removals/rewrites).

---

# Frontend (no test runner configured — verify via build + manual smoke test)

- [ ] 13. Remove content-correction state, actions, shortcuts, overlay, and props from the orchestrator.
      In `LegalTranscriptionSystem.js`: delete the `pendingCorrections`, `appliedCorrections`,
      `correctionsByTarget` state and `lastSeenCorrectionIdRef`; the `acceptCorrection`, `rejectCorrection`,
      `undoCorrection`, `pushScratch`, `pushReplace`, `handleReplaceSubmit` functions; the `showReplaceInput`
      state, the Ctrl+Shift+S / Ctrl+Shift+R `keydown` effect, and the replace-input overlay JSX. Delete the
      `correction_proposed` / `correction_applied` / `correction_rejected` / `correction_reversed` /
      `correction_failed` cases in `handleWebSocketMessage`, and the content-correction rebuild inside the
      `session_state` case (keep rebuilding `messages` from `segments`). Remove `last_seen_correction_id`
      from the `session_resync` send. Remove the correction props passed to `LegalTranscriptPanel`. Update the
      dev debug panel text (drop correction counts / shortcut hints).
      Add a `paragraph_break` case to `handleWebSocketMessage` that pushes a break marker into `messages`
      (`{ segment_id: data.segment_id, isParagraphBreak: true }`). Keep `transcript` string unchanged on a
      break (it is just display prose; the break only affects paragraph grouping).
      Files: `Frontend/components/legal/LegalTranscriptionSystem.js`
      Verify: part of the `npm run build` in item 16; plus manual smoke test (item 16).

- [ ] 14. Render paragraphs and remove the correction overlay in the transcript panel.
      In `LegalTranscriptPanel.js`: remove the `CorrectionOverlay` import and all correction props
      (`pendingCorrections`, `appliedCorrections`, `correctionsByTarget`, `onAcceptCorrection`,
      `onRejectCorrection`, `onUndoCorrection`) and the `getCorrectionForSegment` helper. Replace the current
      `messages.map(...).reduce(...)` render with logic that groups `messages` into paragraphs: iterate,
      starting a new paragraph group at each `msg.isParagraphBreak` entry (and skipping the marker itself),
      and render each group as a `<p className="mb-4">` of space-joined segment text, preserving the existing
      Tailwind prose styling (`leading-loose text-justify text-[15px]`). Update the footer hint text to drop
      the Ctrl+Shift+S/R mention (keep "Click speaker badge to correct").
      Files: `Frontend/components/legal/LegalTranscriptPanel.js`
      Verify: part of `npm run build` (item 16) + manual browser check that breaks start new paragraphs.

- [ ] 15. Make the export emit paragraph breaks, and delete the unused overlay component.
      In `LegalExportService.js`: change `buildProse()` to build paragraphs — group `messages` into
      paragraphs split at `isParagraphBreak` markers, join each paragraph's segment text with `" "`, and join
      paragraphs with `"\n\n"` (fallback to the raw `transcript` string when there are no messages). Ensure
      both TXT (`content += ...`) and the PDF path render blank lines between paragraphs: for the PDF,
      `addText` is called per paragraph with an extra `yPosition += lineHeight` gap between paragraphs (or
      pass the `"\n\n"`-joined string through `splitTextToSize`, which preserves blank lines).
      Delete `CorrectionOverlay.js` (now unused after item 14).
      Files: `Frontend/components/legal/LegalExportService.js`; delete
      `Frontend/components/legal/CorrectionOverlay.js`
      Verify: part of `npm run build` (item 16) + manual export check that paragraphs are separated.

- [ ] 16. Build the frontend and smoke-test the full flow.
      Run the Next.js production build to confirm no import/compile errors from the removals (deleted
      `CorrectionOverlay`, removed props/state).
      Files: none (verification only).
      Verify: `cd Frontend && npm run build` — completes with no errors. Then a manual smoke test with the
      backend running (`cd Backend && .\venv\Scripts\uvicorn.exe main:app --port 8000`): start a session,
      dictate a sentence, say "new paragraph", dictate another sentence — confirm the command text is NOT
      shown, a new paragraph begins in the live display, and TXT/PDF export shows two paragraphs. (This
      runtime step is the manual verification called out above; note it in the PR if the environment cannot
      exercise a live mic.)

---

## Notes for the implementer

- Run backend tests from the `Backend` directory using the venv interpreter:
  `.\venv\Scripts\python.exe -m pytest tests -q`. The tests rely on `sys.path.insert(0, ..)` to import
  `services`/`core`, so the working directory matters.
- The baseline suite was 51 passing before changes. After this work the suite should still be green with the
  rewritten/added tests and the removed scratch/replace tests gone.
- Do not remove speaker correction (`correct_speaker`, `speaker_corrections`,
  `_resolve_corrections_by_time`) — it is a separate feature that must keep working.
- Keep the websocket message name `paragraph_break` identical on backend and frontend.

---

# Verification (iteration 1)

All commands run from the stated directories on Windows PowerShell.

## Backend — pytest
Command: `.\venv\Scripts\python.exe -m pytest tests -q` (cwd: `Backend`)
Result: **26 passed, 3 warnings** (the 3 warnings are pre-existing deprecation
warnings from the `sarvamai`/`websockets` SDK, unrelated to this change).
Baseline before changes was 51 passed; the drop to 26 is expected — five
scratch/replace-only test files were deleted and two obsolete tests in
`test_end_session_race.py` were removed, while new paragraph-command and
petition-prose paragraph tests were added.

Test changes:
- Rewrote `tests/test_command_parser.py` — asserts all four phrases
  (`new paragraph`, `new para`, `next paragraph`, `new line`) classify as
  `{"kind": "paragraph_break"}` (case-insensitive, whitespace/period tolerant),
  mid-segment occurrences and normal content return `None`, the removed
  scratch/replace phrases return `None`, and the non-English short-circuit holds.
- Rewrote `tests/test_command_detection_integration.py` — a `new paragraph`
  segment is NOT broadcast as `transcription_update` and NOT stored as content;
  instead a `paragraph_break` message is emitted and a break marker
  (`is_paragraph_break: True`, empty transcript) is appended; normal content
  before/after is still appended and broadcast.
- Added paragraph tests to `tests/test_legal_transcript_formatter.py` —
  single-paragraph output with no markers, two paragraphs separated by `\n\n`
  with one marker, and no empty paragraphs from leading/trailing/consecutive
  markers.
- Updated `tests/test_session_resync.py` — dropped the content-correction
  seeding/assertions and the `ContentCorrectionHandler` dependency; resync still
  covers `segments`/`transcript_buffer`/`session_active`.
- Rewrote `tests/test_end_session_race.py` — kept the late-transcript-rejection
  test (constructed `AudioStreamHandler` without the removed handler arg);
  removed the force-commit/snapshot content-correction tests.
- Deleted obsolete test files: `test_content_correction_handler.py`,
  `test_content_corrections_in_formatter.py`, `test_corrections_json_artifact.py`,
  `test_push_to_command.py`, `test_transcript_materializer.py`.

## Frontend — lint + build
Command: `npm run lint` (cwd: `Frontend`)
Result: **0 errors, 7 warnings** — all 7 are pre-existing
`no-unused-vars`/`react-hooks/exhaustive-deps` warnings (e.g. `tagSpeaker`,
`correctSpeaker`, `speakerMapping`, auth-page effect deps) that predate this
change. No new errors introduced.

Command: `npm run build` (cwd: `Frontend`)
Result: **Compiled successfully** (Next.js 15.5.2 production build, 5 static
pages generated). No import/compile errors after deleting `CorrectionOverlay.js`
and removing the correction props/state.

## Grep — no lingering references in live code
- Backend non-test (`Backend/**/*.py` excluding `tests/`): no matches for
  `content_correction`, `ContentCorrectionHandler`,
  `_resolve_content_corrections_by_time`, `transcript_materializer`,
  `corrections.json`, `pending_content_corrections`, `scratch that`,
  `change that to`, `_SCRATCH_PATTERN`, `_REPLACE_PATTERN`,
  `force_commit_all_pending`.
- Frontend components (`Frontend/components/**/*.js`): no matches for
  `content_correction`, `CorrectionOverlay`, `pushScratch`, `pushReplace`,
  `pendingCorrections`, `appliedCorrections`, `correctionsByTarget`,
  `lastSeenCorrectionId`, `correction_proposed`, `showReplaceInput`.
  (Stale references remain only in the generated `Frontend/.next/` build cache,
  which is regenerated on build and not a live source path.)

## Not verifiable in this environment (manual runtime check)
- Live mic behavior (saying "new paragraph" produces a break and is not shown
  as text) and the visual paragraph rendering/auto-scroll require a running
  backend + browser + microphone, which this environment cannot exercise.
  The unit/integration tests cover the equivalent logic deterministically.
