import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from mistralai import Mistral

from src.agent.context_manager import DocumentContextManager

logger = logging.getLogger(__name__)


class MeetingSummarizer:
    """Generates post-meeting summaries using Mistral AI."""

    def __init__(self, *, api_key: str, model: str = "mistral-medium-2505", context_manager: Optional[DocumentContextManager] = None):
        self._client = Mistral(api_key=api_key)
        self._model = model
        self._context_manager = context_manager

    async def generate_summary(
        self,
        meeting_id: str,
        title: str,
        transcript: List[Dict[str, Any]],
        participants: List[str],
        recorded_data: Optional[Dict[str, Any]] = None,
        meeting_type: str = "default",
    ) -> Dict[str, Any]:
        """Generate a comprehensive meeting summary using Mistral AI."""
        try:
            transcript_text = self._format_transcript(transcript)

            # Use Mistral to generate structured summary
            executive_summary = await self._generate_executive_summary(title, transcript_text)

            # Extract items via Mistral if no recorded_data provided by the agent
            action_items = (recorded_data or {}).get("action_items", [])
            decisions = (recorded_data or {}).get("decisions", [])
            deferred_items = (recorded_data or {}).get("deferred_items", [])

            # If agent didn't record enough, extract from transcript via Mistral
            if not action_items:
                action_items = await self._extract_with_mistral(transcript_text, "action_items")
            if not decisions:
                decisions = await self._extract_with_mistral(transcript_text, "decisions")

            unanswered_questions = await self._extract_with_mistral(transcript_text, "unanswered_questions")

            # Save to database if context_manager is available
            if self._context_manager:
                await self._context_manager.save_meeting_summary(
                    meeting_id=meeting_id,
                    title=title,
                    summary=executive_summary,
                    action_items=action_items,
                    decisions=decisions,
                    participants=participants,
                )

            summary = {
                "meeting_id": meeting_id,
                "title": title,
                "executive_summary": executive_summary,
                "action_items": action_items,
                "decisions": decisions,
                "deferred_items": deferred_items,
                "questions_unanswered": unanswered_questions,
                "participants": participants,
                "meeting_type": meeting_type,
                "generated_at": datetime.now().isoformat(),
                "transcript_length": len(transcript),
            }

            logger.info("Generated summary for meeting: %s", title)
            return summary

        except Exception as e:
            logger.error("Failed to generate meeting summary: %s", e)
            return {
                "error": str(e),
                "meeting_id": meeting_id,
                "title": title,
                "generated_at": datetime.now().isoformat(),
            }

    async def _generate_executive_summary(self, title: str, transcript_text: str) -> str:
        """Generate executive summary using Mistral AI."""
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a meeting summary assistant. Generate a concise executive summary "
                        "of the meeting transcript. Include: key discussion points, outcomes, and "
                        "any notable disagreements or open questions. Keep it under 300 words."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Meeting: {title}\n\nTranscript:\n{transcript_text}",
                },
            ]
            response = await asyncio.to_thread(
                self._client.chat.complete,
                model=self._model,
                messages=messages,
                max_tokens=1000,
                temperature=0.2,
            )
            if response and response.choices:
                return response.choices[0].message.content
            return f"Summary for {title} — see transcript for details."
        except Exception as e:
            logger.error("Failed to generate executive summary: %s", e)
            return f"Summary for {title} — generation failed: {e}"

    async def _extract_with_mistral(self, transcript_text: str, extract_type: str) -> List[Dict[str, Any]]:
        """Extract structured items from transcript using Mistral AI."""
        prompts = {
            "action_items": (
                "Extract all action items from this meeting transcript. "
                "Return a JSON array where each item has: description, assignee, priority (high/medium/low). "
                "If no action items found, return an empty array []."
            ),
            "decisions": (
                "Extract all decisions made during this meeting. "
                "Return a JSON array where each item has: description, decision_maker. "
                "If no decisions found, return an empty array []."
            ),
            "unanswered_questions": (
                "Extract any questions that were asked but not answered during the meeting. "
                "Return a JSON array where each item has: question, speaker. "
                "If no unanswered questions, return an empty array []."
            ),
        }

        prompt = prompts.get(extract_type)
        if not prompt:
            return []

        try:
            messages = [
                {"role": "system", "content": prompt + "\nRespond with ONLY valid JSON, no other text."},
                {"role": "user", "content": f"Transcript:\n{transcript_text}"},
            ]
            response = await asyncio.to_thread(
                self._client.chat.complete,
                model=self._model,
                messages=messages,
                max_tokens=2000,
                temperature=0.1,
            )
            if response and response.choices:
                content = response.choices[0].message.content.strip()
                # Strip markdown code fences if present
                if content.startswith("```"):
                    content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                return json.loads(content)
            return []
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Failed to extract %s: %s", extract_type, e)
            # Fallback: pattern matching
            return self._fallback_extract(transcript_text, extract_type)

    def _fallback_extract(self, transcript_text: str, extract_type: str) -> List[Dict[str, Any]]:
        """Fallback extraction using simple pattern matching."""
        results = []
        lines = transcript_text.split("\n")

        if extract_type == "action_items":
            patterns = ["will handle", "will take care of", "responsible for", "action item:", "todo:"]
            for line in lines:
                if any(p in line.lower() for p in patterns):
                    results.append({"description": line.strip(), "assignee": "unknown", "priority": "medium"})

        elif extract_type == "decisions":
            patterns = ["we decided", "let's go with", "we'll proceed with", "the decision is", "agreed to"]
            for line in lines:
                if any(p in line.lower() for p in patterns):
                    results.append({"description": line.strip(), "decision_maker": "unknown"})

        elif extract_type == "unanswered_questions":
            for line in lines:
                if line.strip().endswith("?"):
                    results.append({"question": line.strip(), "speaker": "unknown"})

        return results

    def _format_transcript(self, transcript: List[Dict[str, Any]]) -> str:
        """Format transcript list into text."""
        lines = []
        for entry in transcript:
            speaker = entry.get("speaker", "unknown")
            text = entry.get("text", "")
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    def format_as_markdown(self, summary: Dict[str, Any]) -> str:
        """Format summary as Markdown."""
        md = f"# {summary['title']}\n\n"
        md += f"**Meeting ID:** {summary['meeting_id']}\n"
        md += f"**Date:** {summary.get('generated_at', 'Unknown')}\n"
        md += f"**Participants:** {', '.join(summary.get('participants', []))}\n\n"

        md += "## Executive Summary\n\n"
        md += f"{summary['executive_summary']}\n\n"

        if summary.get("action_items"):
            md += "## Action Items\n\n"
            for item in summary["action_items"]:
                assignee = item.get("assignee", "unassigned")
                md += f"- {item['description']} (Assigned to: {assignee})\n"
            md += "\n"

        if summary.get("decisions"):
            md += "## Decisions\n\n"
            for d in summary["decisions"]:
                md += f"- {d['description']}\n"
            md += "\n"

        if summary.get("deferred_items"):
            md += "## Deferred Items\n\n"
            for item in summary["deferred_items"]:
                md += f"- {item.get('question', item.get('description', ''))}\n"
            md += "\n"

        if summary.get("questions_unanswered"):
            md += "## Unanswered Questions\n\n"
            for q in summary["questions_unanswered"]:
                md += f"- {q.get('question', '')}\n"
            md += "\n"

        return md
