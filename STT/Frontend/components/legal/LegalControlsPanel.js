import { Mic, MicOff, Square, Radio, Play, Pause } from 'lucide-react';

export default function LegalControlsPanel({
  isRecording,
  audioPaused,
  sessionActive,
  connectionStatus,
  onStartSession,
  onStopSession,
  onPauseAudio,
  onResumeAudio,
  disabled
}) {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-xl font-bold mb-4">Recording Controls</h3>
      
      {/* Status Indicators */}
      <div className="flex items-center space-x-4 mb-6">
        {/* Recording Status */}
        <div className={`flex items-center space-x-2 px-4 py-2 rounded-full ${
          isRecording && !audioPaused
            ? 'bg-red-100 text-red-700'
            : audioPaused 
            ? 'bg-yellow-100 text-yellow-700'
            : 'bg-gray-100 text-gray-600'
        }`}>
          {isRecording && !audioPaused ? (
            <>
              <Radio className="w-5 h-5 animate-pulse" />
              <span className="font-medium">RECORDING</span>
            </>
          ) : audioPaused ? (
            <>
              <Pause className="w-5 h-5" />
              <span className="font-medium">PAUSED</span>
            </>
          ) : (
            <>
              <MicOff className="w-5 h-5" />
              <span>Not Recording</span>
            </>
          )}
        </div>
        
        {/* Session Status */}
        {sessionActive && (
          <div className="flex items-center space-x-2 px-4 py-2 rounded-full bg-green-100 text-green-700">
            <Mic className="w-5 h-5" />
            <span className="font-medium">Session Active</span>
          </div>
        )}
      </div>
      
      {/* Control Buttons */}
      <div className="flex space-x-4">
        {!sessionActive ? (
          <button
            onClick={onStartSession}
            disabled={disabled || connectionStatus !== 'connected'}
            className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
          >
            <Mic className="w-5 h-5" />
            <span>Start Session</span>
          </button>
        ) : (
          <>
            {/* Pause/Resume Button */}
            {audioPaused ? (
              <button
                onClick={onResumeAudio}
                disabled={disabled}
                className="flex-1 bg-green-600 hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
              >
                <Play className="w-5 h-5" />
                <span>Resume Audio</span>
              </button>
            ) : (
              <button
                onClick={onPauseAudio}
                disabled={disabled}
                className="flex-1 bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
              >
                <Pause className="w-5 h-5" />
                <span>Pause Audio</span>
              </button>
            )}
            
            {/* End Session Button */}
            <button
              onClick={onStopSession}
              disabled={disabled}
              className="flex-1 bg-red-600 hover:bg-red-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors"
            >
              <Square className="w-5 h-5" />
              <span>End Session</span>
            </button>
          </>
        )}
      </div>
      
      {/* Connection Warning */}
      {connectionStatus !== 'connected' && (
        <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
          <p className="text-yellow-800 text-sm">
            ⚠️ {connectionStatus === 'error' 
              ? 'WebSocket connection error. Please check backend.' 
              : 'Connecting to backend... Please wait.'}
          </p>
        </div>
      )}
      
      {/* Instructions */}
      {!sessionActive && connectionStatus === 'connected' && (
        <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-blue-800 text-sm">
            ℹ️ Fill in case information above, then click &ldquo;Start Session&rdquo; to begin recording.
          </p>
        </div>
      )}
      
      {/* Pause/Resume Instructions */}
      {sessionActive && (
        <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
          <p className="text-green-800 text-sm">
            💡 <strong>Tip:</strong> Use &ldquo;Pause Audio&rdquo; to stop transcription during breaks or off-record discussions. 
            Click &ldquo;Resume Audio&rdquo; to continue. You can pause and resume unlimited times during the session.
          </p>
        </div>
      )}
    </div>
  );
}
