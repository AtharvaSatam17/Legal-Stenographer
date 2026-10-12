import { useState, useEffect, useRef } from 'react';
import { Edit, Save } from 'lucide-react';

export default function LegalTranscriptPanel({
  messages,
  transcript,
  isEditing,
  onToggleEdit,
  onSave,
}) {
  const [editedText, setEditedText] = useState('');
  const messagesEndRef = useRef(null);

  // Group messages into paragraphs, splitting at each paragraph-break marker.
  // Each paragraph is an array of segment text strings.
  const buildParagraphs = () => {
    const paragraphs = [];
    let current = [];
    for (const msg of messages) {
      if (msg.isParagraphBreak) {
        if (current.length > 0) {
          paragraphs.push(current);
          current = [];
        }
        continue;
      }
      if (msg.text) current.push(msg.text);
    }
    if (current.length > 0) paragraphs.push(current);
    return paragraphs;
  };

  // Build the numbered, editable text form: "1. <para>\n\n2. <para>" ...
  const buildEditableText = () =>
    buildParagraphs()
      .map((p) => p.join(' ').replace(/\s+/g, ' ').trim())
      .filter(Boolean)
      .map((p, i) => `${i + 1}. ${p}`)
      .join('\n\n');

  // When entering edit mode, seed the textarea from the current paragraphs.
  useEffect(() => {
    if (isEditing) setEditedText(buildEditableText());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Parse the edited text back into an ordered array of paragraph strings.
  // Paragraphs are separated by blank lines; any leading "N." numbering the
  // user left in place is stripped (numbering is always re-derived on render).
  const parseEditedParagraphs = (text) =>
    text
      .split(/\n\s*\n+/)
      .map((block) => block.replace(/\s+/g, ' ').trim())
      .map((block) => block.replace(/^\d+\.\s*/, '').trim())
      .filter(Boolean);

  const handleSave = () => {
    onSave(parseEditedParagraphs(editedText));
    onToggleEdit();
  };

  // Number of actual content segments (break markers excluded).
  const contentSegmentCount = messages.filter((m) => !m.isParagraphBreak).length;

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
              value={editedText}
              onChange={(e) => setEditedText(e.target.value)}
              className="w-full h-96 p-4 border border-gray-300 rounded-lg font-mono text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Edit transcript here..."
            />
            <p className="text-sm text-gray-500 mt-2">
              Each numbered block is one paragraph. Separate paragraphs with a blank line to split them,
              or remove the blank line to merge. Numbering is applied automatically on save.
            </p>
          </div>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            {contentSegmentCount === 0 ? (
              <div className="text-center py-12">
                <p className="text-gray-400 text-lg mb-2">No transcript yet</p>
                <p className="text-gray-500 text-sm">Transcript will appear here once recording starts...</p>
              </div>
            ) : (
              <div className="text-gray-800 leading-loose text-justify text-[15px]">
                {buildParagraphs().map((paragraph, idx) => (
                  <p key={idx} className="mb-4 last:mb-0">
                    <span className="font-semibold text-gray-900 mr-1">{idx + 1}.</span>
                    {paragraph.join(' ')}
                  </p>
                ))}
                <span ref={messagesEndRef} />
              </div>
            )}
          </div>
        )}
      </div>
      
      {/* Footer Stats */}
      {contentSegmentCount > 0 && !isEditing && (
        <div className="border-t p-4 bg-gray-50">
          <div className="flex justify-between text-sm text-gray-600">
            <span>{contentSegmentCount} segments</span>
            <span>{transcript.split(' ').filter(Boolean).length} words</span>
          </div>
        </div>
      )}
    </div>
  );
}
