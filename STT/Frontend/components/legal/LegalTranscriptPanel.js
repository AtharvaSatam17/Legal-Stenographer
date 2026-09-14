import { useState, useEffect, useRef } from 'react';
import { Edit, Save, RefreshCw } from 'lucide-react';
import CorrectionOverlay from './CorrectionOverlay';

export default function LegalTranscriptPanel({
  messages,
  transcript,
  isEditing,
  onToggleEdit,
  onSave,
  onCorrectSpeaker,
  clientRole = 'plaintiff',
  sessionActive,
  // Phase 1, Step 9 — content correction props
  pendingCorrections = {},
  appliedCorrections = {},
  correctionsByTarget = {},
  onAcceptCorrection,
  onRejectCorrection,
  onUndoCorrection,
}) {
  const [editedTranscript, setEditedTranscript] = useState(transcript);
  const messagesEndRef = useRef(null);
  
  const clientLabel = clientRole === 'defendant' ? 'DEFENDANT' : 'PLAINTIFF';
  
  useEffect(() => {
    setEditedTranscript(transcript);
  }, [transcript]);
  
  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);
  
  // Speaker color mapping (2-party)
  const getSpeakerColor = (speaker) => {
    if (!speaker) return 'text-gray-700 bg-gray-50 border-gray-200';
    const s = speaker.toUpperCase();
    if (s === 'LAWYER') return 'text-blue-700 bg-blue-50 border-blue-200';
    if (s === 'PLAINTIFF' || s === 'DEFENDANT' || s === 'CLIENT') return 'text-amber-700 bg-amber-50 border-amber-200';
    if (s === 'SPEAKER_1') return 'text-blue-700 bg-blue-50 border-blue-200';
    if (s === 'SPEAKER_2') return 'text-amber-700 bg-amber-50 border-amber-200';
    return 'text-gray-700 bg-gray-50 border-gray-200';
  };
  
  const handleSave = () => {
    onSave(editedTranscript);
    onToggleEdit();
  };

  // Cycle speaker for a segment
  const cycleSpeaker = (segmentId, currentSpeaker) => {
    if (!onCorrectSpeaker || !sessionActive) return;
    const cycle = ['LAWYER', clientLabel, 'SPEAKER'];
    const currentIdx = cycle.indexOf(currentSpeaker?.toUpperCase());
    const nextIdx = (currentIdx + 1) % cycle.length;
    onCorrectSpeaker(segmentId, cycle[nextIdx]);
  };

  // Resolve correction state for a segment
  const getCorrectionForSegment = (segmentId) => {
    const corrId = correctionsByTarget[segmentId];
    if (!corrId) return { pending: null, applied: null };
    if (pendingCorrections[corrId]) return { pending: pendingCorrections[corrId], applied: null };
    if (appliedCorrections[corrId]) return { pending: null, applied: appliedCorrections[corrId] };
    return { pending: null, applied: null };
  };
  
  return (
    <div className="bg-white rounded-lg shadow">
      {/* Header */}
      <div className="border-b p-4 flex justify-between items-center">
        <h3 className="text-xl font-bold">Live Transcript</h3>
        <button
          onClick={isEditing ? handleSave : onToggleEdit}
          className={`px-4 py-2 rounded-lg font-medium flex items-center space-x-2 transition-colors ${
            isEditing 
              ? 'bg-green-600 hover:bg-green-700 text-white'
              : 'bg-gray-200 hover:bg-gray-300 text-gray-700'
          }`}
        >
          {isEditing ? (
            <><Save className="w-4 h-4" /><span>Save Changes</span></>
          ) : (
            <><Edit className="w-4 h-4" /><span>Edit Transcript</span></>
          )}
        </button>
      </div>
      
      {/* Transcript Display */}
      <div className="p-6">
        {isEditing ? (
          <div>
            <textarea
              value={editedTranscript}
              onChange={(e) => setEditedTranscript(e.target.value)}
              className="w-full h-96 p-4 border border-gray-300 rounded-lg font-mono text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Edit transcript here..."
            />
            <p className="text-sm text-gray-500 mt-2">
              Make manual corrections to the transcript. Click &ldquo;Save Changes&rdquo; when done.
            </p>
          </div>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            {messages.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-gray-400 text-lg mb-2">No transcript yet</p>
                <p className="text-gray-500 text-sm">Transcript will appear here once recording starts...</p>
              </div>
            ) : (
              <div className="text-gray-800 leading-loose text-justify text-[15px]">
                {messages.map((msg, idx) => {
                  const { pending, applied } = getCorrectionForSegment(msg.segment_id);

                  return (
                    <CorrectionOverlay
                      key={msg.segment_id || idx}
                      originalText={msg.text}
                      pendingCorrection={pending}
                      appliedCorrection={applied}
                      onAccept={onAcceptCorrection}
                      onReject={onRejectCorrection}
                      onUndo={onUndoCorrection}
                      inline
                    >
                      <span className="hover:bg-yellow-50 rounded transition-colors">
                        {msg.text}
                      </span>
                    </CorrectionOverlay>
                  );
                }).reduce((acc, el, idx) => {
                  // Join segments with a space so it reads as continuous prose
                  if (idx === 0) return [el];
                  return [...acc, ' ', el];
                }, [])}
                <span ref={messagesEndRef} />
              </div>
            )}
          </div>
        )}
      </div>
      
      {/* Footer Stats */}
      {messages.length > 0 && !isEditing && (
        <div className="border-t p-4 bg-gray-50">
          <div className="flex justify-between text-sm text-gray-600">
            <span>{messages.length} segments</span>
            <span>{transcript.split(' ').filter(Boolean).length} words</span>
            {sessionActive && (
              <span className="text-blue-600">Click speaker badge to correct | Ctrl+Shift+S = scratch | Ctrl+Shift+R = replace</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
