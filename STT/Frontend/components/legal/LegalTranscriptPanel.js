import { useState, useEffect, useRef } from 'react';
import { Edit, Save, X, ChevronUp, ChevronDown, ArrowUpToLine, Trash2, GripVertical, Sparkles, Loader2 } from 'lucide-react';

export default function LegalTranscriptPanel({
  messages,
  transcript,
  isEditing,
  onToggleEdit,
  onSave,
  onRequestAiDraft,
  registerAiDraftHandler,
}) {
  // Working copy of the paragraph list while editing (array of strings).
  const [draftParagraphs, setDraftParagraphs] = useState([]);
  // Index of the paragraph currently selected for editing (right pane).
  const [selectedIndex, setSelectedIndex] = useState(null);
  // Text in the right-pane editor for the selected paragraph.
  const [editorText, setEditorText] = useState('');
  const messagesEndRef = useRef(null);

  // AI drafting state
  const [aiInstruction, setAiInstruction] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState('');
  const aiRequestIdRef = useRef(null);

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

  // Flatten to an array of paragraph strings.
  const buildParagraphStrings = () =>
    buildParagraphs()
      .map((p) => p.join(' ').replace(/\s+/g, ' ').trim())
      .filter(Boolean);

  // When entering edit mode, snapshot the current paragraphs into the draft.
  useEffect(() => {
    if (isEditing) {
      setDraftParagraphs(buildParagraphStrings());
      setSelectedIndex(null);
      setEditorText('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing]);

  // Auto-scroll to bottom when new messages arrive (view mode only)
  useEffect(() => {
    if (!isEditing) messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isEditing]);

  const contentSegmentCount = messages.filter((m) => !m.isParagraphBreak).length;
  const viewParagraphs = buildParagraphs();

  // --- Edit interactions ------------------------------------------------

  // Commit the current right-pane text back into the draft list and return
  // the updated list (so switching/saving never loses an in-progress edit).
  const commitCurrentEdit = () => {
    if (selectedIndex === null) return draftParagraphs;
    const next = draftParagraphs.map((p, i) =>
      i === selectedIndex ? editorText.replace(/\s+/g, ' ').trim() : p
    );
    setDraftParagraphs(next);
    return next;
  };

  const selectParagraph = (idx) => {
    const next = commitCurrentEdit();
    setSelectedIndex(idx);
    setEditorText(next[idx] ?? '');
    setAiError('');
  };

  // --- AI drafting ------------------------------------------------------
  // Register a handler so the websocket layer can deliver results here.
  useEffect(() => {
    if (!registerAiDraftHandler) return;
    registerAiDraftHandler(({ request_id, draft, error, message }) => {
      // Ignore results for stale/superseded requests.
      if (request_id !== aiRequestIdRef.current) return;
      setAiLoading(false);
      aiRequestIdRef.current = null;
      if (error) {
        const map = {
          ai_unavailable: 'AI drafting is not configured on the server.',
          bedrock_error: 'The AI service failed. Please try again.',
          empty_instruction: 'Please enter an instruction first.',
          empty_paragraph: 'No paragraph text to draft from.',
          empty_result: 'The AI returned no text. Try rephrasing the instruction.',
        };
        setAiError(message || map[error] || 'AI drafting failed. Please try again.');
        return;
      }
      if (typeof draft === 'string' && draft.trim()) {
        setEditorText(draft.trim());
      }
    });
    return () => registerAiDraftHandler(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runAiDraft = () => {
    setAiError('');
    const instruction = aiInstruction.trim();
    if (!instruction) { setAiError('Please enter an instruction first.'); return; }
    if (selectedIndex === null || !editorText.trim()) {
      setAiError('Select a paragraph with text to draft from.');
      return;
    }
    const reqId = `ai_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    aiRequestIdRef.current = reqId;
    setAiLoading(true);
    const ok = onRequestAiDraft?.({
      request_id: reqId,
      paragraph: editorText,
      instruction,
    });
    if (!ok) {
      setAiLoading(false);
      aiRequestIdRef.current = null;
      setAiError('Not connected to the server. Please wait for the connection.');
    }
  };

  // Apply a reordered/edited list and keep the selection pointing at the
  // paragraph the user was working on (by its new index).
  const applyList = (list, newSelected) => {
    setDraftParagraphs(list);
    if (newSelected === null || newSelected < 0 || newSelected >= list.length) {
      setSelectedIndex(null);
      setEditorText('');
    } else {
      setSelectedIndex(newSelected);
      setEditorText(list[newSelected]);
    }
  };

  // Move a paragraph up or down one step.
  const moveParagraph = (idx, dir) => {
    const list = commitCurrentEdit();
    const target = idx + dir;
    if (target < 0 || target >= list.length) return;
    const next = [...list];
    [next[idx], next[target]] = [next[target], next[idx]];
    // Preserve selection: follow the moved paragraph if it was selected,
    // or the one that got displaced into idx.
    let sel = selectedIndex;
    if (selectedIndex === idx) sel = target;
    else if (selectedIndex === target) sel = idx;
    applyList(next, sel);
  };

  // Merge a paragraph into the one above it.
  const mergeUp = (idx) => {
    if (idx <= 0) return;
    const list = commitCurrentEdit();
    const next = [...list];
    next[idx - 1] = `${next[idx - 1]} ${next[idx]}`.replace(/\s+/g, ' ').trim();
    next.splice(idx, 1);
    // Selection follows the merged (upper) paragraph.
    applyList(next, idx - 1);
  };

  // Delete a paragraph.
  const deleteParagraph = (idx) => {
    const list = commitCurrentEdit();
    const next = [...list];
    next.splice(idx, 1);
    let sel = selectedIndex;
    if (selectedIndex === idx) sel = null;
    else if (selectedIndex !== null && selectedIndex > idx) sel = selectedIndex - 1;
    applyList(next, sel);
  };

  // --- Drag & drop reordering (native HTML5 DnD, no dependency) ----------
  const [dragIndex, setDragIndex] = useState(null);
  const [dragOverIndex, setDragOverIndex] = useState(null);

  const handleDragStart = (idx) => setDragIndex(idx);
  const handleDragOver = (e, idx) => {
    e.preventDefault();
    if (idx !== dragOverIndex) setDragOverIndex(idx);
  };
  const handleDrop = (e, idx) => {
    e.preventDefault();
    if (dragIndex === null || dragIndex === idx) {
      setDragIndex(null);
      setDragOverIndex(null);
      return;
    }
    const list = commitCurrentEdit();
    const next = [...list];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(idx, 0, moved);
    // Track selection across the move.
    let sel = selectedIndex;
    if (selectedIndex === dragIndex) {
      sel = idx;
    } else if (selectedIndex !== null) {
      // Adjust for the removal + insertion.
      let s = selectedIndex;
      if (dragIndex < s) s -= 1;
      if (idx <= s) s += 1;
      sel = s;
    }
    applyList(next, sel);
    setDragIndex(null);
    setDragOverIndex(null);
  };
  const handleDragEnd = () => {
    setDragIndex(null);
    setDragOverIndex(null);
  };

  // Save: fold in the active edit, then persist the WHOLE transcript
  // (all paragraphs) to the backend + display.
  const handleSaveAll = () => {
    const next = commitCurrentEdit();
    const paras = next.map((p) => p.replace(/\s+/g, ' ').trim()).filter(Boolean);
    onSave(paras);
    onToggleEdit();
  };

  const cancelEdit = () => {
    onToggleEdit();
  };

  return (
    <div className="bg-white rounded-lg shadow">
      {/* Header */}
      <div className="border-b p-4 flex justify-between items-center">
        <h3 className="text-xl font-bold">Live Transcript</h3>
        {isEditing ? (
          <div className="flex gap-2">
            <button
              onClick={cancelEdit}
              className="px-4 py-2 rounded-lg font-medium flex items-center space-x-2 bg-gray-200 hover:bg-gray-300 text-gray-700 transition-colors"
            >
              <X className="w-4 h-4" /><span>Cancel</span>
            </button>
            <button
              onClick={handleSaveAll}
              className="px-4 py-2 rounded-lg font-medium flex items-center space-x-2 bg-green-600 hover:bg-green-700 text-white transition-colors"
            >
              <Save className="w-4 h-4" /><span>Save</span>
            </button>
          </div>
        ) : (
          <button
            onClick={onToggleEdit}
            disabled={contentSegmentCount === 0}
            className="px-4 py-2 rounded-lg font-medium flex items-center space-x-2 bg-gray-200 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed text-gray-700 transition-colors"
          >
            <Edit className="w-4 h-4" /><span>Edit Transcript</span>
          </button>
        )}
      </div>

      {/* Body */}
      <div className="p-6">
        {!isEditing ? (
          /* ---------------- VIEW MODE ---------------- */
          <div className="max-h-96 overflow-y-auto">
            {contentSegmentCount === 0 ? (
              <div className="text-center py-12">
                <p className="text-gray-400 text-lg mb-2">No transcript yet</p>
                <p className="text-gray-500 text-sm">Transcript will appear here once recording starts...</p>
              </div>
            ) : (
              <div className="text-gray-800 leading-loose text-justify text-[15px]">
                {viewParagraphs.map((paragraph, idx) => (
                  <p key={idx} className="mb-4 last:mb-0">
                    <span className="font-semibold text-gray-900 mr-1">{idx + 1}.</span>
                    {paragraph.join(' ')}
                  </p>
                ))}
                <span ref={messagesEndRef} />
              </div>
            )}
          </div>
        ) : (
          /* ---------------- EDIT MODE (two columns) ---------------- */
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-start">
            {/* LEFT (wider): selectable + reorderable paragraph list */}
            <div className="lg:col-span-3 rounded-lg border border-gray-200 bg-gray-50 flex flex-col overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-200 bg-white">
                <h4 className="text-sm font-semibold text-gray-700">Paragraphs</h4>
                <p className="text-xs text-gray-500 mt-0.5">
                  Click to edit. Drag the handle or use arrows to reorder, merge up, or delete.
                </p>
              </div>
              <div className="max-h-[26rem] overflow-y-auto space-y-2 p-3">
                {draftParagraphs.length === 0 ? (
                  <p className="text-gray-400 text-sm py-8 text-center">No paragraphs to edit.</p>
                ) : (
                  draftParagraphs.map((para, idx) => (
                    <div
                      key={idx}
                      draggable
                      onDragStart={() => handleDragStart(idx)}
                      onDragOver={(e) => handleDragOver(e, idx)}
                      onDrop={(e) => handleDrop(e, idx)}
                      onDragEnd={handleDragEnd}
                      className={`flex items-start gap-2 p-2 rounded-lg border bg-white shadow-sm transition-colors ${
                        selectedIndex === idx
                          ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-400'
                          : 'border-gray-200 hover:border-gray-300'
                      } ${dragOverIndex === idx && dragIndex !== idx ? 'ring-2 ring-blue-300' : ''} ${
                        dragIndex === idx ? 'opacity-50' : ''
                      }`}
                    >
                      {/* Drag handle */}
                      <span
                        className="mt-1 text-gray-400 cursor-grab active:cursor-grabbing shrink-0"
                        title="Drag to reorder"
                      >
                        <GripVertical className="w-4 h-4" />
                      </span>

                      {/* Clickable text (selects for editing) */}
                      <button
                        onClick={() => selectParagraph(idx)}
                        className="flex-1 text-left text-[15px] leading-relaxed min-w-0"
                      >
                        <span className="font-semibold text-gray-900 mr-1">{idx + 1}.</span>
                        <span className="text-gray-800">{para}</span>
                      </button>

                      {/* Per-paragraph controls */}
                      <div className="flex flex-col items-center gap-0.5 shrink-0">
                        <div className="flex gap-0.5">
                          <button
                            onClick={() => moveParagraph(idx, -1)}
                            disabled={idx === 0}
                            title="Move up"
                            className="p-1 rounded text-gray-500 hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ChevronUp className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => moveParagraph(idx, 1)}
                            disabled={idx === draftParagraphs.length - 1}
                            title="Move down"
                            className="p-1 rounded text-gray-500 hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ChevronDown className="w-4 h-4" />
                          </button>
                        </div>
                        <div className="flex gap-0.5">
                          <button
                            onClick={() => mergeUp(idx)}
                            disabled={idx === 0}
                            title="Merge into paragraph above"
                            className="p-1 rounded text-gray-500 hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ArrowUpToLine className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => deleteParagraph(idx)}
                            title="Delete paragraph"
                            className="p-1 rounded text-red-500 hover:bg-red-50"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* RIGHT (narrower): editor for the selected paragraph */}
            <div className="lg:col-span-2 rounded-lg border border-gray-200 bg-white flex flex-col overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-200 bg-blue-50">
                <h4 className="text-sm font-semibold text-blue-800">
                  {selectedIndex === null ? 'Editor' : `Editing paragraph ${selectedIndex + 1}`}
                </h4>
              </div>
              <div className="p-4 flex-1">
                {selectedIndex === null ? (
                  <div className="min-h-[20rem] flex items-center justify-center">
                    <p className="text-gray-400 text-sm text-center px-4">
                      Select a paragraph on the left to edit it here.
                    </p>
                  </div>
                ) : (
                  <div>
                    <textarea
                      value={editorText}
                      onChange={(e) => setEditorText(e.target.value)}
                      className="w-full h-56 p-3 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="Edit this paragraph..."
                      autoFocus
                    />

                    {/* AI drafting */}
                    <div className="mt-3 border-t border-gray-200 pt-3">
                      <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
                        <Sparkles className="w-4 h-4 text-purple-600" />
                        Draft with AI
                      </label>
                      <textarea
                        value={aiInstruction}
                        onChange={(e) => setAiInstruction(e.target.value)}
                        className="w-full h-16 p-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                        placeholder="Instruction, e.g. &ldquo;make this more formal&rdquo; or &ldquo;rewrite as a petition statement&rdquo;"
                        disabled={aiLoading}
                      />
                      <button
                        onClick={runAiDraft}
                        disabled={aiLoading || !aiInstruction.trim()}
                        className="mt-2 w-full bg-purple-600 hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg font-medium flex items-center justify-center gap-2 transition-colors"
                      >
                        {aiLoading ? (
                          <><Loader2 className="w-4 h-4 animate-spin" /><span>Drafting...</span></>
                        ) : (
                          <><Sparkles className="w-4 h-4" /><span>Reframe this paragraph</span></>
                        )}
                      </button>
                      {aiError && (
                        <p className="text-xs text-red-600 mt-2">{aiError}</p>
                      )}
                      <p className="text-xs text-gray-500 mt-2">
                        AI replaces the text above for review. Nothing is saved until you click &ldquo;Save&rdquo;.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer Stats */}
      {contentSegmentCount > 0 && !isEditing && (
        <div className="border-t p-4 bg-gray-50">
          <div className="flex justify-between text-sm text-gray-600">
            <span>{viewParagraphs.length} paragraph{viewParagraphs.length === 1 ? '' : 's'}</span>
            <span>{transcript.split(' ').filter(Boolean).length} words</span>
          </div>
        </div>
      )}
    </div>
  );
}
