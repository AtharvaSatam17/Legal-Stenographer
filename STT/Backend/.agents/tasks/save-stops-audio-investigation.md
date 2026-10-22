# Investigation: "No new transcription after Edit → Save"

Read-only code trace. No files were modified. All paths are absolute.

---

## 1. Summary answer (most important first)

Two hypotheses were on the table. One is **refuted by the code**, the other is **the real remaining cause but cannot be 100% proven from code alone** — it is a runtime behavior of the Sarvam streaming connection plus a reconnect/notification gap. Here is where it stands:

- **REFUTED — "edit/AI-draft suspends the AudioContext and Save never resumes it."**
  Entering edit mode does **not** touch audio at all. `toggleEditTranscript` only sets a paragraph-break flag; it never calls `pauseAudioRecording`, `audioContext.suspend()`, `stopAudioRecording`, or `ws.close()`. `audioPausedRef` stays `false` through Edit/AI-draft/Save, so `processor.onaudioprocess` keeps sending PCM. See evidence §3.1–§3.2.
  Pause/Resume (`pauseAudioRecording`/`resumeAudioRecording`) are wired only to the explicit Pause/Resume buttons in `LegalControlsPanel`, not to Edit/Save. So the "left suspended" theory does not hold.

- **REFUTED (already fixed) — "the None `end_time_seconds` on edited segments throws a TypeError and the next segment is silently dropped."**
  This was clearly a real past bug (there is a comment describing exactly this symptom), but the code now coalesces `None → 0.0` before any arithmetic, so no exception is raised and the next real segment is still broadcast. See evidence §5.1. I reproduced the guarded arithmetic and it does not raise.

- **REMAINING ROOT-CAUSE CANDIDATE (needs one runtime log to confirm) — the Sarvam streaming WebSocket closes during the Edit/Save interval and the reconnect path either fails or is never surfaced, so audio sent after Save is accepted locally but never produces a `transcription_update`.**
  The backend forwards post-Save audio to Sarvam only while `stream["connection_active"]` is `True` (`Backend/services/vad_service.py:send_audio_chunk`). If Sarvam's socket closed while the user was editing (not speaking), `send_audio_chunk` returns `False` and **silently drops** every chunk; the only recovery is `_attempt_reconnect`, and the frontend has **no handler** for the `stream_status`/`stream_closed` messages that would tell the user. See evidence §4 and §6.

Because the code path that would *definitively* kill transcription after Save (the TypeError) is already patched, the failure you are seeing is almost certainly transport-level and **timing dependent**. The decisive confirmation is a single backend log line — see §8 for exactly which one.

---

## 2. Scope of files traced

Frontend:
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Frontend\components\legal\LegalTranscriptionSystem.js`
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Frontend\components\legal\LegalTranscriptPanel.js`

