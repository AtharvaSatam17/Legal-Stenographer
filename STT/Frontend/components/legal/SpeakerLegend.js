import { Users } from 'lucide-react';

export default function SpeakerLegend({ speakerMapping, clientRole = 'plaintiff' }) {
  const clientLabel = clientRole === 'defendant' ? 'DEFENDANT' : 'PLAINTIFF';
  const clientDescription = clientRole === 'defendant' 
    ? 'Defendant (Client)' 
    : 'Plaintiff (Client)';

  const speakers = [
    { 
      role: 'LAWYER', 
      color: 'bg-blue-500', 
      textColor: 'text-blue-700',
      bgColor: 'bg-blue-50',
      description: 'Attorney / Counsel' 
    },
    { 
      role: clientLabel, 
      color: 'bg-amber-500', 
      textColor: 'text-amber-700',
      bgColor: 'bg-amber-50',
      description: clientDescription 
    },
  ];
  
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-bold mb-4 flex items-center">
        <Users className="w-5 h-5 mr-2" />
        Speaker Legend
      </h3>
      
      <div className="space-y-4">
        {speakers.map((speaker) => (
          <div key={speaker.role} className="flex items-start space-x-3">
            <div className={`w-4 h-4 rounded-full ${speaker.color} flex-shrink-0 mt-1`} />
            <div className="flex-1">
              <div className={`inline-block px-3 py-1 rounded-full text-xs font-medium mb-1 ${speaker.textColor} ${speaker.bgColor}`}>
                {speaker.role}
              </div>
              <p className="text-sm text-gray-600">{speaker.description}</p>
            </div>
          </div>
        ))}
      </div>
      
      <div className="mt-6 pt-4 border-t border-gray-200">
        <p className="text-xs text-gray-500">
          ℹ️ Speaker identification uses keyword heuristics during recording and AI diarization after the session ends.
        </p>
      </div>
      
      <div className="mt-4 p-3 bg-blue-50 rounded-lg">
        <p className="text-xs text-blue-800">
          <strong>Tip:</strong> You can manually tag speakers or correct assignments per segment using the controls below the transcript.
        </p>
      </div>
    </div>
  );
}
