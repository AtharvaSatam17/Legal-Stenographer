# Frontend Architecture Documentation

## Overview

The Legal Stenographer frontend is a **Next.js 15** application built with **React 19** that provides a real-time court/legal transcription interface. It connects to the backend via WebSocket for live audio streaming and transcript updates.

**Primary Use Case:** Lawyer–Client consultation recording with real-time speech-to-text transcription, speaker identification, and content correction capabilities.

---

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Next.js | 15.5.2 | React framework with SSR/SSG |
| React | 19.1.0 | UI library |
| Tailwind CSS | 4.x | Utility-first CSS framework |
| lucide-react | 0.543.0 | Icon library |
| jsPDF | 4.1.0 | PDF generation for exports |
| jose | 6.1.0 | JWT verification (Cognito) |
| axios | 1.11.0 | HTTP client |
| js-cookie | 3.0.8 | Client-side cookie management |

---

## Project Structure

```
Frontend/
├── components/
│   └── legal/                      # Legal transcription UI components
│       ├── CorrectionOverlay.js    # Content correction UI (pending/applied states)
│       ├── LegalControlsPanel.js   # Recording start/pause/stop controls
│       ├── LegalExportService.js   # TXT/PDF export functionality
│       ├── LegalHeader.js          # App header with connection status
│       ├── LegalMetadataPanel.js   # Case metadata form
│       ├── LegalTranscriptionSystem.js  # Main orchestrator component
│       ├── LegalTranscriptPanel.js # Live transcript display
│       └── SpeakerLegend.js        # Speaker color legend
├── lib/
│   ├── auth.js                     # JWT verification utilities
│   └── withAuth.js                 # SSR auth HOC
├── pages/
│   ├── api/
│   │   └── auth/
│   │       ├── callback.js         # OAuth2 token exchange
│   │       └── logout.js           # Session logout
│   ├── auth/
│   │   ├── callback.js             # Client-side auth callback
│   │   └── success.js              # Post-login redirect
│   ├── _app.js                     # App wrapper
│   ├── _document.js                # HTML document structure
│   └── index.js                    # Main page entry
├── styles/
│   └── globals.css                 # Global styles + Tailwind
├── package.json
├── next.config.ts
├── tsconfig.json
└── .env.local                      # Environment variables
```

---

## Component Architecture

### Component Hierarchy

```
index.js (Home Page)
└── LegalTranscriptionSystem (Main Orchestrator)
    ├── LegalHeader
    │   └── Connection status, user info, case metadata display
    ├── LegalMetadataPanel
    │   └── Case ID, client role, matter type, date inputs
    ├── LegalControlsPanel
    │   └── Start/Pause/Resume/End session buttons
    ├── LegalTranscriptPanel
    │   └── CorrectionOverlay (per segment)
    │       └── Pending/Applied correction UI
    └── LegalExportService
        └── TXT/PDF export buttons
```

### Component Details

#### 1. LegalTranscriptionSystem.js (Core Orchestrator)
**Location:** `components/legal/LegalTranscriptionSystem.js`  
**Purpose:** Main component managing all state, WebSocket connection, and audio recording.

**Key Responsibilities:**
- WebSocket connection management with auto-reconnect
- Audio capture via WebAudio API (16kHz, mono, PCM)
- Session lifecycle (start → record → pause/resume → end)
- Content correction state management
- Keyboard shortcuts for quick commands

**State Management:**
```javascript
// Connection State
connectionStatus: 'disconnected' | 'connected' | 'error'
wsRef: WebSocket reference

// Session State
sessionId: string | null
sessionActive: boolean
isRecording: boolean
audioPaused: boolean

// Transcript State
transcript: string (full text)
messages: Array<{segment_id, text, timestamp, speaker, speakerConfidence}>

// Case Metadata
caseMetadata: {caseId, clientRole, matterType, date}

// Content Corrections
pendingCorrections: {[correction_id]: CorrectionObject}
appliedCorrections: {[correction_id]: CorrectionObject}
correctionsByTarget: {[segment_id]: correction_id}
```

