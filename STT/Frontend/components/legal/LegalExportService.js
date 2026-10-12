import { Download, FileText } from 'lucide-react';
import { jsPDF } from 'jspdf';

export default function LegalExportService({ transcript, messages, caseMetadata, sessionId }) {
  
  // Build petition prose from the segments (no timestamps, no speaker labels),
  // grouping into paragraphs split at each paragraph-break marker. Paragraphs
  // are separated by a blank line ("\n\n"). Falls back to the raw transcript
  // string if there are no structured messages.
  const buildProse = () => {
    if (messages && messages.length > 0) {
      const paragraphs = [];
      let current = [];
      for (const msg of messages) {
        if (msg.isParagraphBreak) {
          if (current.length > 0) {
            paragraphs.push(current.join(' '));
            current = [];
          }
          continue;
        }
        const text = (msg.text || '').trim();
        if (text) current.push(text);
      }
      if (current.length > 0) paragraphs.push(current.join(' '));
      return paragraphs
        .map((p) => p.replace(/\s+/g, ' ').trim())
        .filter(Boolean)
        .map((p, i) => `${i + 1}. ${p}`)
        .join('\n\n');
    }
    return (transcript || '').replace(/[^\S\n]+/g, ' ').trim();
  };
  
  // Export as TXT
  const exportAsTXT = () => {
    if (!transcript || transcript.trim().length === 0) {
      alert('No transcript to export');
      return;
    }
    
    // Format as plain petition prose (lawyer-only, no timestamps/speakers)
    let content = '================================================================================\n';
    content += 'PETITION\n';
    content += '================================================================================\n\n';
    
    // Add metadata
    content += `Case / Matter ID: ${caseMetadata.caseId || 'N/A'}\n`;
    content += `Matter Type: ${(caseMetadata.matterType || 'consultation').replace(/_/g, ' ')}\n`;
    content += `Date: ${new Date(caseMetadata.date).toLocaleDateString()}\n`;
    content += `Session ID: ${sessionId || 'N/A'}\n\n`;
    content += '--------------------------------------------------------------------------------\n\n';
    
    // Continuous prose — join all segments into a single flowing body of text.
    content += buildProse() + '\n\n';
    
    content += '================================================================================\n';
    content += 'END OF PETITION\n';
    content += '================================================================================\n';
    
    // Create blob and download
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `legal_transcript_${caseMetadata.caseId || 'session'}_${Date.now()}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    
    console.log('✅ Transcript exported as TXT');
  };
  
  // Export as PDF
  const exportAsPDF = () => {
    if (!transcript || transcript.trim().length === 0) {
      alert('No transcript to export');
      return;
    }
    
    try {
      const doc = new jsPDF();
      const pageWidth = doc.internal.pageSize.getWidth();
      const pageHeight = doc.internal.pageSize.getHeight();
      const margin = 20;
      const lineHeight = 7;
      let yPosition = margin;
      
      // Helper function to add text with page breaks
      const addText = (text, fontSize = 10, isBold = false) => {
        doc.setFontSize(fontSize);
        if (isBold) {
          doc.setFont(undefined, 'bold');
        } else {
          doc.setFont(undefined, 'normal');
        }
        
        const lines = doc.splitTextToSize(text, pageWidth - 2 * margin);
        lines.forEach((line) => {
          if (yPosition + lineHeight > pageHeight - margin) {
            doc.addPage();
            yPosition = margin;
          }
          doc.text(line, margin, yPosition);
          yPosition += lineHeight;
        });
      };
      
      // Title
      doc.setFontSize(18);
      doc.setFont(undefined, 'bold');
      doc.text('PETITION', pageWidth / 2, yPosition, { align: 'center' });
      yPosition += 15;
      
      // Metadata
      doc.setFontSize(10);
      doc.setFont(undefined, 'normal');
      addText(`Case / Matter ID: ${caseMetadata.caseId || 'N/A'}`);
      addText(`Matter Type: ${(caseMetadata.matterType || 'consultation').replace(/_/g, ' ')}`);
      addText(`Date: ${new Date(caseMetadata.date).toLocaleDateString()}`);
      addText(`Session ID: ${sessionId || 'N/A'}`);
      yPosition += 5;
      
      // Separator
      doc.line(margin, yPosition, pageWidth - margin, yPosition);
      yPosition += 10;
      
      // Continuous petition prose — no timestamps, no speaker labels.
      addText(buildProse());
      
      // Footer on last page
      yPosition += 10;
      doc.line(margin, yPosition, pageWidth - margin, yPosition);
      yPosition += 10;
      doc.setFontSize(12);
      doc.setFont(undefined, 'bold');
      doc.text('END OF PETITION', pageWidth / 2, yPosition, { align: 'center' });
      
      // Save PDF
      doc.save(`legal_transcript_${caseMetadata.caseId || 'session'}_${Date.now()}.pdf`);
      
      console.log('✅ Transcript exported as PDF');
    } catch (error) {
      console.error('❌ Error exporting PDF:', error);
      alert('Error exporting PDF. Please try TXT export instead.');
    }
  };
  
  const hasContent = transcript && transcript.trim().length > 0;
  
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        {/* Title + note */}
        <div className="flex items-center gap-2">
          <Download className="w-5 h-5 text-gray-700" />
          <div>
            <h3 className="text-base font-bold leading-tight">Export Transcript</h3>
            <p className="text-xs text-gray-500">
              {hasContent
                ? 'Exports the petition as continuous prose along with case metadata.'
                : 'No transcript available to export yet.'}
            </p>
          </div>
        </div>

        {/* Action buttons — inline, right-aligned on wider screens */}
        <div className="flex gap-3">
          <button
            onClick={exportAsTXT}
            disabled={!hasContent}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg font-medium flex items-center justify-center gap-2 transition-colors"
          >
            <FileText className="w-4 h-4" />
            <span>Export as TXT</span>
          </button>

          <button
            onClick={exportAsPDF}
            disabled={!hasContent}
            className="bg-green-600 hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg font-medium flex items-center justify-center gap-2 transition-colors"
          >
            <FileText className="w-4 h-4" />
            <span>Export as PDF</span>
          </button>
        </div>
      </div>
    </div>
  );
}
