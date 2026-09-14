from typing import Dict, List


class LanguageUtils:
    script_patterns = {
        'en-IN': r'[a-zA-Z]',
        'hi-IN': r'[\u0900-\u097F]',
        'te-IN': r'[\u0C00-\u0C7F]',
        'ta-IN': r'[\u0B80-\u0BFF]',
        'kn-IN': r'[\u0C80-\u0CFF]',
        'ml-IN': r'[\u0D00-\u0D7F]',
        'bn-IN': r'[\u0980-\u09FF]',
        'gu-IN': r'[\u0A80-\u0AFF]',
        'mr-IN': r'[\u0900-\u097F]',
        'pa-IN': r'[\u0A00-\u0A7F]'
    }

    # English words in Telugu script for transliteration detection
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
        """Detect actual language from script content with Telugu preference"""
        if not text:
            return 'en-IN'

        # Count characters for each script (simplified approach matching original logic)
        # The original implementation only counted Telugu range explicitly; we'll follow the same simple approach.
        script_counts: Dict[str, int] = {}
        for lang in LanguageUtils.script_patterns.keys():
            if lang == 'te-IN':
                count = sum(1 for char in text if 0x0C00 <= ord(char) <= 0x0C7F)
            else:
                count = 0
            script_counts[lang] = count

        # Find language with most characters
        max_count = 0
        detected_lang = 'en-IN'

        for lang, count in script_counts.items():
            if count > max_count:
                max_count = count
                detected_lang = lang

        return detected_lang if max_count > 0 else 'en-IN'

    @staticmethod
    def contains_english_transliteration(transcript: str) -> bool:
        """Check if content contains English transliterated into Telugu script"""
        count = 0
        for word in LanguageUtils.english_in_telugu:
            if word in transcript:
                count += 1
        return count >= 2