**Keyboard Shortcuts:**
| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+S` | Push "scratch" command (delete last lawyer statement) |
| `Ctrl+Shift+R` | Open replace input modal |
| `Escape` | Close replace input modal |

---

#### 2. LegalHeader.js
**Location:** `components/legal/LegalHeader.js`  
**Purpose:** Application header with branding, connection status, and case metadata display.

**Props:**
```typescript
{
  caseMetadata: { caseId, clientRole, matterType, date }
  connectionStatus: 'disconnected' | 'connected' | 'error'
  user: { name?, username?, email? }
}
```

**Features:**
- WebSocket connection indicator (green/yellow/red)
- Dynamic client role label (Plaintiff/Defendant)
- User info display

---

#### 3. LegalMetadataPanel.js
**Location:** `components/legal/LegalMetadataPanel.js`  
**Purpose:** Form for entering case/consultation metadata before starting a session.

**Props:**
```typescript
{
  metadata: CaseMetadata
  onChange: (metadata: CaseMetadata) => void
  disabled: boolean  // Locked during active session
}
```

**Fields:**
| Field | Type | Required | Options |
|-------|------|----------|---------|
| Case/Matter ID | text | Yes | Free text |
| Client Role | select | Yes | plaintiff, defendant |
| Matter Type | select | No | consultation, follow_up, case_review, settlement_discussion, witness_prep |
| Date | date | No | Date picker |

---

#### 4. LegalControlsPanel.js
**Location:** `components/legal/LegalControlsPanel.js`  
**Purpose:** Recording control buttons and status indicators.

**Props:**
```typescript
{
  isRecording: boolean
  audioPaused: boolean
  sessionActive: boolean
  connectionStatus: string
  onStartSession: () => void
  onStopSession: () => void
  onPauseAudio: () => void
  onResumeAudio: () => void
  disabled: boolean
}
```

**Button States:**
- **Not Active:** "Start Session" button
- **Active + Recording:** "Pause Audio" + "End Session" buttons
- **Active + Paused:** "Resume Audio" + "End Session" buttons

---

#### 5. LegalTranscriptPanel.js
**Location:** `components/legal/LegalTranscriptPanel.js`  
**Purpose:** Displays live transcript with segment-level correction overlays.

**Props:**
```typescript
{
  messages: Message[]
  transcript: string
  isEditing: boolean
  onToggleEdit: () => void
  onSave: (editedTranscript: string) => void
  onCorrectSpeaker: (segmentId, speaker) => void
  clientRole: 'plaintiff' | 'defendant'
  sessionActive: boolean
  pendingCorrections: Record<string, Correction>
  appliedCorrections: Record<string, Correction>
  correctionsByTarget: Record<string, string>
  onAcceptCorrection: (correctionId) => void
  onRejectCorrection: (correctionId) => void
  onUndoCorrection: (correctionId) => void
}
```

**Features:**
- Continuous prose display (no timestamps/speaker labels in view)
- Manual transcript editing mode
- Auto-scroll to new content
- Word/segment count stats
- Per-segment CorrectionOverlay integration

---

#### 6. CorrectionOverlay.js
**Location:** `components/legal/CorrectionOverlay.js`  
**Purpose:** Renders correction states for individual transcript segments.

**Props:**
```typescript
{
  originalText: string
  pendingCorrection: PendingCorrection | null
  appliedCorrection: AppliedCorrection | null
  onAccept: (correctionId) => void
  onReject: (correctionId) => void
  onUndo: (correctionId) => void
  children: ReactNode
  inline: boolean  // Render as inline span vs block
}
```

**Correction States:**
1. **Clean:** Renders children normally
2. **Pending:** Strike-through original + replacement preview + Accept/Reject buttons + countdown timer
3. **Applied:** Shows corrected text with "edited" badge, hover reveals original + undo option

---

#### 7. LegalExportService.js
**Location:** `components/legal/LegalExportService.js`  
**Purpose:** Export transcript as TXT or PDF.

**Props:**
```typescript
{
  transcript: string
  messages: Message[]
  caseMetadata: CaseMetadata
  sessionId: string | null
}
```

**Export Formats:**
- **TXT:** Plain text with header, metadata, continuous prose, footer
- **PDF:** Formatted document via jsPDF with automatic page breaks

**Output Structure:**
```
================================================================================
PETITION
================================================================================

Case / Matter ID: CASE-2024-001
Matter Type: consultation
Date: 10/11/2026
Session ID: abc123

--------------------------------------------------------------------------------

[Continuous prose transcript content...]

