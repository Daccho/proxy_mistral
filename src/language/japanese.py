import logging
from typing import Optional, Dict, Any, List
import re

from sentence_transformers import SentenceTransformer
from fugashi import Tagger
from unicodedata import normalize

logger = logging.getLogger(__name__)


class JapaneseLanguageSupport:
    """Japanese language support for the meeting proxy agent."""

    def __init__(self):
        self.tagger = Tagger('-Owakati')  # Japanese tokenizer
        self.sentence_model: Optional[SentenceTransformer] = None
        self._initialize_models()

    def _initialize_models(self) -> None:
        """Initialize language models."""
        try:
            # Load Japanese sentence transformer model
            # Note: This is a placeholder - in production you would use an appropriate model
            # self.sentence_model = SentenceTransformer('intfloat/multilingual-e5-large')
            logger.info("Japanese language models initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Japanese models: {e}")
            # Fallback to basic support without ML models

    def normalize_text(self, text: str) -> str:
        """Normalize Japanese text for processing."""
        try:
            # Unicode normalization
            text = normalize('NFKC', text)
            
            # Remove extra whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            return text
        except Exception as e:
            logger.error(f"Text normalization failed: {e}")
            return text

    def tokenize(self, text: str) -> List[str]:
        """Tokenize Japanese text using MeCab."""
        try:
            # Normalize first
            text = self.normalize_text(text)
            
            # Tokenize using Fugashi (MeCab binding)
            tokens = [token for token in self.tagger(text)]
            return tokens
        except Exception as e:
            logger.error(f"Tokenization failed: {e}")
            # Fallback to simple whitespace split
            return text.split()

    def detect_language(self, text: str) -> str:
        """Detect if text is Japanese."""
        try:
            # Simple heuristic: check for Japanese characters
            japanese_range = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')
            
            if japanese_range.search(text):
                return 'ja'
            
            # Check for common Japanese punctuation
            japanese_punct = re.compile(r'[、。・：「」（）【】]')
            if japanese_punct.search(text):
                return 'ja'
            
            return 'en'  # Default to English
        except Exception as e:
            logger.error(f"Language detection failed: {e}")
            return 'unknown'

    def translate_to_english(self, text: str) -> str:
        """Translate Japanese text to English (placeholder)."""
        # In a real implementation, this would use a translation API
        # For now, return a placeholder
        return f"[TRANSLATION: {text}]"

    def extract_key_phrases(self, text: str, language: str = 'ja') -> List[str]:
        """Extract key phrases from Japanese text."""
        try:
            if language != 'ja':
                # For non-Japanese text, use simple noun extraction
                tokens = text.split()
                return [token for token in tokens if len(token) > 3]  # Simple heuristic
            
            # Tokenize Japanese text
            tokens = self.tokenize(text)
            
            # Simple key phrase extraction (nouns and proper nouns)
            # In production, use proper POS tagging
            key_phrases = []
            current_phrase = []
            
            for token in tokens:
                # Simple heuristic: nouns are often followed by particles
                # This is a placeholder - real implementation would use proper POS tagging
                if len(token) > 1 and not token in ['の', 'は', 'が', 'を', 'に', 'で', 'と']:
                    current_phrase.append(token)
                elif current_phrase:
                    key_phrases.append(''.join(current_phrase))
                    current_phrase = []
            
            if current_phrase:
                key_phrases.append(''.join(current_phrase))
            
            return key_phrases
        except Exception as e:
            logger.error(f"Key phrase extraction failed: {e}")
            return []

    def generate_embeddings(self, text: str) -> Optional[List[float]]:
        """Generate embeddings for Japanese text."""
        try:
            if self.sentence_model:
                # Normalize text
                text = self.normalize_text(text)
                
                # Generate embeddings
                embeddings = self.sentence_model.encode(text)
                return embeddings.tolist()
            else:
                logger.warning("Sentence transformer model not loaded")
                return None
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def analyze_sentiment(self, text: str) -> Dict[str, float]:
        """Analyze sentiment of Japanese text (placeholder)."""
        # In a real implementation, use a sentiment analysis model
        return {
            'positive': 0.5,
            'neutral': 0.3,
            'negative': 0.2
        }

    def process_meeting_transcript(self, transcript: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process meeting transcript for Japanese language support."""
        processed = []
        
        for utterance in transcript:
            try:
                text = utterance['text']
                language = self.detect_language(text)
                
                processed_utterance = utterance.copy()
                processed_utterance['language'] = language
                
                if language == 'ja':
                    # Add Japanese-specific processing
                    processed_utterance['tokens'] = self.tokenize(text)
                    processed_utterance['key_phrases'] = self.extract_key_phrases(text)
                    processed_utterance['translation'] = self.translate_to_english(text)
                
                processed.append(processed_utterance)
            except Exception as e:
                logger.error(f"Failed to process utterance: {e}")
                processed.append(utterance)
        
        return processed

    def generate_japanese_response(self, context: str, query: str) -> str:
        """Generate Japanese response (placeholder)."""
        # In a real implementation, use a Japanese LLM
        # For now, return a placeholder response
        return "申し訳ありませんが、その質問にはお答えできません。詳細を確認して後でお返事します。"

    def is_japanese_meeting(self, transcript: List[Dict[str, Any]]) -> bool:
        """Determine if a meeting is primarily in Japanese."""
        try:
            japanese_count = 0
            total_count = len(transcript)
            
            if total_count == 0:
                return False
            
            for utterance in transcript:
                if self.detect_language(utterance['text']) == 'ja':
                    japanese_count += 1
            
            # If more than 60% of utterances are Japanese
            return (japanese_count / total_count) > 0.6
        except Exception as e:
            logger.error(f"Meeting language detection failed: {e}")
            return False

    def get_language_stats(self, transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get language statistics for a meeting."""
        try:
            stats = {
                'japanese': 0,
                'english': 0,
                'other': 0,
                'total_utterances': len(transcript),
                'total_words': 0
            }
            
            for utterance in transcript:
                lang = self.detect_language(utterance['text'])
                tokens = self.tokenize(utterance['text']) if lang == 'ja' else utterance['text'].split()
                
                if lang == 'ja':
                    stats['japanese'] += 1
                elif lang == 'en':
                    stats['english'] += 1
                else:
                    stats['other'] += 1
                
                stats['total_words'] += len(tokens)
            
            # Calculate percentages
            if stats['total_utterances'] > 0:
                stats['japanese_percentage'] = (stats['japanese'] / stats['total_utterances']) * 100
                stats['english_percentage'] = (stats['english'] / stats['total_utterances']) * 100
                stats['other_percentage'] = (stats['other'] / stats['total_utterances']) * 100
            
            return stats
        except Exception as e:
            logger.error(f"Language stats failed: {e}")
            return {
                'error': str(e),
                'japanese': 0,
                'english': 0,
                'other': 0,
                'total_utterances': len(transcript)
            }

    def cleanup(self) -> None:
        """Clean up resources."""
        self.sentence_model = None