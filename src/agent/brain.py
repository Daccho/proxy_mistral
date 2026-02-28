import asyncio
import logging
from typing import Optional, Dict, Any, List

from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    TranscriptionFrame,
    StartFrame,
    EndFrame,
    CancelFrame,
)
from mistralai import Mistral

from src.config.settings import settings

logger = logging.getLogger(__name__)


class MistralAgentBrain(FrameProcessor):
    """Mistral Agent brain for decision making and response generation.

    Receives TranscriptionFrame from STT, decides whether to respond,
    and emits TextFrame downstream to TTS when a response is needed.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "mistral-medium-2505",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        persona: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(name="MistralAgentBrain", **kwargs)
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._persona = persona or self._load_default_persona()
        self._client: Optional[Mistral] = None
        self._context: List[Dict[str, Any]] = []
        self._messages: List[dict] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._client = Mistral(api_key=self._api_key)
            self._messages = [{"role": "system", "content": self._generate_system_prompt()}]
            logger.info("MistralAgentBrain initialized")
            await self.push_frame(frame, direction)

        elif isinstance(frame, TranscriptionFrame):
            speaker = frame.metadata.get("speaker", frame.user_id) if frame.metadata else frame.user_id
            self._add_to_context(frame.text, speaker)

            should_respond = await self._should_respond(frame.text, speaker)

            if should_respond:
                response_text = await self._generate_response(frame.text, speaker)
                if response_text:
                    response_frame = TextFrame(text=response_text)
                    response_frame.metadata = {
                        "is_response": True,
                        "response_to": speaker,
                        "source": "mistral_agent",
                    }
                    await self.push_frame(response_frame)

            # TranscriptionFrame is consumed here (not pushed downstream)

        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._client = None
            logger.info("MistralAgentBrain stopped")
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    async def _should_respond(self, text: str, speaker: str) -> bool:
        """Decide whether to respond to this utterance."""
        try:
            speaker_text = text.lower()
            persona_name = self._persona.get("name", "").lower()

            # Check if addressed by name
            if persona_name and persona_name in speaker_text:
                return True

            # Check if direct question
            if any(word in speaker_text for word in ["you", "your", "?"]):
                return True

            # Use Mistral for more sophisticated decision
            if self._client:
                decision_messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a meeting response decision maker. "
                            "Decide if the AI assistant should respond to the given utterance. "
                            "Respond with ONLY 'yes' or 'no'."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Speaker: {speaker}\n"
                            f"Utterance: {text}\n"
                            f"Context: {self._format_context()}\n\n"
                            f"Should the assistant ({self._persona.get('name', 'Assistant')}) respond?"
                        ),
                    },
                ]
                response = await asyncio.to_thread(
                    self._client.chat.complete,
                    model=self._model,
                    messages=decision_messages,
                    max_tokens=10,
                    temperature=0.1,
                )
                if response and response.choices:
                    answer = response.choices[0].message.content.strip().lower()
                    return answer.startswith("yes")

            return False
        except Exception as e:
            logger.error(f"Error in should_respond: {e}")
            return False

    async def _generate_response(self, text: str, speaker: str) -> Optional[str]:
        """Generate response text using Mistral chat completions."""
        if not self._client:
            return None

        try:
            # Add the user utterance to message history
            self._messages.append({
                "role": "user",
                "content": f"[{speaker}]: {text}",
            })

            response = await asyncio.to_thread(
                self._client.chat.complete,
                model=self._model,
                messages=self._messages,
                max_tokens=500,
                temperature=self._temperature,
            )

            if response and response.choices:
                response_text = response.choices[0].message.content
                # Add assistant response to history
                self._messages.append({
                    "role": "assistant",
                    "content": response_text,
                })
                return response_text

            return None
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return None

    def _add_to_context(self, text: str, speaker: str) -> None:
        """Add utterance to conversation context."""
        self._context.append({
            "speaker": speaker,
            "text": text,
        })
        # Limit context size
        if len(self._context) > 100:
            self._context = self._context[-100:]

    def _format_context(self) -> str:
        """Format context for Mistral prompt."""
        formatted = []
        for utterance in self._context[-10:]:
            formatted.append(f"{utterance['speaker']}: {utterance['text']}")
        return "\n".join(formatted)

    def _generate_system_prompt(self) -> str:
        """Generate system prompt from persona."""
        persona_name = self._persona.get("name", "Assistant")
        communication_style = self._persona.get("communication_style", {})
        rules = self._persona.get("rules", [])

        prompt = f"""You are {persona_name}, an AI meeting assistant.

Communication Style:
- Tone: {communication_style.get('tone', 'professional')}
- Verbosity: {communication_style.get('verbosity', 'concise')}
- Formality: {communication_style.get('formality', 'semi-formal')}

Rules:
"""
        for i, rule in enumerate(rules, 1):
            prompt += f"{i}. {rule}\n"

        prompt += """
Current Meeting Context:
- You are attending a meeting as a passive participant
- Only respond when directly addressed or when a direct question is asked
- Be concise and professional
- If unsure about anything, say "I'll confirm the details"
"""
        return prompt

    def _load_default_persona(self) -> Dict[str, Any]:
        """Load default persona from config."""
        return {
            "name": "Assistant",
            "communication_style": {
                "tone": "professional",
                "verbosity": "concise",
                "formality": "semi-formal",
            },
            "rules": [
                "Never commit to deadlines without saying 'I'll confirm the timeline'",
                "Always note action items assigned to me",
                "If unsure about specifics, give best estimate and say 'I'll confirm the details'",
            ],
        }
