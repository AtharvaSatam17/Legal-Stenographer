# utils/language_utils.py

import re
from typing import Dict


class LanguageUtils:
    """
    Utility class for language detection based on Unicode script analysis.
    
    Note: This is now a FALLBACK mechanism. The primary source of language
    information is the Sarvam SDK's language_code field. This utility is
    only used when the SDK doesn't provide language information.
    """

    # Unicode ranges for Indian language scripts
    script_ranges = {
        'en-IN': (0x0000, 0x007F),  # Basic Latin (ASCII)
        'hi-IN': (0x0900, 0x097F),  # Devanagari (Hindi, Marathi, Sanskrit)
        'mr-IN': (0x0900, 0x097F),  # Devanagari (shared with Hindi)
        'te-IN': (0x0C00, 0x0C7F),  # Telugu
        'ta-IN': (0x0B80, 0x0BFF),  # Tamil
        'kn-IN': (0x0C80, 0x0CFF),  # Kannada
        'ml-IN': (0x0D00, 0x0D7F),  # Malayalam
        'bn-IN': (0x0980, 0x09FF),  # Bengali
        'gu-IN': (0x0A80, 0x0AFF),  # Gujarati
        'pa-IN': (0x0A00, 0x0A7F),  # Gurmukhi (Punjabi)
        'or-IN': (0x0B00, 0x0B7F),  # Odia
    }

    # Regex patterns for script detection (compiled for efficiency)
    script_patterns = {
        'en-IN': re.compile(r'[a-zA-Z]'),
        'hi-IN': re.compile(r'[\u0900-\u097F]'),
        'mr-IN': re.compile(r'[\u0900-\u097F]'),  # Same as Hindi (Devanagari)
        'te-IN': re.compile(r'[\u0C00-\u0C7F]'),
        'ta-IN': re.compile(r'[\u0B80-\u0BFF]'),
        'kn-IN': re.compile(r'[\u0C80-\u0CFF]'),
        'ml-IN': re.compile(r'[\u0D00-\u0D7F]'),
        'bn-IN': re.compile(r'[\u0980-\u09FF]'),
        'gu-IN': re.compile(r'[\u0A80-\u0AFF]'),
        'pa-IN': re.compile(r'[\u0A00-\u0A7F]'),
        'or-IN': re.compile(r'[\u0B00-\u0B7F]'),
    }

    # English words commonly transliterated into Telugu script
    english_in_telugu = [
        'ఆల్', 'రైట్', 'లెట్', 'మీ', 'స్టార్ట్', 'కన్వర్సేషన్', 'అగైన్',
        'జస్ట్', 'గెట్టింగ్', 'రెస్పాన్స్', 'ప్రాపర్లీ', 'డిటెక్ట్',
        'ఇంగ్లీష్', 'ఐయామ్', 'కైండ్', 'ఆఫ్', 'టేకింగ్', 'సమ్', 'టైమ్స్',
        'డూయింగ్', 'గుడ్', 'జాబ్', 'కాకపోతే', 'ఐ', 'సీ', 'లైక్', 'ది',
        'అవుట్పుట్', 'ఈజ్', 'ఇన్పుట్', 'సిస్టమ్', 'ప్రాబ్లమ్', 'సల్యూషన్',
        'ఫిక్స్', 'ఇష్యూ', 'రిజల్ట్', 'టెస్ట్', 'చెక్', 'వర్క్', 'ఫైన్', 'ఓకే'
    ]

    @staticmethod
    def detect_actual_language(text: str) -> str:
        """
        Detect language from script content by counting Unicode characters.
        
        This counts characters in each script's Unicode range and returns
        the language with the most characters. English (ASCII) is only
        returned if no other script is detected.
        
        Args:
            text: Text to analyze
        
        Returns:
            Language code (e.g., 'hi-IN', 'te-IN', 'en-IN')
        """
        if not text:
            return 'en-IN'

        # Count characters for each script
        script_counts: Dict[str, int] = {}
        
        for lang, pattern in LanguageUtils.script_patterns.items():
            # Skip English in first pass (we want to prefer non-English scripts)
            if lang == 'en-IN':
                continue
            # Skip mr-IN to avoid double-counting Devanagari (hi-IN covers it)
            if lang == 'mr-IN':
                continue
            
            matches = pattern.findall(text)
            count = len(matches)
            if count > 0:
                script_counts[lang] = count

        # If we found non-English scripts, return the one with most characters
        if script_counts:
            # Special case: Devanagari could be Hindi or Marathi
            # We return hi-IN by default, but this could be refined with lexical analysis
            detected_lang = max(script_counts.items(), key=lambda x: x[1])[0]
            return detected_lang

        # Fallback: count English characters
        english_count = len(LanguageUtils.script_patterns['en-IN'].findall(text))
        if english_count > 0:
            return 'en-IN'

        return 'unknown'

    @staticmethod
    def count_script_characters(text: str) -> Dict[str, int]:
        """
        Count characters from each script in the text.
        
        Useful for debugging and for code-mixed text analysis.
        
        Args:
            text: Text to analyze
        
        Returns:
            Dict mapping language codes to character counts
        """
        if not text:
            return {}

        counts: Dict[str, int] = {}
        
        for lang, pattern in LanguageUtils.script_patterns.items():
            # Skip mr-IN to avoid confusion (same range as hi-IN)
            if lang == 'mr-IN':
                continue
            
            matches = pattern.findall(text)
            count = len(matches)
            if count > 0:
                counts[lang] = count

        return counts

    @staticmethod
    def is_code_mixed(text: str, threshold: float = 0.2) -> bool:
        """
        Detect if text is code-mixed (contains multiple scripts).
        
        Args:
            text: Text to analyze
            threshold: Minimum ratio of secondary script to be considered code-mixed
        
        Returns:
            True if text contains significant amounts of multiple scripts
        """
        counts = LanguageUtils.count_script_characters(text)
        
        if len(counts) < 2:
            return False
        
        total = sum(counts.values())
        if total == 0:
            return False
        
        # Sort by count descending
        sorted_counts = sorted(counts.values(), reverse=True)
        
        # Check if second-most-common script meets threshold
        if len(sorted_counts) >= 2:
            secondary_ratio = sorted_counts[1] / total
            return secondary_ratio >= threshold
        
        return False

    @staticmethod
    def contains_english_transliteration(transcript: str) -> bool:
        """
        Check if content contains English transliterated into Telugu script.
        
        This detects cases where English words are written in Telugu script
        (romanized -> Telugu), which can confuse language detection.
        
        Args:
            transcript: Telugu script text to check
        
        Returns:
            True if multiple English transliterations are detected
        """
        count = 0
        for word in LanguageUtils.english_in_telugu:
            if word in transcript:
                count += 1
        return count >= 2

    @staticmethod
    def get_script_name(language_code: str) -> str:
        """
        Get the script name for a language code.
        
        Args:
            language_code: Language code (e.g., 'hi-IN')
        
        Returns:
            Script name (e.g., 'Devanagari')
        """
        script_names = {
            'en-IN': 'Latin',
            'hi-IN': 'Devanagari',
            'mr-IN': 'Devanagari',
            'te-IN': 'Telugu',
            'ta-IN': 'Tamil',
            'kn-IN': 'Kannada',
            'ml-IN': 'Malayalam',
            'bn-IN': 'Bengali',
            'gu-IN': 'Gujarati',
            'pa-IN': 'Gurmukhi',
            'or-IN': 'Odia',
        }
        return script_names.get(language_code, 'Unknown')
