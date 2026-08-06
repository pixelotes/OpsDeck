"""
Enhanced Search Service with Faceted Filtering

Provides unified search across multiple entity types with dynamic faceted filters,
saved searches, and result previews.
"""
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy import or_, func
from sqlalchemy.orm import Query
from ..extensions import db
from ..models.auth import User
from ..models.assets import Asset
from ..models.uar import UARExecution, UARFinding
from ..models.security import FrameworkControl, SecurityIncident
from ..models.procurement import Supplier, Subscription
from ..models.services import BusinessService
from src.utils.timezone_helper import now



class SearchService:
    """
    Unified search service with faceted filtering capabilities.
    """

    SEARCHABLE_ENTITIES = {
        'assets': {
            'model': Asset,
            'fields': ['name', 'serial_number', 'asset_tag', 'notes'],
            'filters': ['status', 'location', 'assigned_to_id'],
            'display_fields': ['name', 'serial_number', 'status', 'assigned_to']
        },
        'users': {
            'model': User,
            'fields': ['name', 'email', 'role', 'department'],
            'filters': ['role', 'is_archived'],
            'display_fields': ['name', 'email', 'role', 'department']
        },
        'uar_executions': {
            'model': UARExecution,
            'fields': ['comparison.name'],
            'filters': ['status', 'started_at'],
            'display_fields': ['comparison.name', 'status', 'findings_count', 'started_at']
        },
        'uar_findings': {
            'model': UARFinding,
            'fields': ['key_value', 'description'],
            'filters': ['finding_type', 'severity', 'status', 'assigned_to_id'],
            'display_fields': ['key_value', 'finding_type', 'severity', 'status']
        },
        'compliance_controls': {
            'model': FrameworkControl,
            'fields': ['control_id', 'name', 'description'],
            'filters': ['framework_id'],
            'display_fields': ['control_id', 'name', 'framework.name']
        },
        'security_incidents': {
            'model': SecurityIncident,
            'fields': ['title', 'description', 'source'],
            'filters': ['status', 'severity', 'assigned_to_id'],
            'display_fields': ['title', 'status', 'severity', 'created_at']
        },
        'suppliers': {
            'model': Supplier,
            'fields': ['name', 'website', 'notes'],
            'filters': ['compliance_status', 'country'],
            'display_fields': ['name', 'compliance_status', 'country']
        },
        'subscriptions': {
            'model': Subscription,
            'fields': ['name', 'description', 'vendor'],
            'filters': ['status', 'renewal_type'],
            'display_fields': ['name', 'vendor', 'status', 'next_renewal_date']
        },
        'business_services': {
            'model': BusinessService,
            'fields': ['name', 'description', 'owner'],
            'filters': ['criticality', 'status'],
            'display_fields': ['name', 'criticality', 'status', 'owner']
        }
    }

    def __init__(self):
        self.supported_entities = list(self.SEARCHABLE_ENTITIES.keys())

    def search(
        self,
        query: str,
        entity_types: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Perform unified search across multiple entity types.

        Args:
            query: Search query string
            entity_types: List of entity types to search (default: all)
            filters: Faceted filters to apply
            limit: Maximum results per entity type
            offset: Pagination offset

        Returns:
            dict with search results, facets, and metadata
        """
        if entity_types is None:
            entity_types = self.supported_entities

        results = {}
        total_count = 0

        for entity_type in entity_types:
            if entity_type not in self.SEARCHABLE_ENTITIES:
                continue

            entity_results, count = self._search_entity(
                entity_type, query, filters or {}, limit, offset
            )
            results[entity_type] = entity_results
            total_count += count

        # Generate facets (available filter options)
        facets = self._generate_facets(entity_types, filters or {})

        return {
            'query': query,
            'results': results,
            'facets': facets,
            'total_count': total_count,
            'entity_types': entity_types
        }

    def _search_entity(
        self,
        entity_type: str,
        query: str,
        filters: Dict[str, Any],
        limit: int,
        offset: int
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Search within a specific entity type.

        Args:
            entity_type: Type of entity to search
            query: Search query
            filters: Filters to apply
            limit: Result limit
            offset: Pagination offset

        Returns:
            tuple: (list of results, total count)
        """
        config = self.SEARCHABLE_ENTITIES[entity_type]
        model = config['model']
        search_fields = config['fields']

        # Build base query
        base_query = model.query

        # Apply search across fields
        if query:
            search_conditions = []
            for field in search_fields:
                if '.' in field:
                    # Handle relationship fields (e.g., 'comparison.name')
                    continue  # skipped: matching this field would need a join
                else:
                    column = getattr(model, field, None)
                    if column is not None:
                        search_conditions.append(column.ilike(f'%{query}%'))

            if search_conditions:
                base_query = base_query.filter(or_(*search_conditions))

        # Apply faceted filters
        base_query = self._apply_filters(base_query, model, filters)

        # Get total count
        total_count = base_query.count()

        # Apply pagination
        results = base_query.limit(limit).offset(offset).all()

        # Format results
        formatted_results = [
            self._format_result(entity_type, result)
            for result in results
        ]

        return formatted_results, total_count

    def _apply_filters(
        self,
        query: Query,
        model: Any,
        filters: Dict[str, Any]
    ) -> Query:
        """
        Apply faceted filters to query.

        Args:
            query: SQLAlchemy query
            model: Model class
            filters: Filter dictionary

        Returns:
            Filtered query
        """
        for filter_name, filter_value in filters.items():
            if filter_value is None or filter_value == '':
                continue

            # Handle date range filters
            if filter_name == 'date_from':
                date_field = getattr(model, 'created_at', None)
                if date_field is not None:
                    query = query.filter(date_field >= filter_value)

            elif filter_name == 'date_to':
                date_field = getattr(model, 'created_at', None)
                if date_field is not None:
                    query = query.filter(date_field <= filter_value)

            # Handle list filters (multiple selection)
            elif isinstance(filter_value, list):
                column = getattr(model, filter_name, None)
                if column is not None:
                    query = query.filter(column.in_(filter_value))

            # Handle single value filters
            else:
                column = getattr(model, filter_name, None)
                if column is not None:
                    query = query.filter(column == filter_value)

        return query

    def _format_result(self, entity_type: str, result: Any) -> Dict[str, Any]:
        """
        Format a search result for display.

        Args:
            entity_type: Type of entity
            result: Model instance

        Returns:
            Formatted result dictionary
        """
        config = self.SEARCHABLE_ENTITIES[entity_type]
        display_fields = config['display_fields']

        formatted = {
            'id': result.id,
            'entity_type': entity_type,
            'url': self._get_detail_url(entity_type, result.id),
            'fields': {}
        }

        for field in display_fields:
            if '.' in field:
                # Handle relationship fields
                parts = field.split('.')
                value = result
                for part in parts:
                    value = getattr(value, part, None)
                    if value is None:
                        break
                formatted['fields'][field] = str(value) if value else 'N/A'
            else:
                value = getattr(result, field, None)
                if isinstance(value, datetime):
                    formatted['fields'][field] = value.strftime('%Y-%m-%d %H:%M')
                elif value is not None:
                    formatted['fields'][field] = str(value)
                else:
                    formatted['fields'][field] = 'N/A'

        return formatted

    def _get_detail_url(self, entity_type: str, entity_id: int) -> str:
        """
        Get detail page URL for an entity.

        Args:
            entity_type: Type of entity
            entity_id: Entity ID

        Returns:
            URL string
        """
        from flask import url_for

        url_map = {
            'assets': lambda id: url_for('assets.asset_detail', id=id),
            'users': lambda id: url_for('users.user_detail', id=id),
            'uar_executions': lambda id: url_for('compliance.uar_execution_detail', execution_id=id),
            'uar_findings': lambda id: f'#finding-{id}',  # Anchor within execution page
            'compliance_controls': lambda id: url_for('frameworks.control_detail', id=id),
            'security_incidents': lambda id: url_for('security.incident_detail', id=id),
            'suppliers': lambda id: url_for('suppliers.supplier_detail', id=id),
            'subscriptions': lambda id: url_for('subscriptions.subscription_detail', id=id),
            'business_services': lambda id: url_for('services.service_detail', id=id)
        }

        url_func = url_map.get(entity_type)
        return url_func(entity_id) if url_func else '#'

    def _generate_facets(
        self,
        entity_types: List[str],
        current_filters: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate available facet options for filtering.

        Args:
            entity_types: Entity types being searched
            current_filters: Currently applied filters

        Returns:
            Dictionary of facets with counts
        """
        facets = {}

        # Common facets across entities
        common_facets = {
            'status': self._get_status_facets(entity_types),
            'severity': self._get_severity_facets(entity_types),
            'date_range': self._get_date_range_presets()
        }

        facets.update(common_facets)

        return facets

    def _get_status_facets(self, entity_types: List[str]) -> List[Dict[str, Any]]:
        """Get status filter options with counts."""
        status_options = []

        for entity_type in entity_types:
            config = self.SEARCHABLE_ENTITIES.get(entity_type)
            if not config or 'status' not in config['filters']:
                continue

            model = config['model']
            status_column = getattr(model, 'status', None)

            if status_column is not None:
                # Get unique status values with counts
                results = db.session.query(
                    status_column,
                    func.count(model.id)
                ).group_by(status_column).all()

                for status, count in results:
                    status_options.append({
                        'value': status,
                        'label': status.title() if status else 'Unknown',
                        'count': count,
                        'entity_type': entity_type
                    })

        return status_options

    def _get_severity_facets(self, entity_types: List[str]) -> List[Dict[str, Any]]:
        """Get severity filter options with counts."""
        severity_options = []

        for entity_type in entity_types:
            config = self.SEARCHABLE_ENTITIES.get(entity_type)
            if not config or 'severity' not in config['filters']:
                continue

            model = config['model']
            severity_column = getattr(model, 'severity', None)

            if severity_column is not None:
                results = db.session.query(
                    severity_column,
                    func.count(model.id)
                ).group_by(severity_column).all()

                for severity, count in results:
                    severity_options.append({
                        'value': severity,
                        'label': severity.upper() if severity else 'Unknown',
                        'count': count,
                        'entity_type': entity_type
                    })

        return severity_options

    def _get_date_range_presets(self) -> List[Dict[str, Any]]:
        """Get preset date range options."""
        current_time = now()

        return [
            {
                'label': 'Last 7 days',
                'value': 'last_7_days',
                'date_from': (current_time - timedelta(days=7)).isoformat(),
                'date_to': current_time.isoformat()
            },
            {
                'label': 'Last 30 days',
                'value': 'last_30_days',
                'date_from': (current_time - timedelta(days=30)).isoformat(),
                'date_to': current_time.isoformat()
            },
            {
                'label': 'Last 90 days',
                'value': 'last_90_days',
                'date_from': (current_time - timedelta(days=90)).isoformat(),
                'date_to': current_time.isoformat()
            },
            {
                'label': 'This year',
                'value': 'this_year',
                'date_from': current_time.replace(month=1, day=1, hour=0, minute=0).isoformat(),
                'date_to': current_time.isoformat()
            }
        ]

    def save_search(
        self,
        user_id: int,
        name: str,
        query: str,
        entity_types: List[str],
        filters: Dict[str, Any]
    ) -> int:
        """
        Save a search configuration for later reuse.

        Args:
            user_id: User ID
            name: Search name
            query: Search query
            entity_types: Entity types
            filters: Applied filters

        Returns:
            Saved search ID
        """
        # TODO: Implement SavedSearch model and persistence
        # For now, return dummy ID
        return 1


# Singleton instance
_search_service = None


def get_search_service() -> SearchService:
    """Get singleton instance of SearchService."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service