================================================================================
END OF PETITION
================================================================================
```

---

#### 8. SpeakerLegend.js
**Location:** `components/legal/SpeakerLegend.js`  
**Purpose:** Visual legend showing speaker roles and their color coding.

**Speaker Colors:**
| Speaker | Color | CSS Classes |
|---------|-------|-------------|
| LAWYER | Blue | `text-blue-700 bg-blue-50` |
| PLAINTIFF/DEFENDANT | Amber | `text-amber-700 bg-amber-50` |

---

## WebSocket Communication

### Connection URL
```
NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/realtime'
```

### Auto-Reconnect Logic
- Reconnect attempts with exponential backoff: `[500ms, 1s, 2s, 5s]`
- Only reconnects if `sessionActive` is true
- On reconnect, sends `session_resync` to restore state

### Message Types

#### Client → Server

| Message Type | Payload | Description |
|--------------|---------|-------------|
| `start_session` | `{username, case_id, client_role, matter_type, preferred_language, processing_mode}` | Initialize new session |
| `audio_stream` | `{session_id, audio_data (base64), encoding, sample_rate}` | Stream audio chunks |
| `end_session` | `{session_id, username}` | End current session |
| `tag_speaker` | `{session_id, speaker_id, role}` | Assign role to speaker |
| `correct_speaker` | `{session_id, segment_id, speaker}` | Correct speaker for segment |
| `update_transcript` | `{session_id, transcript}` | Manual transcript edit |
| `content_correction_accept` | `{session_id, correction_id, staff_username}` | Accept pending correction |
| `content_correction_reject` | `{session_id, correction_id, staff_username}` | Reject pending correction |
| `content_correction_reverse` | `{session_id, correction_id, staff_username}` | Undo applied correction |
| `content_correction_push` | `{session_id, kind, replacement?, staff_username}` | Push scratch/replace command |
| `session_resync` | `{session_id, last_seen_correction_id}` | Request state resync after reconnect |

#### Server → Client

| Message Type | Payload | Description |
|--------------|---------|-------------|
| `session_started` | `{session_id}` | Session created |
| `transcription_update` | `{segment_id, transcript, timestamp, speaker, speaker_confidence}` | New transcript segment |
| `speaker_tagged` | `{speaker_id, role}` | Speaker role assigned |
| `speaker_corrected` | `{segment_id, corrected_speaker}` | Speaker correction applied |
| `session_ended` | `{data}` | Session terminated |
| `correction_proposed` | `{correction_id, kind, target_segment_id, original_text, replacement_text, auto_commit_at, command_segment_id}` | Pending correction |
| `correction_applied` | `{correction_id, kind, target_segment_id, original_text, replacement_text, confirmed_by, confirmation_timestamp}` | Correction committed |
| `correction_rejected` | `{correction_id, target_segment_id}` | Correction declined |
| `correction_reversed` | `{correction_id, reverses_correction_id, target_segment_id}` | Correction undone |
| `correction_failed` | `{reason, message}` | Correction error |
| `session_state` | `{segments[], content_corrections[], pending_content_corrections{}}` | Full state for resync |
| `session_resync_failed` | `{reason}` | Resync failed (session lost) |
| `error` | `{message}` | General error |

---

## Audio Recording

### Configuration
```javascript
{
  sampleRate: 16000,      // 16 kHz
  channelCount: 1,        // Mono
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true
}
```

### Processing Pipeline
1. `getUserMedia()` → MediaStream
2. `AudioContext` (16kHz) → `MediaStreamSource`
3. `ScriptProcessor` (4096 samples/buffer)
4. Float32 → Int16 PCM conversion
5. Base64 encode → WebSocket send

### Pause/Resume
- `audioPausedRef` flag controls whether audio is sent
- Audio pipeline stays connected; only transmission stops

---

## Authentication

### Flow: AWS Cognito OAuth2

```
┌──────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   Frontend   │ ──── │  Cognito Hosted │ ──── │  Backend API    │
│              │      │       UI        │      │  (if needed)    │
└──────────────┘      └─────────────────┘      └─────────────────┘
       │                      │
       │  1. Redirect to      │
       │     /login           │
       │─────────────────────>│
       │                      │
       │  2. User logs in     │
       │                      │
       │  3. Redirect back    │
       │     with ?code=xxx   │
       │<─────────────────────│
       │                      │
       │  4. Exchange code    │
       │     for tokens       │
       │─────────────────────>│
       │                      │
       │  5. Return tokens    │
       │<─────────────────────│
       │                      │
       │  6. Set cookies      │
       │     (id_token,       │
       │      access_token)   │
       │                      │
