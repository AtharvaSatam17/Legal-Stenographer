'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import LegalHeader from './LegalHeader';
import LegalMetadataPanel from './LegalMetadataPanel';
import LegalControlsPanel from './LegalControlsPanel';
import LegalTranscriptPanel from './LegalTranscriptPanel';
import LegalExportService from './LegalExportService';

export default function LegalTranscriptionSystem({ user }) {
  // WebSocket and connection state
  const wsRef = useRef(null);
  const [connectionStatus, setConnectionStatus] = useState('disconnected');
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef(null);
  
  // Session state
  const [sessionId, setSessionId] = useState(null);
  const [sessionActive, setSessionActive] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isEndingSession, setIsEndingSession] = useState(false);
  const [audioPaused, setAudioPaused] = useState(false);
  
  // Audio recording refs
  const streamRef = useRef(null);
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  
  // Refs for callback access (to avoid stale closure)
  const isRecordingRef = useRef(false);
  const sessionIdRef = useRef(null);
  const audioPausedRef = useRef(false);
  const sessionActiveRef = useRef(false);
  
  // Transcript state
  const [transcript, setTranscript] = useState('');
  const [messages, setMessages] = useState([]);
  const [isEditingTranscript, setIsEditingTranscript] = useState(false);
  
  // Consultation-specific metadata
  const [caseMetadata, setCaseMetadata] = useState({
    caseId: '',
    clientRole: 'plaintiff',
    matterType: 'consultation',
    date: new Date().toISOString(),
  });
  
  // Speaker mapping (2-party: Lawyer + Client)
  const [speakerMapping, setSpeakerMapping] = useState({
    SPEAKER_1: 'LAWYER',
    SPEAKER_2: 'PLAINTIFF'
  });
  
  // Speaker corrections overlay
  const [speakerCorrections, setSpeakerCorrections] = useState({});

  // =====================================================================
  // Phase 1, Step 9 — Content correction state
  // =====================================================================
  const [pendingCorrections, setPendingCorrections] = useState({});       // {correction_id: {...}}
  const [appliedCorrections, setAppliedCorrections] = useState({});       // {correction_id: {...}}
  const [correctionsByTarget, setCorrectionsByTarget] = useState({});      // {segment_id: correction_id}
  
  // Track last correction_id for resync (Step 10)
  const lastSeenCorrectionIdRef = useRef(null);
  
  // Update speaker mapping when client role changes
  useEffect(() => {
    const clientLabel = caseMetadata.clientRole === 'defendant' ? 'DEFENDANT' : 'PLAINTIFF';
    setSpeakerMapping({
      SPEAKER_1: 'LAWYER',
      SPEAKER_2: clientLabel
    });
  }, [caseMetadata.clientRole]);

  // Keep sessionActiveRef in sync
  useEffect(() => {
    sessionActiveRef.current = sessionActive;
  }, [sessionActive]);
  
  // =====================================================================
  // WebSocket connection with reconnect (Step 10)
  // =====================================================================
  const connectWebSocket = useCallback(() => {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/realtime';
    console.log('🔌 Connecting to WebSocket:', wsUrl);
    
    const ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
      console.log('✅ WebSocket connected');
      setConnectionStatus('connected');
      reconnectAttemptRef.current = 0;

      // Step 10: if we had an active session, request resync
      if (sessionIdRef.current && sessionActiveRef.current) {
        ws.send(JSON.stringify({
          type: 'session_resync',
          session_id: sessionIdRef.current,
          last_seen_correction_id: lastSeenCorrectionIdRef.current,
        }));
      }
    };
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
      } catch (error) {
        console.error('❌ Error parsing WebSocket message:', error);
      }
    };
    
    ws.onerror = (error) => {
      console.error('❌ WebSocket error:', error);
      setConnectionStatus('error');
    };
    
    ws.onclose = () => {
      console.log('🔌 WebSocket closed');
      setConnectionStatus('disconnected');

      // Step 10: reconnect with backoff if session is active
      if (sessionActiveRef.current) {
        const delays = [500, 1000, 2000, 5000];
        const attempt = reconnectAttemptRef.current;
        const delay = delays[Math.min(attempt, delays.length - 1)];
        reconnectAttemptRef.current += 1;
        console.log(`🔄 Reconnecting in ${delay}ms (attempt ${attempt + 1})...`);
        reconnectTimerRef.current = setTimeout(() => {
          connectWebSocket();
        }, delay);
      }
    };
    
    wsRef.current = ws;
  }, []);
  
  // Handle WebSocket messages
  const handleWebSocketMessage = (data) => {
    console.log('📨 Received message:', data.type);
    
    switch (data.type) {
      case 'session_started':
        console.log('✅ Session started:', data.session_id);
        setSessionId(data.session_id);
        sessionIdRef.current = data.session_id;
        setSessionActive(true);
        break;
        
      case 'transcription_update':
        console.log('📝 Transcript update:', data.transcript?.substring(0, 50));
        setTranscript(prev => {
          const newTranscript = prev + ' ' + data.transcript;
          return newTranscript.trim();
        });
        setMessages(prev => [...prev, {
          segment_id: data.segment_id,
          text: data.transcript,
          timestamp: data.timestamp || new Date().toISOString(),
          speaker: data.speaker || null,
          speakerConfidence: data.speaker_confidence || 0
        }]);
        break;
        
      case 'speaker_tagged':
        console.log('🏷️ Speaker tagged:', data.speaker_id, '→', data.role);
        break;

      case 'speaker_corrected':
        console.log('✏️ Speaker corrected:', data.segment_id, '→', data.corrected_speaker);
        break;
        
      case 'session_ended':
        console.log('✅ Session ended:', data.data);
        setSessionActive(false);
        setIsRecording(false);
        setAudioPaused(false);
        isRecordingRef.current = false;
        audioPausedRef.current = false;
        alert('Session ended successfully. Processing in background...');
        break;

      // =============================================================
      // Phase 1, Step 9 — Content correction messages
      // =============================================================
      case 'correction_proposed': {
        const { correction_id, kind, target_segment_id, original_text, replacement_text, auto_commit_at, command_segment_id } = data;
        lastSeenCorrectionIdRef.current = correction_id;
        setPendingCorrections(prev => ({
          ...prev,
          [correction_id]: { correction_id, kind, target_segment_id, original_text, replacement_text, auto_commit_at, command_segment_id }
        }));
        setCorrectionsByTarget(prev => ({ ...prev, [target_segment_id]: correction_id }));
        break;
      }

      case 'correction_applied': {
        const { correction_id, kind, target_segment_id, original_text, replacement_text, confirmed_by, confirmation_timestamp } = data;
        lastSeenCorrectionIdRef.current = correction_id;
        // Move from pending to applied
        setPendingCorrections(prev => { const n = { ...prev }; delete n[correction_id]; return n; });
        setAppliedCorrections(prev => ({
          ...prev,
          [correction_id]: { correction_id, kind, target_segment_id, original_text, replacement_text, confirmed_by, confirmation_timestamp }
        }));
        setCorrectionsByTarget(prev => ({ ...prev, [target_segment_id]: correction_id }));
        break;
      }

      case 'correction_rejected': {
        const { correction_id, target_segment_id } = data;
        lastSeenCorrectionIdRef.current = correction_id;
        setPendingCorrections(prev => { const n = { ...prev }; delete n[correction_id]; return n; });
        setCorrectionsByTarget(prev => { const n = { ...prev }; if (n[target_segment_id] === correction_id) delete n[target_segment_id]; return n; });
        break;
      }

      case 'correction_reversed': {
        const { correction_id, reverses_correction_id, target_segment_id } = data;
        lastSeenCorrectionIdRef.current = correction_id;
        // Remove the reversed correction from applied
        setAppliedCorrections(prev => { const n = { ...prev }; delete n[reverses_correction_id]; return n; });
        setCorrectionsByTarget(prev => { const n = { ...prev }; if (n[target_segment_id] === reverses_correction_id) delete n[target_segment_id]; return n; });
        break;
      }

      case 'correction_failed':
        console.warn('⚠️ Correction failed:', data.reason, data.message);
        break;

      // Step 10: session resync response
      case 'session_state': {
        console.log('🔄 Session state resync received');
        // Rebuild local state from server
        if (data.segments) {
          setMessages(data.segments.map(seg => ({
            segment_id: seg.segment_id,
            text: seg.transcript,
            timestamp: seg.timestamp,
            speaker: seg.speaker_heuristic,
            speakerConfidence: seg.speaker_confidence || 0,
          })));
        }
        // Rebuild corrections state
        if (data.content_corrections) {
          const applied = {};
          const byTarget = {};
          for (const entry of data.content_corrections) {
            if (entry.kind === 'scratch' || entry.kind === 'replace') {
              applied[entry.correction_id] = entry;
              byTarget[entry.target_segment_id] = entry.correction_id;
            }
          }
          setAppliedCorrections(applied);
          setCorrectionsByTarget(prev => ({ ...prev, ...byTarget }));
        }
        if (data.pending_content_corrections) {
          const pending = {};
          for (const [cid, entry] of Object.entries(data.pending_content_corrections)) {
            pending[cid] = entry;
            setCorrectionsByTarget(prev => ({ ...prev, [entry.target_segment_id]: cid }));
          }
          setPendingCorrections(pending);
        }
        break;
      }

      case 'session_resync_failed':
        console.error('❌ Session resync failed:', data.reason);
        // Session is gone — reset
        setSessionActive(false);
        setIsRecording(false);
        alert('Session could not be recovered after reconnect. Please start a new session.');
        break;
        
      case 'error':
        console.error('❌ Server error:', data.message);
        break;
        
      default:
        console.log('ℹ️ Unknown message type:', data.type);
    }
  };
  
  // =====================================================================
  // Content correction actions (Step 9)
  // =====================================================================
  const acceptCorrection = (correctionId) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !sessionId) return;
    wsRef.current.send(JSON.stringify({
      type: 'content_correction_accept',
      session_id: sessionId,
      correction_id: correctionId,
      staff_username: user?.username || 'staff',
    }));
  };

  const rejectCorrection = (correctionId) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !sessionId) return;
    wsRef.current.send(JSON.stringify({
      type: 'content_correction_reject',
      session_id: sessionId,
      correction_id: correctionId,
      staff_username: user?.username || 'staff',
    }));
  };

  const undoCorrection = (correctionId) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !sessionId) return;
    wsRef.current.send(JSON.stringify({
      type: 'content_correction_reverse',
      session_id: sessionId,
      correction_id: correctionId,
      staff_username: user?.username || 'staff',
    }));
  };

  const pushScratch = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !sessionId) return;
    wsRef.current.send(JSON.stringify({
      type: 'content_correction_push',
      session_id: sessionId,
      kind: 'scratch',
      staff_username: user?.username || 'staff',
    }));
  };

  const pushReplace = (replacementText) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !sessionId || !replacementText) return;
    wsRef.current.send(JSON.stringify({
      type: 'content_correction_push',
      session_id: sessionId,
      kind: 'replace',
      replacement: replacementText,
      staff_username: user?.username || 'staff',
    }));
  };

  // =====================================================================
  // Keyboard shortcuts (Step 9 — push-to-command)
  // =====================================================================
  const [showReplaceInput, setShowReplaceInput] = useState(false);
  const replaceInputRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ignore when focus is in a text input/textarea
      const tag = document.activeElement?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

      // Ctrl+Shift+S → push scratch
      if (e.ctrlKey && e.shiftKey && e.key === 'S') {
        e.preventDefault();
        if (sessionActive) pushScratch();
      }
      // Ctrl+Shift+R → show replace input
      if (e.ctrlKey && e.shiftKey && e.key === 'R') {
        e.preventDefault();
        if (sessionActive) {
          setShowReplaceInput(true);
          setTimeout(() => replaceInputRef.current?.focus(), 50);
        }
      }
      // Escape → close replace input
      if (e.key === 'Escape') {
        setShowReplaceInput(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [sessionActive, sessionId]);

  const handleReplaceSubmit = (e) => {
    e.preventDefault();
    const text = replaceInputRef.current?.value?.trim();
    if (text) {
      pushReplace(text);
      replaceInputRef.current.value = '';
    }
    setShowReplaceInput(false);
  };

  // =====================================================================
  // Existing functionality (unchanged)
  // =====================================================================

  // Tag a speaker manually
  const tagSpeaker = (speakerId, role) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !sessionId) return;
    wsRef.current.send(JSON.stringify({
      type: 'tag_speaker',
      session_id: sessionId,
      speaker_id: speakerId,
      role: role
    }));
  };
  
  // Correct speaker for a specific segment
  const correctSpeaker = (segmentId, speaker) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !sessionId) return;
    wsRef.current.send(JSON.stringify({
      type: 'correct_speaker',
      session_id: sessionId,
      segment_id: segmentId,
      speaker: speaker
    }));
    setSpeakerCorrections(prev => ({ ...prev, [segmentId]: speaker }));
    setMessages(prev => prev.map(msg => 
      msg.segment_id === segmentId ? { ...msg, speaker: speaker } : msg
    ));
  };
  
  const pauseAudioRecording = () => { setAudioPaused(true); audioPausedRef.current = true; };
  const resumeAudioRecording = () => { setAudioPaused(false); audioPausedRef.current = false; };
  
  const startAudioRecording = async () => {
    try {
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      await audioContext.resume();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      streamRef.current = stream;
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (e) => {
        if (!isRecordingRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || audioPausedRef.current) return;
        const inputData = e.inputBuffer.getChannelData(0);
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        const base64Audio = btoa(String.fromCharCode.apply(null, new Uint8Array(pcmData.buffer)));
        try {
          wsRef.current.send(JSON.stringify({ type: 'audio_stream', session_id: sessionIdRef.current, audio_data: base64Audio, encoding: 'audio/wav', sample_rate: 16000 }));
        } catch (error) { console.error('❌ Error sending audio:', error); }
      };
      source.connect(processor);
      processor.connect(audioContext.destination);
      audioContextRef.current = audioContext;
      processorRef.current = processor;
    } catch (error) {
      console.error('❌ Error starting audio:', error);
      alert('Microphone access denied. Please allow microphone access and try again.');
      throw error;
    }
  };
  
  const stopAudioRecording = () => {
    if (streamRef.current) { streamRef.current.getTracks().forEach(track => track.stop()); streamRef.current = null; }
    if (processorRef.current) { processorRef.current.disconnect(); processorRef.current = null; }
    if (audioContextRef.current) { audioContextRef.current.close(); audioContextRef.current = null; }
  };
  
  const startSession = async () => {
    if (!wsRef.current || connectionStatus !== 'connected') { alert('Please wait for WebSocket connection'); return; }
    if (!caseMetadata.caseId) { alert('Please fill in Case / Matter ID before starting'); return; }
    setIsRecording(true); setAudioPaused(false); isRecordingRef.current = true; audioPausedRef.current = false;
    wsRef.current.send(JSON.stringify({
      type: 'start_session', username: user?.username || 'lawyer', case_id: caseMetadata.caseId,
      client_role: caseMetadata.clientRole, matter_type: caseMetadata.matterType,
      preferred_language: 'en-IN', processing_mode: 'transcribe'
    }));
    try { await startAudioRecording(); } catch (error) { setIsRecording(false); setAudioPaused(false); isRecordingRef.current = false; audioPausedRef.current = false; }
  };
  
  const endSession = () => {
    if (!sessionId) return;
    setIsEndingSession(true);
    stopAudioRecording();
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'end_session', session_id: sessionId, username: user?.username || 'lawyer' }));
    }
    setIsRecording(false); setAudioPaused(false); isRecordingRef.current = false; audioPausedRef.current = false; setIsEndingSession(false);
  };
  
  const saveTranscript = (editedTranscript) => {
    setTranscript(editedTranscript);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && sessionId) {
      wsRef.current.send(JSON.stringify({ type: 'update_transcript', session_id: sessionId, transcript: editedTranscript }));
    }
  };
  
  // Connect WebSocket on mount
  useEffect(() => {
    connectWebSocket();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) wsRef.current.close();
      stopAudioRecording();
    };
  }, [connectWebSocket]);
  
  return (
    <div className="min-h-screen bg-gray-50">
      <LegalHeader caseMetadata={caseMetadata} connectionStatus={connectionStatus} user={user} />
      
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {!sessionActive && (
          <LegalMetadataPanel metadata={caseMetadata} onChange={setCaseMetadata} disabled={sessionActive} />
        )}
        
        <LegalControlsPanel
          isRecording={isRecording} audioPaused={audioPaused} sessionActive={sessionActive}
          connectionStatus={connectionStatus} onStartSession={startSession} onStopSession={endSession}
          onPauseAudio={pauseAudioRecording} onResumeAudio={resumeAudioRecording} disabled={isEndingSession}
        />

        {/* Push-to-command replace input overlay */}
        {showReplaceInput && (
          <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center" onClick={() => setShowReplaceInput(false)}>
            <form onSubmit={handleReplaceSubmit} onClick={e => e.stopPropagation()} className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg">
              <label className="block text-sm font-medium text-gray-700 mb-2">Replace most recent lawyer statement with:</label>
              <input ref={replaceInputRef} type="text" className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500" placeholder="Type replacement text and press Enter..." autoFocus />
              <div className="flex justify-end gap-2 mt-3">
                <button type="button" onClick={() => setShowReplaceInput(false)} className="px-3 py-1 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
                <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">Replace</button>
              </div>
            </form>
          </div>
        )}
        
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <LegalTranscriptPanel
              messages={messages}
              transcript={transcript}
              isEditing={isEditingTranscript}
              onToggleEdit={() => setIsEditingTranscript(!isEditingTranscript)}
              onSave={saveTranscript}
              onCorrectSpeaker={correctSpeaker}
              clientRole={caseMetadata.clientRole}
              sessionActive={sessionActive}
              pendingCorrections={pendingCorrections}
              appliedCorrections={appliedCorrections}
              correctionsByTarget={correctionsByTarget}
              onAcceptCorrection={acceptCorrection}
              onRejectCorrection={rejectCorrection}
              onUndoCorrection={undoCorrection}
            />
          </div>
          
          <div className="space-y-6">
            <LegalExportService transcript={transcript} messages={messages} caseMetadata={caseMetadata} sessionId={sessionId} />
          </div>
        </div>
        
        {/* Debug Info (Development Only) */}
        {process.env.NODE_ENV === 'development' && (
          <div className="bg-gray-800 text-white p-4 rounded-lg text-xs font-mono space-y-1">
            <p>Session ID: {sessionId || 'None'} | Connection: {connectionStatus} | Recording: {isRecording ? 'Yes' : 'No'}</p>
            <p>Messages: {messages.length} | Speaker corrections: {Object.keys(speakerCorrections).length}</p>
            <p>Pending corrections: {Object.keys(pendingCorrections).length} | Applied corrections: {Object.keys(appliedCorrections).length}</p>
            <p className="text-gray-400">Shortcuts: Ctrl+Shift+S = scratch last | Ctrl+Shift+R = replace last</p>
          </div>
        )}
      </div>
    </div>
  );
}
