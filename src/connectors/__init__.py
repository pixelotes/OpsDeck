"""
API connectors that sync data from external services (Settings > API Connectors).
Contains API connectors for external services.
"""

from .base import BaseConnector, PaginationStrategy
from .microsoft import MicrosoftConnector
from .aws import AWSConnector
from .google import GoogleWorkspaceConnector as GoogleConnector
from .github import GitHubConnector
from .jumpcloud import JumpCloudConnector
from .atlassian import AtlassianConnector

__all__ = [
    'BaseConnector', 
    'PaginationStrategy', 
    'MicrosoftConnector',
    'AWSConnector',
    'GoogleConnector',
    'GitHubConnector',
    'JumpCloudConnector',
    'AtlassianConnector'
]
