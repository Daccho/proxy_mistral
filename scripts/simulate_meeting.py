#!/usr/bin/env python3
"""
Simulated meeting test script for Proxy Mistral.

This script simulates a meeting with multiple participants and tests the full pipeline.
"""

import asyncio
import logging
import json
from typing import List, Dict, Any
from datetime import datetime

import structlog
from pipecat.frames.frames import InputAudioRawFrame, TranscriptionFrame

from src.pipeline.meeting_pipeline import MeetingPipeline
from src.meeting.transports.meetingbaas import MeetingBaaSTransport
from src.agent.context_manager import DocumentContextManager
from src.agent.summarizer import MeetingSummarizer

# Configure logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=False
)

logger = structlog.get_logger()


class SimulatedMeeting:
    """Simulates a meeting with multiple participants and utterances."""

    def __init__(self):
        self.participants = [
            {"id": "p1", "name": "Alice", "is_host": True},
            {"id": "p2", "name": "Bob", "is_host": False},
            {"id": "p3", "name": "Charlie", "is_host": False}
        ]
        self.transcript: List[Dict[str, Any]] = []
        self.current_time = 0.0

    async def generate_simulated_utterances(self) -> List[Dict[str, Any]]:
        """Generate a sequence of simulated utterances."""
        utterances = [
            # Meeting start
            {"speaker": "Alice", "text": "Good morning everyone, let's start the meeting.", "duration": 3.0},
            {"speaker": "Bob", "text": "Good morning Alice, I'm here.", "duration": 2.0},
            {"speaker": "Charlie", "text": "Morning all, ready to go.", "duration": 1.5},
            
            # Discussion
            {"speaker": "Alice", "text": "Today we need to discuss the project timeline and any blockers.", "duration": 4.0},
            {"speaker": "Bob", "text": "I have a concern about the timeline for the API integration.", "duration": 3.5},
            {"speaker": "Alice", "text": "What's the issue with the API integration, Bob?", "duration": 2.5},
            
            # Action items
            {"speaker": "Bob", "text": "The third-party API team says they need two more weeks. This could delay our launch.", "duration": 4.5},
            {"speaker": "Alice", "text": "That's a problem. Charlie, can you follow up with the API team and see if we can get a firm commitment?", "duration": 5.0},
            {"speaker": "Charlie", "text": "Will do, Alice. I'll set up a call with them today and report back tomorrow.", "duration": 3.5},
            
            # Decision
            {"speaker": "Alice", "text": "Okay, let's tentatively plan to launch on the original date but with a backup plan. Bob, can you prepare a contingency plan?", "duration": 5.5},
            {"speaker": "Bob", "text": "Yes, I can work on that. Should I have it ready by end of day?", "duration": 2.5},
            {"speaker": "Alice", "text": "Yes, that would be great. Let's reconvene tomorrow at the same time to review progress.", "duration": 3.0},
            
            # Meeting end
            {"speaker": "Alice", "text": "Any other questions or concerns before we wrap up?", "duration": 2.5},
            {"speaker": "Bob", "text": "No, that covers everything for me.", "duration": 1.5},
            {"speaker": "Charlie", "text": "All good here, thanks Alice.", "duration": 1.0},
            {"speaker": "Alice", "text": "Great, meeting adjourned. See you all tomorrow.", "duration": 2.0}
        ]
        
        # Add timestamps and participant IDs
        for i, utterance in enumerate(utterances):
            participant = next(p for p in self.participants if p["name"] == utterance["speaker"])
            utterance.update({
                "participant_id": participant["id"],
                "timestamp": self.current_time,
                "is_host": participant["is_host"]
            })
            self.current_time += utterance["duration"]
            self.transcript.append(utterance.copy())
        
        return utterances

    async def simulate_meeting(self, pipeline: MeetingPipeline) -> None:
        """Simulate a meeting by sending utterances through the pipeline."""
        logger.info("Starting simulated meeting...")
        
        # Generate utterances
        utterances = await self.generate_simulated_utterances()
        
        # Process each utterance
        for utterance in utterances:
            logger.info(f"Processing utterance: {utterance['speaker']}: {utterance['text'][:50]}...")
            
            # Create a mock audio frame (in real scenario, this would come from STT)
            # For simulation, we'll create a transcription frame directly
            transcription_frame = TranscriptionFrame(
                text=utterance["text"],
                user_id=utterance["participant_id"],
                timestamp=str(utterance["timestamp"])
            )
            
            # Add metadata
            transcription_frame.metadata = {
                "speaker": utterance["speaker"],
                "participant_id": utterance["participant_id"],
                "is_host": utterance["is_host"],
                "source": "simulation"
            }
            
            # Send through pipeline (this would normally happen automatically)
            # In our simulation, we'll just log it
            logger.info(f"Transcription: {utterance['speaker']}: {utterance['text']}")
            
            # Simulate agent response for certain utterances
            if "proxy" in utterance["text"].lower() or "?" in utterance["text"]:
                await self._simulate_agent_response(utterance, pipeline)
            
            # Small delay to simulate real-time processing
            await asyncio.sleep(0.1)
        
        logger.info("Simulated meeting completed")

    async def _simulate_agent_response(self, utterance: Dict[str, Any], pipeline: MeetingPipeline) -> None:
        """Simulate agent response to an utterance."""
        # This would normally be handled by the MistralAgentBrain
        # For simulation, we'll generate a simple response
        
        if "proxy" in utterance["text"].lower():
            response_text = f"Yes {utterance['speaker']}, I'm here and listening. How can I assist?"
        elif "?" in utterance["text"]:
            response_text = f"That's a good question. I'll need to check on that and get back to you."
        else:
            response_text = "Thank you for the information."
        
        logger.info(f"Agent response: {response_text}")
        
        # In a real scenario, this would generate audio and send it back
        # For simulation, we just log it

    def get_transcript(self) -> List[Dict[str, Any]]:
        """Get the full meeting transcript."""
        return self.transcript


