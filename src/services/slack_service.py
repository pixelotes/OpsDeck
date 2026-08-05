"""
Slack Service Module

Provides integration with Slack API for sending messages.
Implements email-to-user-ID resolution with caching to minimize API calls.
"""
import os
import re
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SlackRateLimitError(Exception):
    """
    Raised when Slack API returns a rate limit error.
    The dispatcher can catch this to re-queue the message for later processing.
    """
    pass

class SlackService:
    """
    Singleton service for Slack API interactions.
    Provides email-to-user-ID resolution with caching and message sending.
    
    Usage:
        slack = SlackService()
        user_id = slack.resolve_user_by_email("user@company.com")
        if user_id:
            slack.send_message(user_id, "Hello!")
    """
    
    _instance = None
    _client = None
    
    # Cache settings
    CACHE_TTL_SECONDS = 300  # 5 minutes
    
    def __new__(cls):
        """Singleton pattern - ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the Slack client if not already done."""
        if self._initialized:
            return
        
        self._email_cache = {}  # {email: {'user_id': 'U123', 'timestamp': 123456}}
        self._initialized = True
        
        # Lazy-load the client when first needed
        self._client = None
    
    def _get_client(self):
        """
        Get or create the Slack WebClient.
        Returns None if token is not configured.
        """
        if self._client is not None:
            return self._client
        
        try:
            from slack_sdk import WebClient
            
            token = os.environ.get('SLACK_BOT_TOKEN')
            if not token:
                logger.warning("SLACK_BOT_TOKEN not configured. Slack notifications disabled.")
                return None
            
            self._client = WebClient(token=token)
            logger.info("Slack WebClient initialized successfully.")
            return self._client
        except ImportError:
            logger.error("slack_sdk not installed. Run: pip install slack_sdk")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Slack client: {e}")
            return None
    
    @property
    def is_configured(self) -> bool:
        """Check if Slack integration is properly configured."""
        return self._get_client() is not None
    
    def resolve_user_by_email(self, email: str) -> Optional[str]:
        """
        Resolve a Slack user ID from an email address.
        
        Uses in-memory caching to avoid repeated API calls for the same email.
        Cache entries expire after CACHE_TTL_SECONDS.
        
        Args:
            email: The email address to look up
            
        Returns:
            Slack User ID (e.g., 'U023BECGF') or None if not found
        """
        if not email:
            return None
        
        email = email.lower().strip()
        current_time = time.time()
        
        # Check cache first
        if email in self._email_cache:
            cached = self._email_cache[email]
            if current_time - cached['timestamp'] < self.CACHE_TTL_SECONDS:
                logger.debug(f"Cache hit for email: {email}")
                return cached['user_id']
            else:
                # Cache expired, remove it
                del self._email_cache[email]
        
        # Get Slack client
        client = self._get_client()
        if not client:
            return None
        
        try:
            
            response = client.users_lookupByEmail(email=email)
            
            if response['ok']:
                user_id = response['user']['id']
                
                # Cache the result
                self._email_cache[email] = {
                    'user_id': user_id,
                    'timestamp': current_time
                }
                
                logger.info(f"Resolved email {email} to Slack user {user_id}")
                return user_id
            else:
                logger.warning(f"Slack API returned not ok for email {email}: {response}")
                return None
                
        except Exception as e:
            # Handle specific errors
            error_str = str(e)
            if 'users_not_found' in error_str:
                logger.info(f"User not found in Slack for email: {email}")
            elif 'invalid_auth' in error_str or 'token_revoked' in error_str:
                logger.error(f"Slack authentication error: {e}")
            else:
                logger.error(f"Error looking up Slack user by email {email}: {e}")
            return None
    
    def send_message(self, target_id: str, text: str) -> bool:
        """
        Send a message to a Slack user (DM) or channel.
        
        Args:
            target_id: Slack User ID (starts with 'U') or Channel ID (starts with 'C')
            text: Message text (Slack markdown supported: *bold*, _italic_, <url|text>)
            
        Returns:
            True if message was sent successfully, False otherwise
        """
        if not target_id or not text:
            logger.warning("send_message called with empty target_id or text")
            return False
        
        client = self._get_client()
        if not client:
            return False
        
        try:
            
            response = client.chat_postMessage(
                channel=target_id,
                text=text
            )
            
            if response['ok']:
                logger.info(f"Successfully sent Slack message to {target_id}")
                return True
            else:
                logger.error(f"Slack API error sending message: {response}")
                return False
                
        except Exception as e:
            error_str = str(e)
            # Check for rate limiting - raise specific exception for re-queue
            if 'ratelimited' in error_str:
                logger.warning(f"Slack rate limited when sending to {target_id}")
                raise SlackRateLimitError(f"Rate limited sending to {target_id}")
            if 'channel_not_found' in error_str:
                logger.error(f"Slack channel/user not found: {target_id}")
            elif 'not_in_channel' in error_str:
                logger.error(f"Bot not in channel: {target_id}")
            elif 'invalid_auth' in error_str or 'token_revoked' in error_str:
                logger.error(f"Slack authentication error: {e}")
            else:
                logger.error(f"Error sending Slack message to {target_id}: {e}")
            return False
    
    def clear_cache(self):
        """Clear the email-to-user-ID cache."""
        self._email_cache.clear()
        logger.info("Slack email cache cleared.")


