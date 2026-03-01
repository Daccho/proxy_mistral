import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# Mistral function calling tool definitions
MEETING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "note_action_item",
            "description": "Record an action item discussed during the meeting, with assignee and optional deadline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Description of the action item",
                    },
                    "assignee": {
                        "type": "string",
                        "description": "Person responsible for the action item",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Deadline in ISO format (optional)",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Priority level",
                    },
                },
                "required": ["description", "assignee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_decision",
            "description": "Record a decision made during the meeting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Description of the decision",
                    },
                    "decision_maker": {
                        "type": "string",
                        "description": "Person who made the decision",
                    },
                },
                "required": ["description", "decision_maker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "defer_to_user",
            "description": "Defer a question to the human user when you cannot answer confidently. Use this for topics outside your knowledge.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to defer",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why you are deferring (e.g. 'budget decision', 'technical detail I don't have')",
                    },
                },
                "required": ["question", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_document",
            "description": "Search the user's document library for relevant information to answer a question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


class MeetingToolExecutor:
    """Executes tool calls from Mistral function calling responses.

    LLM06: Read-only tools execute immediately.  Side-effect tools
    (note_action_item, note_decision) are recorded for post-meeting review.
    """

    # Tools that are safe to execute without human confirmation
    _AUTO_APPROVE = {"lookup_document", "defer_to_user"}

    def __init__(
        self,
        *,
        persona_name: str = "Assistant",
        context_manager: Optional[Any] = None,
    ):
        self._persona_name = persona_name
        self._context_manager = context_manager
        self._action_items: List[Dict[str, Any]] = []
        self._decisions: List[Dict[str, Any]] = []
        self._deferred_items: List[Dict[str, Any]] = []

    def get_recorded_data(self) -> Dict[str, Any]:
        """Return all recorded action items, decisions, and deferred items."""
        return {
            "action_items": self._action_items,
            "decisions": self._decisions,
            "deferred_items": self._deferred_items,
        }

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool call and return the result as a string for Mistral."""
        try:
            if tool_name == "note_action_item":
                return await self._note_action_item(arguments)
            elif tool_name == "note_decision":
                return await self._note_decision(arguments)
            elif tool_name == "defer_to_user":
                return await self._defer_to_user(arguments)
            elif tool_name == "lookup_document":
                return await self._lookup_document(arguments)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return f"Error: {e}"

    async def _note_action_item(self, args: Dict[str, Any]) -> str:
        item = {
            "id": f"action_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self._action_items)}",
            "description": args["description"],
            "assignee": args["assignee"],
            "deadline": args.get("deadline"),
            "priority": args.get("priority", "medium"),
            "recorded_at": datetime.now().isoformat(),
        }
        self._action_items.append(item)
        logger.info(
            "Recorded action item: %s (assigned to: %s)",
            args["description"],
            args["assignee"],
        )
        return f"Action item recorded: {args['description']} → {args['assignee']}"

    async def _note_decision(self, args: Dict[str, Any]) -> str:
        decision = {
            "id": f"decision_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self._decisions)}",
            "description": args["description"],
            "decision_maker": args["decision_maker"],
            "recorded_at": datetime.now().isoformat(),
        }
        self._decisions.append(decision)
        logger.info(
            "Recorded decision: %s (by: %s)",
            args["description"],
            args["decision_maker"],
        )
        return f"Decision recorded: {args['description']}"

    async def _defer_to_user(self, args: Dict[str, Any]) -> str:
        deferred = {
            "id": f"deferred_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self._deferred_items)}",
            "question": args["question"],
            "reason": args["reason"],
            "recorded_at": datetime.now().isoformat(),
        }
        self._deferred_items.append(deferred)
        logger.info(
            "Deferred question: %s (reason: %s)",
            args["question"],
            args["reason"],
        )
        return (
            f"Deferred. Respond with: \"I'll need to check on that and get back to you.\""
        )

    async def _lookup_document(self, args: Dict[str, Any]) -> str:
        if not self._context_manager:
            return "No document context available."

        try:
            results = await self._context_manager.search_documents(args["query"], limit=3)
            if not results:
                return "No relevant documents found."

            formatted = []
            for doc in results:
                content_preview = doc["content"][:300] if doc.get("content") else ""
                formatted.append(f"- {doc.get('title', 'Untitled')}: {content_preview}")
            return "Relevant documents:\n" + "\n".join(formatted)
        except Exception as e:
            logger.error(f"Document lookup error: {e}")
            return f"Document search failed: {e}"
