from typing import Dict, Optional


def identify_speaker(transcript: str, session_context: Optional[Dict] = None) -> Dict:
    """
    Identify speaker from transcript content (Lawyer-Client consultation context).

    Uses keyword heuristics to guess whether the speaker is the Lawyer or the Client.
    Manual speaker tags (from session_context) always take precedence over heuristics.

    Args:
        transcript: The text segment to analyze
        session_context: Optional dict with 'speaker_tags' and 'client_role'

    Returns:
        Dict with 'speaker' and 'confidence' keys
    """
    # If manual tags are available and mapped, use them directly
    if session_context and session_context.get("speaker_tags"):
        # Manual tags are handled at a higher level (by segment_id)
        # This function only does heuristic fallback
        pass

    text = transcript.lower()

    # Lawyer indicators - advisory language, legal references, procedural guidance
    lawyer_indicators = [
        'under the law', 'my advice would be', 'your rights are',
        'legally speaking', 'in my professional opinion', 'i recommend',
        'the statute says', 'according to the act', 'your options are',
        'we can file', 'i will draft', 'the court may', 'let me explain',
        'from a legal standpoint', 'the precedent is', 'section',
        'as your counsel', 'i advise', 'the liability', 'jurisdiction',
        'we should consider', 'the opposing party', 'your claim',
        'the contract states', 'breach of', 'damages', 'compensation',
        'i have reviewed', 'based on the evidence', 'discovery',
        'deposition', 'affidavit', 'settlement', 'litigation',
        'let me walk you through', 'the next step would be'
    ]

    if any(indicator in text for indicator in lawyer_indicators):
        return {'speaker': 'LAWYER', 'confidence': 0.75}

    # Client indicators - personal narrative, questions about process, emotional language
    client_indicators = [
        'what happened was', 'i was told', 'i want to file',
        'they did this to me', 'i signed', 'i received a notice',
        'can i sue', 'what are my options', 'how long will this take',
        'i don\'t understand', 'what does that mean', 'is that legal',
        'they promised me', 'i have proof', 'i was fired',
        'my landlord', 'my employer', 'my ex', 'the accident happened',
        'i was injured', 'i lost my', 'they owe me', 'i paid them',
        'what should i do', 'can they do that', 'is this normal',
        'i\'m worried about', 'how much will it cost', 'will i win',
        'the other side', 'they threatened', 'i have documents',
        'when i called them', 'they refused to', 'i want justice'
    ]

    if any(indicator in text for indicator in client_indicators):
        return {'speaker': 'CLIENT', 'confidence': 0.65}

    # Default to generic SPEAKER for neutral/unclear content
    return {'speaker': 'SPEAKER', 'confidence': 0.3}


def get_role_description(speaker_code: str) -> str:
    """
    Get human-readable description of speaker role.

    Args:
        speaker_code: Speaker identifier (e.g., 'LAWYER', 'PLAINTIFF', 'DEFENDANT')

    Returns:
        Human-readable description
    """
    descriptions = {
        'LAWYER': 'Attorney/Counsel',
        'PLAINTIFF': 'Plaintiff (Client)',
        'DEFENDANT': 'Defendant (Client)',
        'CLIENT': 'Client',
        'SPEAKER': 'Unidentified Speaker'
    }

    return descriptions.get(speaker_code.upper(), 'Unknown Speaker')