class MeetingSimulator:
    """Main meeting simulator class."""

    def __init__(self):
        self.transport = MeetingBaaSTransport()
        self.pipeline = MeetingPipeline(self.transport)
        self.context_manager = DocumentContextManager()
        self.summarizer = MeetingSummarizer(self.context_manager)

    async def setup(self) -> None:
        """Set up the simulator."""
        logger.info("Setting up meeting simulator...")
        
        # Initialize components
        await self.pipeline.setup()
        logger.info("Pipeline setup complete")

    async def run_simulation(self) -> None:
        """Run the meeting simulation."""
        try:
            # Create simulated meeting
            meeting = SimulatedMeeting()
            
            # Run the simulation
            await meeting.simulate_meeting(self.pipeline)
            
            # Generate summary
            transcript = meeting.get_transcript()
            summary = await self.summarizer.generate_summary(
                meeting_id="simulated_meeting_1",
                title="Simulated Project Meeting",
                transcript=transcript,
                participants=[p["name"] for p in meeting.participants]
            )
            
            # Display results
            logger.info("Meeting Summary:")
            logger.info(f"Title: {summary['title']}")
            logger.info(f"Duration: ~{summary['transcript_length'] * 5} minutes")
            logger.info(f"Action Items: {len(summary['action_items'])}")
            logger.info(f"Decisions: {len(summary['decisions'])}")
            logger.info(f"Deferred Items: {len(summary['deferred_items'])}")
            
            # Export summary
            markdown_summary = await self.summarizer.export_summary(summary, "markdown")
            logger.info("\n" + "="*50)
            logger.info("MEETING SUMMARY (Markdown):")
            logger.info("="*50)
            logger.info(markdown_summary)
            
        except Exception as e:
            logger.error(f"Simulation failed: {e}")
            raise

    async def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up simulator...")
        await self.pipeline.stop()


async def main():
    """Main entry point."""
    logger.info("Starting Proxy Mistral Meeting Simulator")
    
    try:
        # Create and run simulator
        simulator = MeetingSimulator()
        await simulator.setup()
        await simulator.run_simulation()
        await simulator.cleanup()
        
        logger.info("✅ Meeting simulation completed successfully!")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Simulation cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)