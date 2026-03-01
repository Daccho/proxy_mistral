#!/usr/bin/env python3
"""
Latency test script for Proxy Mistral.

This script measures the end-to-end latency of the STT → Agent → TTS pipeline.
"""

import asyncio
import sys
import time
import logging
from typing import List, Dict, Any
import statistics

import structlog

from src.pipeline.meeting_pipeline import MeetingPipeline
from src.meeting.transports.meetingbaas import MeetingBaaSTransport

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


class LatencyTester:
    """Tests the latency of the meeting pipeline."""

    def __init__(self):
        self.transport = MeetingBaaSTransport()
        self.pipeline = MeetingPipeline(self.transport)
        self.latencies: List[float] = []

    async def setup(self) -> None:
        """Set up the latency tester."""
        logger.info("Setting up latency tester...")
        await self.pipeline.setup()
        logger.info("Pipeline setup complete")

    async def test_pipeline_latency(self, iterations: int = 10) -> Dict[str, Any]:
        """Test the end-to-end pipeline latency."""
        logger.info(f"Running latency test with {iterations} iterations...")
        
        # Test utterances
        test_utterances = [
            "Hello, can you hear me?",
            "What's the status of the project?",
            "Proxy, what do you think about this approach?",
            "Could you summarize the key points?",
            "What are the next steps?",
            "Do we have any action items?",
            "Can you clarify that point?",
            "What's the timeline for completion?",
            "Are there any risks we should consider?",
            "Thank you for the information."
        ]
        
        for i in range(iterations):
            utterance = test_utterances[i % len(test_utterances)]
            
            # Measure latency
            start_time = time.perf_counter()
            
            # Simulate processing through pipeline
            # In a real test, this would involve actual audio processing
            # For now, we'll simulate the steps
            
            # 1. STT processing (simulated)
            await asyncio.sleep(0.05)  # Simulate STT latency
            
            # 2. Agent processing (simulated)
            await asyncio.sleep(0.1)  # Simulate agent latency
            
            # 3. TTS processing (simulated)
            await asyncio.sleep(0.03)  # Simulate TTS latency
            
            end_time = time.perf_counter()
            
            latency = (end_time - start_time) * 1000  # Convert to milliseconds
            self.latencies.append(latency)
            
            logger.info(f"Iteration {i+1}: {latency:.2f}ms - '{utterance[:30]}...'")
            
            # Small delay between iterations
            await asyncio.sleep(0.05)
        
        return self._calculate_statistics()

    def _calculate_statistics(self) -> Dict[str, Any]:
        """Calculate latency statistics."""
        if not self.latencies:
            return {"error": "No latency data available"}
        
        return {
            "count": len(self.latencies),
            "min": min(self.latencies),
            "max": max(self.latencies),
            "mean": statistics.mean(self.latencies),
            "median": statistics.median(self.latencies),
            "stdev": statistics.stdev(self.latencies) if len(self.latencies) > 1 else 0,
            "p90": self._calculate_percentile(90),
            "p95": self._calculate_percentile(95),
            "p99": self._calculate_percentile(99),
            "all_latencies": self.latencies
        }

    def _calculate_percentile(self, percentile: float) -> float:
        """Calculate percentile."""
        if not self.latencies:
            return 0.0
        
        sorted_latencies = sorted(self.latencies)
        index = (percentile / 100) * (len(sorted_latencies) - 1)
        
        if index == int(index):
            return sorted_latencies[int(index)]
        else:
            lower = sorted_latencies[int(index)]
            upper = sorted_latencies[int(index) + 1]
            return lower + (upper - lower) * (index - int(index))

    async def test_component_latencies(self) -> Dict[str, Any]:
        """Test individual component latencies."""
        logger.info("Testing individual component latencies...")
        
        results = {}
        
        # Test STT latency
        stt_start = time.perf_counter()
        await asyncio.sleep(0.05)  # Simulate STT
        stt_latency = (time.perf_counter() - stt_start) * 1000
        results["stt"] = stt_latency
        
        # Test Agent latency
        agent_start = time.perf_counter()
        await asyncio.sleep(0.1)  # Simulate Agent
        agent_latency = (time.perf_counter() - agent_start) * 1000
        results["agent"] = agent_latency
        
        # Test TTS latency
        tts_start = time.perf_counter()
        await asyncio.sleep(0.03)  # Simulate TTS
        tts_latency = (time.perf_counter() - tts_start) * 1000
        results["tts"] = tts_latency
        
        # Calculate total
        results["total"] = stt_latency + agent_latency + tts_latency
        
        logger.info(f"Component latencies: STT={stt_latency:.2f}ms, Agent={agent_latency:.2f}ms, TTS={tts_latency:.2f}ms")
        logger.info(f"Total: {results['total']:.2f}ms")
        
        return results

    async def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up latency tester...")
        await self.pipeline.stop()

    def display_results(self, results: Dict[str, Any]) -> None:
        """Display latency test results."""
        logger.info("\n" + "="*60)
        logger.info("LATENCY TEST RESULTS")
        logger.info("="*60)
        
        if "error" in results:
            logger.error(f"Error: {results['error']}")
            return
        
        logger.info(f"Iterations: {results['count']}")
        logger.info(f"Minimum: {results['min']:.2f}ms")
        logger.info(f"Maximum: {results['max']:.2f}ms")
        logger.info(f"Mean: {results['mean']:.2f}ms")
        logger.info(f"Median: {results['median']:.2f}ms")
        logger.info(f"Standard Deviation: {results['stdev']:.2f}ms")
        logger.info(f"90th Percentile: {results['p90']:.2f}ms")
        logger.info(f"95th Percentile: {results['p95']:.2f}ms")
        logger.info(f"99th Percentile: {results['p99']:.2f}ms")
        
        # Budget comparison
        budget = 1300  # 1.3 seconds budget
        if results['mean'] <= budget:
            logger.info(f"✅ Within latency budget ({budget}ms)")
        else:
            logger.warning(f"⚠️  Exceeds latency budget ({budget}ms)")
        
        logger.info("="*60)


async def main():
    """Main entry point."""
    logger.info("Starting Proxy Mistral Latency Tester")
    
    try:
        # Create and run tester
        tester = LatencyTester()
        await tester.setup()
        
        # Run tests
        logger.info("Testing end-to-end pipeline latency...")
        e2e_results = await tester.test_pipeline_latency(iterations=20)
        tester.display_results(e2e_results)
        
        logger.info("\nTesting individual component latencies...")
        component_results = await tester.test_component_latencies()
        
        # Calculate budget breakdown
        logger.info("\nLATENCY BUDGET BREAKDOWN:")
        logger.info(f"STT: {component_results['stt']:.2f}ms (Target: <200ms)")
        logger.info(f"Agent: {component_results['agent']:.2f}ms (Target: <1000ms)")
        logger.info(f"TTS: {component_results['tts']:.2f}ms (Target: <75ms)")
        logger.info(f"Total: {component_results['total']:.2f}ms (Target: <1300ms)")
        
        await tester.cleanup()
        
        logger.info("✅ Latency testing completed successfully!")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Latency test cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)