```

### Key Files

| File | Purpose |
|------|---------|
| `lib/auth.js` | Server-side JWT verification using JWKS |
| `lib/withAuth.js` | SSR HOC for protected pages |
| `pages/api/auth/callback.js` | Token exchange API route |
| `pages/api/auth/logout.js` | Logout + cookie clearing |
| `pages/auth/callback.js` | Client-side callback handler |
| `pages/auth/success.js` | Post-login redirect |

### Environment Variables
```env
COGNITO_REGION=ap-south-1
COGNITO_USER_POOL_ID=ap-south-1_xxxxx
COGNITO_CLIENT_ID=xxxxxxxxx
COGNITO_DOMAIN=https://your-domain.auth.ap-south-1.amazoncognito.com
CALLBACK_URI=http://localhost:3000/api/auth/callback
LOGOUT_URI=http://localhost:3000/
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/realtime
```

### Current Status
**Note:** Authentication is currently **mocked** in `pages/index.js` with a hardcoded user object. The full Cognito flow infrastructure exists but is bypassed for development.

---

## State Management

The application uses **React's built-in state** (useState, useRef) without external state management libraries.

### State Categories

| Category | Managed By | Persistence |
|----------|------------|-------------|
| Connection | LegalTranscriptionSystem | Memory (reconnect on disconnect) |
| Session | LegalTranscriptionSystem | Memory (lost on page refresh) |
| Transcript | LegalTranscriptionSystem | Memory (export before refresh) |
| Corrections | LegalTranscriptionSystem | Memory (resync from server) |
| Auth | Cookies | HttpOnly cookies |

### Refs for Callbacks
To avoid stale closures in callbacks, refs mirror state:
```javascript
isRecordingRef.current = isRecording
sessionIdRef.current = sessionId
audioPausedRef.current = audioPaused
sessionActiveRef.current = sessionActive
```

---

## Content Corrections System

### Correction Types
1. **Scratch:** Delete a segment entirely
2. **Replace:** Replace segment text with new content

### Correction Lifecycle
```
┌────────────┐    voice/keyboard    ┌──────────────┐
│   Clean    │ ─────────────────────>│   Proposed   │
│  Segment   │                       │  (Pending)   │
└────────────┘                       └──────────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
                    ▼                      ▼                      ▼
              ┌──────────┐          ┌──────────┐          ┌──────────┐
              │  Accept  │          │  Reject  │          │Auto-Commit│
              └──────────┘          └──────────┘          │ (timeout) │
                    │                      │              └──────────┘
                    ▼                      ▼                    │
              ┌──────────┐          ┌──────────┐                │
              │ Applied  │          │  Clean   │<───────────────┘
              │(editable)│          │ (reset)  │
              └──────────┘          └──────────┘
                    │
                    │  Undo
                    ▼
              ┌──────────┐
              │ Reversed │
              │ (clean)  │
              └──────────┘
```

### Auto-Commit Timer
Pending corrections have an `auto_commit_at` timestamp. The UI displays a countdown, and the backend auto-commits if no action is taken.

---

## Styling

### Tailwind CSS v4
- Imported via `@import "tailwindcss"` in `globals.css`
- Uses CSS custom properties for theming
- Supports `prefers-color-scheme: dark` (basic dark mode)

### Color Scheme
| Element | Light Mode | Dark Mode |
|---------|------------|-----------|
| Background | `#ffffff` | `#0a0a0a` |
| Foreground | `#171717` | `#ededed` |
| Primary (Blue) | `blue-600` | `blue-600` |
| Success (Green) | `green-600` | `green-600` |
| Warning (Yellow) | `yellow-600` | `yellow-600` |
| Error (Red) | `red-600` | `red-600` |

### Component Styling Patterns
- Cards: `bg-white rounded-lg shadow p-6`
- Buttons: `px-4 py-2 rounded-lg font-medium transition-colors`
- Status badges: `px-4 py-2 rounded-full`
- Form inputs: `border border-gray-300 rounded-lg focus:ring-2`

---

## Development

### Scripts
```bash
npm run dev      # Start dev server (http://localhost:3000)
npm run build    # Production build
npm run start    # Start production server
npm run lint     # Run ESLint
```

### Environment Setup
1. Copy `.env.local.example` to `.env.local`
2. Configure Cognito credentials
3. Set `NEXT_PUBLIC_WS_URL` to backend WebSocket URL

### Debug Panel
In development mode (`NODE_ENV === 'development'`), a debug panel shows:
- Session ID
- Connection status
- Recording state
- Message count
- Correction counts
- Keyboard shortcuts reference

---

## Future Considerations

1. **State Management:** Consider Zustand/Jotai if state complexity grows
2. **Offline Support:** Service worker for offline transcript caching
3. **Real-time Sync:** Consider WebSocket multiplexing for multi-user sessions
4. **Accessibility:** Add ARIA labels and keyboard navigation
5. **Testing:** Add unit tests with React Testing Library
6. **Error Boundaries:** Add React error boundaries for graceful failures
