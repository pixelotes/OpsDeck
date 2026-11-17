from abc import ABC, abstractmethod
import requests
import hashlib
import json
import time
import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Any

if TYPE_CHECKING:
    from src.models.connectors import ConnectorReport

logger = logging.getLogger(__name__)


class PaginationStrategy:
    """Define pagination strategies"""
    CURSOR = 'cursor'          # nextPageToken / cursor in the response body
    OFFSET = 'offset'          # offset and limit query parameters
    PAGE = 'page'              # page number and page size query parameters
    LINK_HEADER = 'link'       # RFC 5988 Link headers


class BaseConnector(ABC):
    """
    Abstract base class for API connectors.
    Handles authentication, pagination, retries, and storage.
    """
    
    def __init__(self, task, subtask):
        self.task = task
        self.subtask = subtask
        self.session = requests.Session()
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        self.rate_limit_delay = 60  # seconds
        
    @abstractmethod
    def authenticate(self) -> None:
        """
        Set up authentication for the API.
        Should configure self.session with necessary headers/auth.
        """
        pass
    
    @abstractmethod
    def get_base_url(self) -> str:
        """Return the base URL for this connector."""
        pass
    
    @abstractmethod
    def parse_items(self, response_data: Dict) -> List[Dict]:
        """
        Extract items from API response.
        
        Args:
            response_data: Parsed JSON response
            
        Returns:
            List of items from this page
        """
        pass
    
    @abstractmethod
    def get_pagination_token(self, response_data: Dict) -> Optional[str]:
        """
        Extract next page token from response.
        
        Args:
            response_data: Parsed JSON response
            
        Returns:
            Next page token or None if no more pages
        """
        pass
    
    def build_request_url(self, page_token: Optional[str] = None) -> str:
        """
        Build the complete request URL with pagination.
        
        Args:
            page_token: Pagination token from previous response
            
        Returns:
            Complete URL for the request
        """
        base_url = self.get_base_url()
        endpoint = self.subtask.endpoint
        url = f"{base_url}{endpoint}"
        
        # Add pagination parameter based on strategy
        if page_token:
            if self.subtask.pagination_type == PaginationStrategy.CURSOR:
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}pageToken={page_token}"
            elif self.subtask.pagination_type == PaginationStrategy.OFFSET:
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}offset={page_token}"
            elif self.subtask.pagination_type == PaginationStrategy.PAGE:
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}page={page_token}"
                
        return url
    
    def fetch_page(self, url: str) -> requests.Response:
        """
        Fetch a single page with retry logic.
        
        Args:
            url: URL to fetch
            
        Returns:
            Response object
        """
        logger.debug(f"[{self.task.service}] Fetching URL: {url}")
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=30)
                logger.debug(f"[{self.task.service}] Response status: {response.status_code}")
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', self.rate_limit_delay))
                    logger.warning(f"[{self.task.service}] Rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue
                
                response.raise_for_status()
                logger.info(f"[{self.task.service}] Successfully fetched {url} ({response.status_code})")
                return response
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"[{self.task.service}] Attempt {attempt + 1}/{self.max_retries} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    logger.error(f"[{self.task.service}] All retry attempts exhausted for {url}")
                    raise
                retry_delay = self.retry_delay * (attempt + 1)
                logger.debug(f"[{self.task.service}] Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
        
        raise ConnectionError(f"Failed to fetch {url} after {self.max_retries} attempts")
    
    def fetch_all_pages(self) -> Dict[str, Any]:
        """
        Fetch all pages using pagination.
        This is the main orchestrator method.
        
        Returns:
            Dictionary with 'items', 'total_count', 'pages_fetched', etc.
        """
        logger.info(f"[{self.task.service}] Starting fetch_all_pages for subtask: {self.subtask.name}")
        logger.debug(f"[{self.task.service}] Endpoint: {self.subtask.endpoint}")
        logger.debug(f"[{self.task.service}] Pagination type: {self.subtask.pagination_type}")
        
        try:
            self.authenticate()
            logger.info(f"[{self.task.service}] Authentication successful")
        except Exception:
            logger.exception(f"[{self.task.service}] Authentication failed")
            raise
        
        all_items = []
        page_token = None
        page_count = 0
        start_time = time.time()
        
        try:
            while True:
                page_count += 1
                logger.debug(f"[{self.task.service}] Fetching page {page_count} (token: {page_token})")
                url = self.build_request_url(page_token)
                
                response = self.fetch_page(url)
                response_data = response.json()
                
                # Extract items from this page
                items = self.parse_items(response_data)
                logger.debug(f"[{self.task.service}] Page {page_count}: {len(items)} items")
                all_items.extend(items)
                
                # Check for next page
                page_token = self.get_pagination_token(response_data)
                if not page_token:
                    logger.debug(f"[{self.task.service}] No more pages to fetch")
                    break
                    
                # Safety check: don't fetch more than 100 pages
                if page_count >= 100:
                    logger.warning(f"[{self.task.service}] Reached maximum page limit (100)")
                    break
            
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[{self.task.service}] Completed: {len(all_items)} total items from {page_count} pages in {duration_ms}ms")
            
            return {
                'items': all_items,
                'total_count': len(all_items),
                'pages_fetched': page_count,
                'duration_ms': duration_ms
            }
        except Exception:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.exception(f"[{self.task.service}] fetch_all_pages failed after {page_count} pages and {duration_ms}ms")
            raise
    
    def save_report(self, data: Dict) -> 'ConnectorReport':
        """
        Save execution result to database.
        
        Args:
            data: Result dictionary from fetch_all_pages()
            
        Returns:
            ConnectorReport instance
        """
        from src.extensions import db
        from src.models.connectors import ConnectorReport
        
        # Serialize data
        json_data = json.dumps(data, sort_keys=True, indent=2)
        checksum = hashlib.sha256(json_data.encode()).hexdigest()
        
        report = ConnectorReport(
            subtask_id=self.subtask.id,
            data=json_data,
            checksum=checksum,
            record_count=data.get('total_count', 0),
            fetch_duration_ms=data.get('duration_ms', 0)
        )
        
        db.session.add(report)
        db.session.commit()
        
        return report
