import { FileText } from 'lucide-react';

export default function LegalMetadataPanel({ metadata, onChange, disabled }) {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-xl font-bold mb-4 flex items-center">
        <FileText className="w-5 h-5 mr-2" />
        Consultation Information
      </h3>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Case ID */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Case / Matter ID <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={metadata.caseId}
            onChange={(e) => onChange({ ...metadata, caseId: e.target.value })}
            disabled={disabled}
            placeholder="e.g., CASE-2024-001"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
            required
          />
        </div>
        
        {/* Client Role */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Client Role <span className="text-red-500">*</span>
          </label>
          <select
            value={metadata.clientRole}
            onChange={(e) => onChange({ ...metadata, clientRole: e.target.value })}
            disabled={disabled}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
          >
            <option value="plaintiff">Plaintiff</option>
            <option value="defendant">Defendant</option>
          </select>
          <p className="text-xs text-gray-500 mt-1">
            Is the client the Plaintiff or Defendant in this matter?
          </p>
        </div>
        
        {/* Matter Type */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Matter Type
          </label>
          <select
            value={metadata.matterType}
            onChange={(e) => onChange({ ...metadata, matterType: e.target.value })}
            disabled={disabled}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
          >
            <option value="consultation">Initial Consultation</option>
            <option value="follow_up">Follow-up Meeting</option>
            <option value="case_review">Case Review</option>
            <option value="settlement_discussion">Settlement Discussion</option>
            <option value="witness_prep">Witness Preparation</option>
          </select>
        </div>
        
        {/* Date */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Date
          </label>
          <input
            type="date"
            value={metadata.date?.split('T')[0]}
            onChange={(e) => onChange({ ...metadata, date: new Date(e.target.value).toISOString() })}
            disabled={disabled}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
        </div>
      </div>
      
      <p className="text-sm text-gray-500 mt-4">
        <span className="text-red-500">*</span> Required fields must be filled before starting a session
      </p>
    </div>
  );
}
