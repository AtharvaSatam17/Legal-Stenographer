import { Wifi, WifiOff } from 'lucide-react';

export default function LegalHeader({ caseMetadata, connectionStatus, user }) {
  const clientLabel = caseMetadata.clientRole === 'defendant' ? 'Defendant' : 'Plaintiff';

  return (
    <header className="bg-gradient-to-r from-blue-900 to-blue-700 text-white p-6 shadow-lg">
      <div className="max-w-7xl mx-auto">
        {/* Top Row: System Title & User */}
        <div className="flex justify-between items-center mb-4">
          <div>
            <h1 className="text-3xl font-bold">⚖️ Legal Stenographer</h1>
            <p className="text-blue-200 text-sm">Lawyer–Client Consultation Recorder</p>
          </div>
          
          <div className="flex items-center space-x-4">
            {/* Connection Status */}
            <div className="flex items-center space-x-2">
              {connectionStatus === 'connected' ? (
                <>
                  <Wifi className="w-5 h-5 text-green-300" />
                  <span className="text-sm">Connected</span>
                </>
              ) : connectionStatus === 'error' ? (
                <>
                  <WifiOff className="w-5 h-5 text-red-300" />
                  <span className="text-sm">Error</span>
                </>
              ) : (
                <>
                  <WifiOff className="w-5 h-5 text-yellow-300" />
                  <span className="text-sm">Connecting...</span>
                </>
              )}
            </div>
            
            {/* User Info */}
            <div className="text-right">
              <p className="font-medium">{user?.name || user?.username || 'Lawyer'}</p>
              <p className="text-xs text-blue-200">Attorney</p>
            </div>
          </div>
        </div>
        
        {/* Bottom Row: Case Metadata */}
        <div className="bg-blue-800/50 rounded-lg p-4 grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs text-blue-200">Case / Matter ID</p>
            <p className="font-semibold">{caseMetadata.caseId || 'Not Set'}</p>
          </div>
          <div>
            <p className="text-xs text-blue-200">Client Role</p>
            <p className="font-semibold">{clientLabel}</p>
          </div>
          <div>
            <p className="text-xs text-blue-200">Matter Type</p>
            <p className="font-semibold capitalize">{caseMetadata.matterType?.replace(/_/g, ' ') || 'Consultation'}</p>
          </div>
        </div>
      </div>
    </header>
  );
}
