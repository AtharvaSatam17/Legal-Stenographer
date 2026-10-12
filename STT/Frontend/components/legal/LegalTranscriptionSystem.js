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

      case 'paragraph_break':
        console.log('↵ Paragraph break');
        // Push a lightweight marker so the display and export start a new
        // paragraph here. The command text itself is never shown.
        setMessages(prev => [...prev, {
          segment_id: data.segment_id,
          isParagraphBreak: true,
        }]);
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

      // Step 10: session resync response
      case 'session_state': {
        console.log('🔄 Session state resync received');
        // Rebuild local state from server. Paragraph-break markers are
        // preserved so the display re-groups into paragraphs after reconnect.
        if (data.segments) {
          setMessages(data.segments.map(seg => (
            seg.is_paragraph_break
              ? { segment_id: seg.segment_id, isParagraphBreak: true }
              : {
                  segment_id: seg.segment_id,
                  text: seg.transcript,
                  timestamp: seg.timestamp,
                  speaker: seg.speaker_heuristic,
                  speakerConfidence: seg.speaker_confidence || 0,
                }
          )));
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
  // Existing functionality
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
  
  // Receives an ordered array of paragraph strings from the edit panel.
  // Rebuilds the local messages array (one content segment per paragraph,
  // with break markers between them) so the paragraph display and export
  // reflect the edit immediately, and sends the structured paragraphs to the
  // backend so the final petition prose matches.
  const saveTranscript = (paragraphs) => {
    const paras = Array.isArray(paragraphs) ? paragraphs : [];

    // Rebuild messages: content segment, then a break marker before each
    // subsequent paragraph.
    const rebuilt = [];
    paras.forEach((text, i) => {
      if (i > 0) rebuilt.push({ segment_id: `edit_break_${i}`, isParagraphBreak: true });
      rebuilt.push({
        segment_id: `edit_seg_${i}`,
        text,
        timestamp: new Date().toISOString(),
        speaker: null,
        speakerConfidence: 0,
      });
    });
    setMessages(rebuilt);
    setTranscript(paras.join(' ').replace(/\s+/g, ' ').trim());

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && sessionId) {
      wsRef.current.send(JSON.stringify({
        type: 'update_transcript',
        session_id: sessionId,
        paragraphs: paras,
      }));
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
        
        {/* Export toolbar — placed up top alongside the controls, not in a sidebar */}
        <LegalExportService transcript={transcript} messages={messages} caseMetadata={caseMetadata} sessionId={sessionId} />

        <LegalTranscriptPanel
          messages={messages}
          transcript={transcript}
          isEditing={isEditingTranscript}
          onToggleEdit={() => setIsEditingTranscript(!isEditingTranscript)}
          onSave={saveTranscript}
        />
        
        {/* Debug Info (Development Only) */}
        {process.env.NODE_ENV === 'development' && (
          <div className="bg-gray-800 text-white p-4 rounded-lg text-xs font-mono space-y-1">
            <p>Session ID: {sessionId || 'None'} | Connection: {connectionStatus} | Recording: {isRecording ? 'Yes' : 'No'}</p>
            <p>Messages: {messages.length} | Speaker corrections: {Object.keys(speakerCorrections).length}</p>
          </div>
        )}
      </div>
    </div>
  );
}
