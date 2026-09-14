# Legal Stenographer - Frontend

Next.js 15 frontend for real-time court transcription with speaker diarization.

## Structure

```
Frontend/
├── package.json
├── next.config.ts
├── tsconfig.json
│
├── components/
│   └── legal/
│       ├── LegalTranscriptionSystem.js   # Main orchestrator
│       ├── LegalHeader.js                # Header with case info
│       ├── LegalMetadataPanel.js         # Case metadata input
│       ├── LegalControlsPanel.js         # Recording controls
│       ├── LegalTranscriptPanel.js       # Live transcript display
│       ├── SpeakerLegend.js              # Speaker role colors
│       └── LegalExportService.js         # PDF/TXT export
│
├── lib/
│   ├── auth.js                           # Cognito JWT verification
│   └── withAuth.js                       # Auth HOC for SSR
│
├── pages/
│   ├── index.js                          # Home (Legal Transcription)
│   ├── _app.js
│   ├── _document.js
│   ├── auth/                             # Auth callback pages
│   └── api/auth/                         # Auth API routes
│
├── styles/
│   └── globals.css
│
└── public/
    └── favicon.ico
```

## Setup

```bash
npm install
```

## Environment Variables

Create a `.env.local` file:

```
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/realtime
COGNITO_REGION=ap-south-1
COGNITO_USER_POOL_ID=your_pool_id
COGNITO_CLIENT_ID=your_client_id
COGNITO_DOMAIN=your_cognito_domain
CALLBACK_URI=http://localhost:3000/api/auth/callback
```

## Run

```bash
npm run dev
```

Open http://localhost:3000 to access the Legal Stenographer.
