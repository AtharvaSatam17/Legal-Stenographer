/**
 * CorrectionOverlay.js — Phase 1, Step 9
 *
 * Presentational component rendering per-segment correction states:
 *   - clean: renders children normally
 *   - pending: strike-through original + inline proposed replacement +
 *              Accept/Reject buttons + countdown to auto-commit
 *   - applied: replacement text shown as primary, small "edited" badge,
 *              hover reveals original + confirmed_by + timestamp + Undo button
 */

import { useState } from 'react';
import { Check, X, Undo2, Clock } from 'lucide-react';

export default function CorrectionOverlay({
  originalText,
  pendingCorrection,   // null or {correction_id, kind, replacement_text, auto_commit_at}
  appliedCorrection,   // null or {correction_id, kind, replacement_text, confirmed_by, confirmation_timestamp, original_text}
  onAccept,            // (correction_id) => void
  onReject,            // (correction_id) => void
  onUndo,              // (correction_id) => void
  children,            // default content render
  inline = false,      // render applied corrections inline (prose flow)
}) {
  const [showDetails, setShowDetails] = useState(false);

  // --- PENDING STATE ---
  if (pendingCorrection) {
    const { correction_id, kind, replacement_text, auto_commit_at } = pendingCorrection;
    const timeLeft = auto_commit_at
      ? Math.max(0, Math.round((new Date(auto_commit_at) - Date.now()) / 1000))
      : 10;

    return (
      <div className="border-2 border-yellow-300 bg-yellow-50 rounded-lg p-3 space-y-2">
        {/* Original text with strike-through */}
        <div className="flex items-start gap-2">
          <span className="text-xs font-medium text-yellow-700 bg-yellow-200 px-2 py-0.5 rounded">
            {kind === 'scratch' ? 'SCRATCH' : 'REPLACE'}
          </span>
          <span className="line-through text-gray-500 text-sm flex-1">{originalText}</span>
        </div>

        {/* Proposed replacement (if replace) */}
        {kind === 'replace' && replacement_text && (
          <div className="pl-4 border-l-2 border-green-400">
            <p className="text-green-800 text-sm font-medium">→ {replacement_text}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={() => onAccept(correction_id)}
            className="flex items-center gap-1 px-3 py-1 bg-green-600 hover:bg-green-700 text-white text-xs font-medium rounded transition-colors"
          >
            <Check className="w-3 h-3" /> Accept
          </button>
          <button
            onClick={() => onReject(correction_id)}
            className="flex items-center gap-1 px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-xs font-medium rounded transition-colors"
          >
            <X className="w-3 h-3" /> Reject
          </button>
          <span className="flex items-center gap-1 text-xs text-gray-500 ml-auto">
            <Clock className="w-3 h-3" />
            Auto-commit in {timeLeft}s
          </span>
        </div>
      </div>
    );
  }

  // --- APPLIED STATE ---
  if (appliedCorrection) {
    const { correction_id, kind, replacement_text, confirmed_by, confirmation_timestamp, original_text: origText } = appliedCorrection;

    // Inline mode: render the corrected text as part of the flowing prose.
    if (inline) {
      if (kind === 'scratch') {
        // Scratched content is removed from the petition text entirely.
        return null;
      }
      return (
        <span
          className="text-gray-800 hover:bg-purple-50 rounded cursor-pointer transition-colors"
          title={`Edited from: "${origText || originalText}" by ${confirmed_by || 'user'}`}
          onClick={() => onUndo && onUndo(correction_id)}
        >
          {replacement_text}
        </span>
      );
    }

    return (
      <div className="relative group">
        {/* Main content */}
        <div
          className="flex items-start gap-2 cursor-pointer"
          onClick={() => setShowDetails(!showDetails)}
        >
          {kind === 'scratch' ? (
            <span className="line-through text-gray-400 text-sm italic">{origText || originalText}</span>
          ) : (
            <span className="text-gray-800">{replacement_text}</span>
          )}
          <span className="flex-shrink-0 text-xs font-medium text-purple-700 bg-purple-100 px-1.5 py-0.5 rounded">
            edited
          </span>
        </div>

        {/* Details on click */}
        {showDetails && (
          <div className="mt-2 p-3 bg-gray-100 rounded-lg text-xs space-y-1 border border-gray-200">
            {kind === 'replace' && (
              <p><span className="font-medium">Original:</span> <span className="line-through text-gray-500">{origText || originalText}</span></p>
            )}
            <p><span className="font-medium">Confirmed by:</span> {confirmed_by}</p>
            <p><span className="font-medium">At:</span> {confirmation_timestamp ? new Date(confirmation_timestamp).toLocaleTimeString() : 'N/A'}</p>
            <button
              onClick={(e) => { e.stopPropagation(); onUndo(correction_id); }}
              className="flex items-center gap-1 px-2 py-1 bg-orange-500 hover:bg-orange-600 text-white text-xs font-medium rounded mt-2 transition-colors"
            >
              <Undo2 className="w-3 h-3" /> Undo
            </button>
          </div>
        )}
      </div>
    );
  }

  // --- CLEAN STATE ---
  return <>{children}</>;
}