def strip_html_for_slack(html_content: str) -> str:
    """
    Convert HTML content to Slack-compatible plain text.
    
    Performs basic conversion:
    - Strips HTML tags
    - Preserves line breaks from <br> and <p> tags
    - Converts <a href="url">text</a> to Slack link format <url|text>
    
    Args:
        html_content: HTML string to convert
        
    Returns:
        Plain text suitable for Slack
    """
    if not html_content:
        return ""
    
    text = html_content
    
    # Convert links to Slack format before stripping tags
    # <a href="url">text</a> -> <url|text>
    link_pattern = r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>'
    text = re.sub(link_pattern, r'<\1|\2>', text, flags=re.IGNORECASE)
    
    # Convert <br> and </p> to newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    
    # Convert list items to bullet points
    text = re.sub(r'<li[^>]*>', '• ', text, flags=re.IGNORECASE)
    
    # Convert headers to bold
    text = re.sub(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', r'*\1*\n', text, flags=re.IGNORECASE)
    
    # Convert <strong> and <b> to Slack bold
    text = re.sub(r'<(?:strong|b)[^>]*>([^<]+)</(?:strong|b)>', r'*\1*', text, flags=re.IGNORECASE)
    
    # Convert <em> and <i> to Slack italic
    text = re.sub(r'<(?:em|i)[^>]*>([^<]+)</(?:em|i)>', r'_\1_', text, flags=re.IGNORECASE)
    
    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode common HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    
    # Clean up multiple newlines and whitespace
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    text = text.strip()
    
    return text


def format_slack_notification(subject: str, body_html: str, opsdeck_url: str = None) -> str:
    """
    Format a notification for Slack.
    
    Creates a clean, readable Slack message with:
    - Emoji prefix
    - Subject as header
    - Stripped body text (truncated if too long)
    - Link to OpsDeck if provided
    
    Args:
        subject: Email subject line
        body_html: HTML body content
        opsdeck_url: Optional URL to the relevant OpsDeck page
        
    Returns:
        Formatted Slack message
    """
    parts = []
    
    # Header with emoji
    parts.append(f"📋 *{subject}*")
    parts.append("")  # Empty line
    
    # Body (stripped and truncated)
    body_text = strip_html_for_slack(body_html)
    if len(body_text) > 500:
        body_text = body_text[:497] + "..."
    
    if body_text:
        parts.append(body_text)
        parts.append("")
    
    # Link to OpsDeck
    if opsdeck_url:
        parts.append(f"<{opsdeck_url}|📎 Ver en OpsDeck>")
    
    return "\n".join(parts)