Backend:
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Backend\main.py`
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Backend\services\realtime\realtime_service.py`
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Backend\services\realtime\audio_stream_handler.py`
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Backend\services\vad_service.py`
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Backend\services\sarvam_service.py`
- `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Backend\core\session_manager.py`

---

## 3. Frontend lifecycle evidence

### 3.1 Flag inventory and whether each is reset after Save

| Flag | Where set | Does Edit/Save change it? | Blocks `onaudioprocess`? |
|------|-----------|---------------------------|--------------------------|
| `isRecordingRef.current` | `startSession` → `true`; `endSession`/`session_ended` → `false` | **No** — neither Edit nor Save touch it | Yes (early-return if `false`) |
| `audioPausedRef.current` | `pauseAudioRecording` → `true`; `resumeAudioRecording`/`startSession` → `false` | **No** — only the Pause/Resume buttons touch it | Yes (early-return if `true`) |
| `isEditingTranscript` | `toggleEditTranscript` | Toggled by Edit/Save; **UI-only**, not referenced in audio path | No |
| `sessionActiveRef.current` | mirrors `sessionActive`; set `true` on `session_started`, `false` on end | No | No (used only for reconnect/resync) |
| `pendingParagraphBreakRef.current` | `toggleEditTranscript` on leave → `true`; cleared in `transcription_update` | Set on leaving edit; cleared on next segment | No — only controls paragraph grouping |

There is **no** `isFinal` / `isLocked` / `isProcessing` flag anywhere. The audio gate is exactly these three in `processor.onaudioprocess`:

`Frontend/.../LegalTranscriptionSystem.js`, inside `startAudioRecording`:
```js
processor.onaudioprocess = (e) => {
  if (!isRecordingRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || audioPausedRef.current) return;
  ...
  wsRef.current.send(JSON.stringify({ type: 'audio_stream', session_id: sessionIdRef.current, audio_data: base64Audio, encoding: 'audio/wav', sample_rate: 16000 }));
};
```
None of `isRecordingRef`, `audioPausedRef`, or `wsRef.readyState` is mutated by Edit, AI-draft, or Save. **So after Save the frontend keeps sending PCM.**

### 3.2 Edit/Save handlers do NOT touch audio or the socket

- `toggleEditTranscript` (`LegalTranscriptionSystem.js`): sets `pendingParagraphBreakRef.current = true` when leaving edit, then `setIsEditingTranscript(...)`. No audio/socket calls.
- `saveTranscript` (the `onSave` prop, `LegalTranscriptionSystem.js`): rebuilds `messages`, calls `setTranscript(...)`, and sends `{type:'update_transcript', session_id, paragraphs}`. **No `stopAudioRecording`, no `suspend`, no `ws.close()`.**
- `handleSaveAll` (`LegalTranscriptPanel.js`): `commitCurrentEdit()` → `onSave(paras)` → `onToggleEdit()`. No audio/socket calls.
- `runAiDraft` (`LegalTranscriptPanel.js`) → `onRequestAiDraft` → `requestAiDraft` (`LegalTranscriptionSystem.js`): sends `{type:'ai_draft', ...}`. No audio/socket calls.

### 3.3 useEffect / cleanup / key

The only lifecycle effect that tears down audio+socket is the mount effect:
```js
useEffect(() => { connectWebSocket(); return () => { ...; wsRef.current.close(); stopAudioRecording(); }; }, [connectWebSocket]);
```
`connectWebSocket` is `useCallback(..., [])` (stable), and nothing in Edit/Save changes it or any component `key`. So Save does **not** re-run this effect and does **not** tear down the socket/mic. **Refutes the "effect cleanup closes the mic" theory.**

### 3.4 Stale closures / state overwrite

- `transcription_update` uses functional updates: `setTranscript(prev => ...)` and `setMessages(prev => [...prev, seg])`. New segments **append**; they are not overwritten. (`LegalTranscriptionSystem.js`, `case 'transcription_update'`.)
- `saveTranscript` **replaces** `messages`/`transcript` with the edited paragraphs, but that happens once at Save time; subsequent `transcription_update`s still append to that new array. So a post-Save segment, if it arrives, **is rendered** (and `LegalTranscriptPanel.buildParagraphs` will show it, with a `post_edit_break` marker before it).

**Frontend conclusion:** the frontend neither stops the mic nor hides a post-Save segment. If nothing new appears, it is because **no `transcription_update` is arriving from the backend** after Save.

---

## 4. Transport evidence (the live Sarvam stream)

Transport is raw int16 PCM @16 kHz over the app WebSocket (`type:'audio_stream'`), decoded in `process_audio` and forwarded to Sarvam via `VADService`.

`Backend/services/vad_service.py` — `send_audio_chunk` is the choke point:
```python
if session_id not in self.active_streams:
    return False
stream = self.active_streams[session_id]
if not stream["connection_active"]:
    logger.warning(f"Connection not active for session={session_id}")
    return False
...
stream["pcm_buffer"].extend(audio_data)
if len(stream["pcm_buffer"]) >= MIN_BUFFER_BYTES:  # 0.5s
    ... queue.put(...)
