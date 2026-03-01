#!/usr/bin/env python3
"""
Voice cloning setup script for Proxy Mistral.

This script guides users through the voice cloning process using ElevenLabs.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
import soundfile as sf
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def check_dependencies():
    """Check if required dependencies are available."""
    try:
        import soundfile
        import numpy
        # Check if ffmpeg is available
        import subprocess
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        return False
    except subprocess.CalledProcessError:
        logger.error("ffmpeg is required but not installed")
        return False
    except Exception as e:
        logger.error(f"Dependency check failed: {e}")
        return False


async def record_audio_sample(output_path: str, duration: int = 30) -> bool:
    """Record audio sample for voice cloning."""
    try:
        import sounddevice as sd
        
        logger.info(f"Recording {duration} seconds of audio...")
        logger.info("Speak clearly in your normal voice.")
        logger.info("Press Ctrl+C to stop early if needed.")
        
        # Record audio
        sample_rate = 16000  # 16kHz for ElevenLabs
        audio_data = sd.rec(
            int(duration * sample_rate), 
            samplerate=sample_rate, 
            channels=1, 
            dtype='int16'
        )
        
        # Wait for recording to complete
        sd.wait()
        
        # Save as WAV file
        sf.write(output_path, audio_data, sample_rate)
        logger.info(f"Audio sample saved to {output_path}")
        
        # Check audio quality
        if np.max(np.abs(audio_data)) < 1000:  # Too quiet
            logger.warning("Audio seems too quiet. Please speak louder.")
            return False
        
        return True

    except KeyboardInterrupt:
        logger.info("Recording stopped by user")
        return False
    except ImportError:
        logger.error("sounddevice package required for audio recording")
        return False
    except Exception as e:
        logger.error(f"Failed to record audio: {e}")
        return False


async def upload_to_elevenlabs(api_key: str, audio_path: str) -> Optional[str]:
    """Upload audio sample to ElevenLabs for voice cloning."""
    try:
        import requests
        
        logger.info("Uploading audio to ElevenLabs for voice cloning...")
        
        # Read audio file
        with open(audio_path, "rb") as audio_file:
            files = {"files": audio_file}
            
        # ElevenLabs voice cloning endpoint
        url = "https://api.elevenlabs.io/v1/voices/add"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "multipart/form-data"
        }
        
        # Additional parameters
        data = {
            "name": "Proxy Mistral Voice Clone",
            "description": "Voice clone for meeting proxy agent",
            "labels": {"use_case": "meeting_proxy"}
        }
        
        # Make the request
        response = requests.post(url, headers=headers, files=files, data=data)
        response.raise_for_status()
        
        result = response.json()
        voice_id = result["voice_id"]
        
        logger.info(f"Voice cloning successful! Voice ID: {voice_id}")
        return voice_id
        
    except ImportError:
        logger.error("requests package required for API calls")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"ElevenLabs API error: {e}")
        if hasattr(e, 'response') and e.response:
            logger.error(f"Response: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Failed to upload to ElevenLabs: {e}")
        return None


async def save_voice_id(voice_id: str, env_path: str = ".env") -> bool:
    """Save voice ID to environment file."""
    try:
        # Read existing .env file
        env_lines = []
        if Path(env_path).exists():
            with open(env_path, "r") as f:
                env_lines = f.readlines()
        
        # Update or add ELEVENLABS_VOICE_ID
        updated = False
        for i, line in enumerate(env_lines):
            if line.startswith("ELEVENLABS_VOICE_ID="):
                env_lines[i] = f"ELEVENLABS_VOICE_ID={voice_id}\n"
                updated = True
                break
        
        if not updated:
            env_lines.append(f"ELEVENLABS_VOICE_ID={voice_id}\n")
        
        # Write back to file
        with open(env_path, "w") as f:
            f.writelines(env_lines)
        
        logger.info(f"Voice ID saved to {env_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save voice ID: {e}")
        return False


async def test_voice_clone(api_key: str, voice_id: str) -> bool:
    """Test the voice clone with a simple sentence."""
    try:
        import requests
        import io
        import soundfile as sf
        
        logger.info("Testing voice clone...")
        
        # ElevenLabs TTS endpoint
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        data = {
            "text": "Hello, this is your meeting proxy assistant speaking in your cloned voice.",
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        
        # Make the request
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        
        # Save and play the audio
        output_path = "test_voice_clone.wav"
        with open(output_path, "wb") as f:
            f.write(response.content)
        
        logger.info(f"Voice test saved to {output_path}")
        
        # Play the audio
        try:
            import sounddevice as sd
            data, sample_rate = sf.read(output_path)
            sd.play(data, sample_rate)
            sd.wait()
            logger.info("Voice test playback completed")
            return True
        except ImportError:
            logger.info("Audio playback skipped (sounddevice not available)")
            return True
        
    except ImportError:
        logger.error("requests package required for API calls")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"ElevenLabs TTS error: {e}")
        return False
    except Exception as e:
        logger.error(f"Voice test failed: {e}")
        return False


async def main():
    """Main setup function."""
    logger.info("Starting Proxy Mistral voice cloning setup...")
    
    # Check dependencies
    if not check_dependencies():
        logger.error("Please install missing dependencies and try again.")
        return 1
    
    # Get API key
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        api_key = input("Enter your ElevenLabs API key: ").strip()
        if not api_key:
            logger.error("ElevenLabs API key is required")
            return 1
    
    # Create output directory
    output_dir = Path("voice_samples")
    output_dir.mkdir(exist_ok=True)
    
    # Record audio sample
    audio_path = output_dir / "voice_sample.wav"
    while True:
        success = await record_audio_sample(str(audio_path), 30)
        if success:
            break
        
        retry = input("Try again? (y/n): ").strip().lower()
        if retry != 'y':
            logger.error("Voice cloning cancelled")
            return 1
    
    # Upload to ElevenLabs
    voice_id = await upload_to_elevenlabs(api_key, str(audio_path))
    if not voice_id:
        logger.error("Voice cloning failed")
        return 1
    
    # Save voice ID
    if not await save_voice_id(voice_id):
        logger.error("Failed to save voice ID")
        return 1
    
    # Test voice clone
    if not await test_voice_clone(api_key, voice_id):
        logger.warning("Voice test failed, but voice cloning may still work")
    
    logger.info("✅ Voice cloning setup completed successfully!")
    logger.info(f"Voice ID: {voice_id}")
    logger.info("You can now use this voice in your meetings.")
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)