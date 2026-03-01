import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

from src.config.settings import settings
from src.security.crypto import encrypt_data, decrypt_data

# Configure logging
logger = logging.getLogger(__name__)

# Google Calendar API scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]


class GoogleCalendarIntegration:
    """Integration with Google Calendar API for meeting management."""

    def __init__(self):
        self.credentials: Optional[Credentials] = None
        self.service: Optional[Any] = None
        self._initialize()

    def _initialize(self) -> None:
        """Initialize Google Calendar API client.

        Production: loads token from GOOGLE_CALENDAR_CREDENTIALS env var (K8s Secret).
        Development: loads from file, falls back to interactive OAuth browser flow.
        """
        try:
            creds = None
            is_production = settings.app.environment == "production"
            token_path = os.path.join(settings.app.data_dir, 'google_calendar_token.json')

            # 1. Try environment variable first (production path)
            env_token = settings.google_calendar.credentials_json
            if env_token:
                creds = self._load_creds_from_string(env_token)

            # 2. Fall back to file-based token (development)
            if not creds and os.path.exists(token_path):
                try:
                    with open(token_path, 'r') as f:
                        token_data = f.read()
                    creds = self._load_creds_from_string(token_data)
                except Exception:
                    logger.warning("Failed to load token file, trying unencrypted (migration)")
                    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

            # 3. Refresh or acquire new credentials
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    self._save_token(creds, token_path)
                elif not is_production:
                    # Interactive OAuth flow (development only)
                    flow = InstalledAppFlow.from_client_secrets_file(
                        os.path.join(settings.app.data_dir, 'credentials.json'),
                        SCOPES,
                    )
                    creds = flow.run_local_server(port=0)
                    self._save_token(creds, token_path)
                else:
                    raise RuntimeError(
                        "No valid Google Calendar credentials in production. "
                        "Run 'python -m src.main auth-calendar' locally first, "
                        "then set GOOGLE_CALENDAR_CREDENTIALS as a K8s secret."
                    )

            self.credentials = creds
            self.service = build('calendar', 'v3', credentials=creds)
            logger.info("Google Calendar API initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Google Calendar API: {e}")
            raise

    def _load_creds_from_string(self, data: str) -> Optional[Credentials]:
        """Load credentials from a string (encrypted or plain JSON)."""
        # Try decrypting first (A02: encrypted token storage)
        try:
            decrypted = decrypt_data(data)
            return Credentials.from_authorized_user_info(json.loads(decrypted), SCOPES)
        except Exception:
            pass
        # Try as plain JSON
        try:
            return Credentials.from_authorized_user_info(json.loads(data), SCOPES)
        except Exception:
            return None

    def _save_token(self, creds: Credentials, token_path: str) -> None:
        """Save credentials to file with encryption (A02)."""
        os.makedirs(os.path.dirname(token_path) if os.path.dirname(token_path) else '.', exist_ok=True)
        with open(token_path, 'w') as f:
            f.write(encrypt_data(creds.to_json()))

    def is_authenticated(self) -> bool:
        """Check if authenticated with Google Calendar."""
        return self.credentials is not None and self.service is not None

    async def get_upcoming_meetings(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Get upcoming meetings from Google Calendar."""
        if not self.is_authenticated():
            raise RuntimeError("Not authenticated with Google Calendar")

        try:
            # Get current time and time range
            now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
            time_max = (datetime.utcnow() + timedelta(days=7)).isoformat() + 'Z'
            
            # Get events from primary calendar
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=now,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Filter for Google Meet meetings
            meetings = []
            for event in events:
                # Check if it's a Google Meet event
                if 'conferenceData' in event and event['conferenceData'].get('entryPointType') == 'video':
                    meeting = {
                        'id': event['id'],
                        'summary': event.get('summary', 'No title'),
                        'description': event.get('description', ''),
                        'start': event['start'].get('dateTime', event['start'].get('date')),
                        'end': event['end'].get('dateTime', event['end'].get('date')),
                        'meet_url': event['conferenceData']['entryPoints'][0]['uri'],
                        'organizer': event.get('organizer', {}).get('email', 'Unknown'),
                        'attendees': [attendee.get('email') for attendee in event.get('attendees', [])],
                        'status': event.get('status', 'confirmed')
                    }
                    meetings.append(meeting)
            
            logger.info(f"Found {len(meetings)} upcoming Google Meet meetings")
            return meetings

        except HttpError as error:
            logger.error(f"Google Calendar API error: {error}")
            raise
        except Exception as e:
            logger.error(f"Failed to get upcoming meetings: {e}")
            raise

    async def get_meeting_details(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific meeting."""
        if not self.is_authenticated():
            raise RuntimeError("Not authenticated with Google Calendar")

        try:
            event = self.service.events().get(
                calendarId='primary',
                eventId=meeting_id
            ).execute()
            
            if 'conferenceData' not in event:
                return None
                
            meeting = {
                'id': event['id'],
                'summary': event.get('summary', 'No title'),
                'description': event.get('description', ''),
                'start': event['start'].get('dateTime', event['start'].get('date')),
                'end': event['end'].get('dateTime', event['end'].get('date')),
                'meet_url': event['conferenceData']['entryPoints'][0]['uri'],
                'organizer': event.get('organizer', {}).get('email', 'Unknown'),
                'attendees': [attendee.get('email') for attendee in event.get('attendees', [])],
                'status': event.get('status', 'confirmed'),
                'hangoutLink': event.get('hangoutLink'),
                'conference_data': event.get('conferenceData')
            }
            
            return meeting

        except HttpError as error:
            logger.error(f"Google Calendar API error: {error}")
            return None
        except Exception as e:
            logger.error(f"Failed to get meeting details: {e}")
            return None

    async def auto_join_meetings(self, persona: str = "default") -> List[str]:
        """Automatically join meetings based on priority and persona."""
        if not self.is_authenticated():
            raise RuntimeError("Not authenticated with Google Calendar")

        try:
            # Get upcoming meetings
            meetings = await self.get_upcoming_meetings()
            
            joined_meetings = []
            
            for meeting in meetings:
                # Check if meeting should be auto-joined based on persona
                should_join = await self._should_auto_join(meeting, persona)
                
                if should_join:
                    try:
                        # In a real implementation, this would call the meeting join logic
                        # For now, we'll just log and return the meeting URL
                        logger.info(f"Auto-joining meeting: {meeting['summary']}")
                        joined_meetings.append(meeting['meet_url'])
                        
                    except Exception as e:
                        logger.error(f"Failed to join meeting {meeting['id']}: {e}")

            return joined_meetings

        except Exception as e:
            logger.error(f"Failed to auto-join meetings: {e}")
            return []

    async def _should_auto_join(self, meeting: Dict[str, Any], persona: str) -> bool:
        """Determine if a meeting should be auto-joined based on persona and rules."""
        try:
            persona_config = self._load_persona_settings(persona)
            auto_join = persona_config.get('auto_join', {})

            # Priority keyword override: join regardless of meeting type
            title = meeting.get('summary', '').lower()
            keywords = auto_join.get('priority_keywords', [])
            if auto_join.get('keyword_override') and any(k in title for k in keywords):
                logger.info(f"Priority keyword match for '{meeting.get('summary')}', auto-joining")
                return True

            # Check meeting type rules
            meeting_type = self._determine_meeting_type(meeting)
            return auto_join.get(meeting_type, auto_join.get('default', False))

        except Exception as e:
            logger.error(f"Failed to determine auto-join for meeting: {e}")
            return False

    def _load_persona_settings(self, persona: str) -> Dict[str, Any]:
        """Load persona settings from YAML configuration file."""
        import yaml
        persona_path = os.path.join('config', 'personas', f'{persona}.yaml')
        try:
            with open(persona_path, 'r') as f:
                config = yaml.safe_load(f) or {}
            return config
        except FileNotFoundError:
            logger.warning(f"Persona file not found: {persona_path}, using defaults")
            return {
                'auto_join': {
                    'standup': True,
                    'all_hands': False,
                    'one_on_one': True,
                    'default': False,
                }
            }

    def _determine_meeting_type(self, meeting: Dict[str, Any]) -> str:
        """Determine meeting type from title/description."""
        title = meeting.get('summary', '').lower()
        description = meeting.get('description', '').lower()

        if any(word in title or word in description for word in ['standup', 'daily']):
            return 'standup'
        elif any(word in title or word in description for word in ['all hands', 'all-hands']):
            return 'all_hands'
        elif any(word in title or word in description for word in ['1:1', 'one-on-one', '1on1']):
            return 'one_on_one'
        elif any(word in title or word in description for word in ['sprint review', 'sprint demo', 'sprint retrospective']):
            return 'sprint_review'
        else:
            return 'default'

    async def create_meeting(self, 
                           summary: str, 
                           description: str, 
                           start_time: datetime, 
                           end_time: datetime, 
                           attendees: List[str], 
                           meet_link: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a new Google Calendar meeting."""
        if not self.is_authenticated():
            raise RuntimeError("Not authenticated with Google Calendar")

        try:
            # Format time for Google Calendar API
            start_time_str = start_time.isoformat()
            end_time_str = end_time.isoformat()
            
            # Create event
            event = {
                'summary': summary,
                'description': description,
                'start': {
                    'dateTime': start_time_str,
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_time_str,
                    'timeZone': 'UTC',
                },
                'attendees': [{'email': email} for email in attendees],
                'reminders': {
                    'useDefault': True,
                },
            }
            
            # Add Google Meet conference if requested
            if meet_link:
                event['conferenceData'] = {
                    'createRequest': {
                        'requestId': f"meeting-{datetime.now().timestamp()}",
                        'conferenceSolutionKey': {
                            'type': 'hangoutsMeet'
                        },
                    }
                }
            
            # Create the event
            created_event = self.service.events().insert(
                calendarId='primary',
                body=event,
                conferenceDataVersion=1
            ).execute()
            
            return {
                'id': created_event['id'],
                'summary': created_event['summary'],
                'meet_url': created_event.get('hangoutLink') or created_event.get('conferenceData', {}).get('entryPoints', [{}])[0].get('uri'),
                'start': created_event['start'],
                'end': created_event['end']
            }

        except HttpError as error:
            logger.error(f"Google Calendar API error: {error}")
            return None
        except Exception as e:
            logger.error(f"Failed to create meeting: {e}")
            return None

    async def get_calendar_list(self) -> List[Dict[str, Any]]:
        """Get list of accessible calendars."""
        if not self.is_authenticated():
            raise RuntimeError("Not authenticated with Google Calendar")

        try:
            calendar_list = self.service.calendarList().list().execute()
            return calendar_list.get('items', [])
        except Exception as e:
            logger.error(f"Failed to get calendar list: {e}")
            return []

    def revoke_access(self) -> bool:
        """Revoke Google Calendar API access."""
        try:
            if self.credentials and self.credentials.valid:
                # Revoke the token
                self.credentials.revoke(Request())
                
                # Remove the token file
                token_path = os.path.join(settings.app.data_dir, 'google_calendar_token.json')
                if os.path.exists(token_path):
                    os.remove(token_path)
                
                self.credentials = None
                self.service = None
                logger.info("Google Calendar access revoked")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to revoke access: {e}")
            return False

    async def close(self) -> None:
        """Clean up resources."""
        self.credentials = None
        self.service = None
        logger.info("Google Calendar integration closed")