```
If `connection_active` is `False`, **every post-Save chunk is dropped and only a `logger.warning` is emitted** — no error to the user, no transcript. The upstream `process_audio` ignores the return value, so nothing propagates to the frontend either.

`connection_active` becomes `False` in `_listen_vad_events`'s `finally` when the Sarvam socket's `async for message in ws` loop ends (normal close, idle timeout, or network blip). During a long Edit + AI-draft + Save interval the user is **not speaking**, so this is exactly when an idle close is most likely.

### 4.1 Reconnect exists, but has gaps

`_listen_vad_events` → `_attempt_reconnect`:
- Retries up to `MAX_RECONNECT_ATTEMPTS = 3` with backoff `[1,2,4]s`, then emits `{"type":"stream_closed","reason":"reconnect_failed"}` and **gives up** — `connection_active` stays `False`, so all further audio is dropped permanently.
- On the `except` branch it does `stream["reconnect_count"] += 1` then recurses into `_attempt_reconnect` — but it does **not** reset `connection_active`, so even a late success leaves a window where chunks are dropped.
- Race: on success it starts a **new** `_sender_loop` and `_listen_vad_events` while the previous `_sender_loop` may still be draining; both read/write the same `audio_queue`. Not the primary cause, but can reorder/lose a chunk.

### 4.2 The frontend is never told

`_listen_vad_events` and `handle_vad_event` emit `{"type":"stream_status", ...}` and `{"type":"stream_closed", ...}` to the frontend. **The frontend has no case for either** — `handleWebSocketMessage` in `LegalTranscriptionSystem.js` has cases for `transcription_update`, `paragraph_break`, `session_ended`, `session_state`, `ai_draft_*`, `error`, etc., but **nothing for `stream_status`/`stream_closed`**; they hit `default` and only `console.log('ℹ️ Unknown message type')`. Confirmed by grep: `stream_status|stream_closed|stream_reconnected` → **no matches** in `Frontend/**/*.js`.

Net effect: when the Sarvam stream dies during an edit and reconnect does not restore it, the user sees exactly the reported symptom — mic looks active, no new text, no error.

---

## 5. Backend session/state evidence

### 5.1 The TypeError-silent-drop path is already guarded (so Save itself does not crash the next segment)

`Backend/services/realtime/audio_stream_handler.py`, `_handle_transcript`:
```python
prev_segments = session.get("segments", [])
prev_end_raw = prev_segments[-1].get("end_time_seconds") if prev_segments else None
prev_end_val = prev_end_raw if isinstance(prev_end_raw, (int, float)) else 0.0
start_time_seconds = prev_end_val
```
After Save, `update_session_transcript` rebuilds `session["segments"]` so the last entry is an `edit_seg_i` with `end_time_seconds=None`. The `isinstance` guard coalesces that `None` to `0.0`, so the subsequent arithmetic and the monotonicity check do **not** raise. I reproduced the exact expressions with `prev_end_raw=None`: `start=0.0`, clamp-comparison `False`, no exception. **So a post-Save segment is still appended and broadcast as `transcription_update`.** This refutes the "edited-segment None breaks the next segment" theory as the *current* cause (it reads like a previously fixed bug — the inline comment documents that history).

### 5.2 Save/AI-draft do not lock or delete the session

- `update_session_transcript` (`realtime_service.py`): mutates `session["segments"]`, `transcript_buffer`, `raw_transcript_buffer`. It does **not** set any `finalized`/`completed`/`locked` flag, does **not** change `session_id`, does **not** touch `vad_active`, and does **not** delete the session. `process_audio`'s only gates are `exists(session_id)`, `session["ending"]`, and `session["vad_active"]` — none of which Save changes.
- `ai_draft_paragraph` (`realtime_service.py`): pure text op via Bedrock; explicitly not persisted; does not touch session audio state.
- `session_manager.py`: there is **no** `finalized`/`completed`/`locked` field at all. The only blocking flags are `ending` (set only by `end_session`) and `vad_active`.

So nothing in the backend's own session state blocks post-Save audio. The block, if any, is `connection_active` inside `VADService` (§4), which is independent of the app session.

### 5.3 Error swallowing

- `send_audio_chunk` returning `False` on a dead connection only logs a warning; the dropped audio is invisible to the user (§4).
- `_attempt_reconnect`'s inner `except Exception: pass` around `old_context.__aexit__` and the callback sends hide close/reconnect errors.
- `main.py` websocket loop catches generic `Exception` and only `print`s it.

---

## 6. Why the symptom is "after Edit/Save" specifically

Edit + AI-draft + Save is the one workflow that creates a **multi-second gap with no real speech** while the session stays open. That gap is the window in which the Sarvam stream is most likely to idle-close. Normal continuous dictation keeps the stream warm, so the bug does not appear. This matches "transcribes fine → edit/save → silence," and it is consistent with the fact that the only *code-certain* killer (the TypeError) is already fixed.

---

## 7. Minimal fix (proposed — NOT applied)

The robust fix has three independent parts. Part A is the smallest change that directly addresses the drop; B and C make the failure visible/recoverable.

### A. Don't silently drop audio when the Sarvam stream is down — trigger recovery

`Backend/services/vad_service.py`, in `send_audio_chunk`:
```diff
     stream = self.active_streams[session_id]

     if not stream["connection_active"]:
-        logger.warning(f"Connection not active for session={session_id}")
-        return False
+        logger.warning(f"Connection not active for session={session_id}; buffering + triggering reconnect")
+        # Keep the audio so it isn't lost, and kick a reconnect if one isn't already running.
+        if audio_data:
+            stream["pcm_buffer"].extend(audio_data)
+        if not stream.get("session_ending") and stream.get("reconnect_count", 0) < MAX_RECONNECT_ATTEMPTS:
+            asyncio.create_task(self._attempt_reconnect(session_id))
+        return False
```

### B. Surface stream status to the user so a dead stream isn't invisible

`Frontend/.../LegalTranscriptionSystem.js`, add cases in `handleWebSocketMessage`:
```diff
+      case 'stream_status':
+        console.log('📶 Stream status:', data.status, data.reason || '');
+        setConnectionStatus(data.status === 'connected' ? 'connected'
+          : data.status === 'disconnected' ? 'error' : 'connecting');
+        if (data.status === 'disconnected') {
+          alert('The transcription stream dropped and could not reconnect. Please End the session and start a new one.');
+        }
+        break;
```
(There is no `stream_closed` case needed separately; `handle_vad_event` already remaps closes to `stream_status`.)

### C. Reset `connection_active` deterministically around reconnect

`Backend/services/vad_service.py`, in `_attempt_reconnect`'s `except` branch, before recursing:
```diff
         except Exception as e:
             logger.exception(f"Reconnect failed for session={session_id}: {e}")
             stream["reconnect_count"] = reconnect_count + 1
+            stream["connection_active"] = False
             # Try again
             await self._attempt_reconnect(session_id)
```

> Note: parts B and C change user-visible behavior / recovery semantics. If you only want the smallest behavioral change, apply A alone; it keeps post-Save audio from being discarded and lets the existing reconnect path run.

---

## 8. If the cause can't be confirmed from code alone — exact runtime data needed

The code proves the frontend keeps sending and the backend session stays unlocked; it does **not** prove whether Sarvam's socket closed during the edit. To confirm, reproduce the bug (speak → Edit → AI-draft → Save → speak again) and collect:

1. **Backend log (decisive).** With `vad_service` logging at INFO/DEBUG, after Save look for either:
   - `Connection not active for session=...` from `send_audio_chunk` → **confirms** the stream was closed and post-Save audio is being dropped (root cause confirmed). Instrumentation point: `Backend/services/vad_service.py`, `send_audio_chunk`, the `if not stream["connection_active"]:` branch.
   - `Listener ended for session=...` / `Stream closed for session=...` / `Attempting reconnect .../3` / `Max reconnect attempts reached` from `_listen_vad_events` and `_attempt_reconnect` → tells you whether reconnect fired and whether it gave up.

2. **Browser DevTools → Network → WS frames** for `ws://localhost:8000/ws/realtime` after Save:
   - Outgoing `audio_stream` frames still present → confirms the mic/frontend is alive (refutes any remaining frontend theory).
   - Incoming frames: absence of `transcription_update` plus presence of `stream_status` → confirms backend-side stream death.

3. **Browser Console** after Save: look for `📶`/`ℹ️ Unknown message type: stream_status` (today it logs as "Unknown"), and confirm **no** `❌ WebSocket closed` for the app socket (i.e., the app WS is fine; only the upstream Sarvam stream died).

### Temporary instrumentation to add (copy-paste one-liners; remove after)

Frontend `Frontend/.../LegalTranscriptionSystem.js`:
- In `startAudioRecording`, first line of `onaudioprocess` body:
  `if (!isRecordingRef.current) console.log('⛔ gate: isRecording=false'); else if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) console.log('⛔ gate: ws not open', wsRef.current?.readyState); else if (audioPausedRef.current) console.log('⛔ gate: audioPaused');`
- Just before `wsRef.current.send(... audio_stream ...)`:
  `console.log('🎙️ send audio bytes=', pcmData.byteLength);`
- Top of `saveTranscript`: `console.log('💾 saveTranscript', { readyState: wsRef.current?.readyState, isRecording: isRecordingRef.current, audioPaused: audioPausedRef.current });`
- Top of `toggleEditTranscript`: `console.log('✏️ toggleEdit entering=', !isEditingTranscript);`
- Top of `requestAiDraft`: `console.log('🤖 requestAiDraft', { readyState: wsRef.current?.readyState });`
- `ws.onclose` first line: `console.log('🔌 app ws closed, sessionActive=', sessionActiveRef.current);`

Backend `Backend/services/realtime/audio_stream_handler.py`, top of `process_audio` after reading `session_id`:
`logger.info(f"RX audio session={session_id} ending={self.session_manager.get_session(session_id).get('ending') if self.session_manager.exists(session_id) else 'NO_SESSION'} vad_active={self.session_manager.get_session(session_id).get('vad_active') if self.session_manager.exists(session_id) else 'NO_SESSION'}")`

Backend `Backend/services/vad_service.py`:
- `send_audio_chunk`, first line: `logger.info(f"send_audio_chunk session={session_id} active={self.active_streams.get(session_id, {}).get('connection_active')}")`
- `_sender_loop`, right before `await ws.translate(...)`: `logger.info(f"→ Sarvam translate {len(pcm_data)} bytes session={session_id}")`
- `_listen_vad_events`, inside `async for message in ws:` first line: `logger.info(f"← Sarvam msg session={session_id}")`
- `_listen_vad_events` `finally`, first line: `logger.info(f"Sarvam listener FINALLY session={session_id} was_active={stream.get('connection_active')}")`

Backend `Backend/services/realtime/audio_stream_handler.py`, in `_handle_transcript` right before the final `await websocket.send_text(json.dumps(response))`:
`logger.info(f"BROADCAST transcription_update session={session_id} seg={segment_id} text='{transcript[:40]}'")`

If after Save you see `RX audio` and `send_audio_chunk ... active=False` but **no** `→ Sarvam translate` and **no** `BROADCAST transcription_update`, the Sarvam-stream-closed root cause (§1, §4) is confirmed and fix §7.A is the correct minimal change.

---

## 9. Secondary issues noticed

1. **Frontend ignores `stream_status`/`stream_closed`** (`LegalTranscriptionSystem.js`): a dropped upstream stream is completely invisible to the user. (Fix §7.B.)
2. **`send_audio_chunk` drops audio on a dead stream** with only a warning and no recovery trigger (`vad_service.py`). (Fix §7.A.)
3. **Reconnect race**: `_attempt_reconnect` spawns a new `_sender_loop`/`_listen_vad_events` without guaranteeing the old ones have exited; both share one `audio_queue`.
4. **`_attempt_reconnect` recursion** on the `except` path doesn't reset `connection_active`, widening the drop window. (Fix §7.C.)
5. **`update_transcript` message shape mismatch vs. docs**: `FRONTEND_ARCHITECTURE.md` documents `update_transcript` as `{session_id, transcript}` (string), but the frontend now sends `{session_id, paragraphs: [...]}`. The backend handles both, but the doc is stale.
6. **`end_session` buffer wait is a no-op-ish**: `await asyncio.sleep(min(2.0, 0.5))` always sleeps 0.5s regardless of the comment claiming "up to 2 seconds" (`realtime_service.py`). Unrelated to this bug but likely unintended.
7. **Broad error swallowing** in `main.py` (`except Exception: print(...)`) and in several `_attempt_reconnect` branches makes stream failures hard to diagnose in production.

---

## 10. Verification note

This was a read-only investigation. Backend tests live in `c:\Users\Atharva_Satam\Desktop\Atharva\STT\Talekar-STT\STT\Backend\tests\` (pytest; e.g. `test_session_resync.py`, `test_end_session_race.py`); frontend scripts in `Frontend/package.json` (`npm run lint`, `npm run build`). If/when fixes §7 are applied, add a `vad_service` unit test that asserts audio queued after a simulated `connection_active=False` triggers `_attempt_reconnect` (part A), and run `pytest Backend/tests` plus `npm run lint`. No code was changed and no server was restarted as part of this investigation.
