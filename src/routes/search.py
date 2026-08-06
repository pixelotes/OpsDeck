"""
Search Routes

Unified search interface with faceted filtering across all entity types.
"""
from flask import Blueprint, render_template, request, jsonify, session
from datetime import datetime
from ..services.search_service import get_search_service
from .main import login_required

search_bp = Blueprint('search', __name__)


@search_bp.route('/', methods=['GET'])
@login_required
def search_home():
    """
    Main search interface.
    """
    return render_template('search/search.html')


@search_bp.route('/api/search', methods=['GET', 'POST'])
@login_required
def api_search():
    """
    API endpoint for search queries with faceted filtering.

    Query Parameters:
        q: Search query string
        entity_types: Comma-separated list of entity types
        status: Filter by status
        severity: Filter by severity
        date_from: Start date (ISO format)
        date_to: End date (ISO format)
        limit: Results per entity type (default: 50)
        offset: Pagination offset (default: 0)

    Returns:
        JSON with search results, facets, and metadata
    """
    search_service = get_search_service()

    # Get query parameters
    query = request.args.get('q', '').strip()
    entity_types_str = request.args.get('entity_types', '')
    entity_types = [et.strip() for et in entity_types_str.split(',') if et.strip()] if entity_types_str else None

    # Build filters
    filters = {}

    # Status filter
    status = request.args.get('status')
    if status:
        filters['status'] = status

    # Severity filter (can be multiple)
    severity = request.args.getlist('severity')
    if severity:
        filters['severity'] = severity

    # Date range filters
    date_from = request.args.get('date_from')
    if date_from:
        try:
            filters['date_from'] = datetime.fromisoformat(date_from)
        except ValueError:
            pass

    date_to = request.args.get('date_to')
    if date_to:
        try:
            filters['date_to'] = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    # Assigned to filter
    assigned_to_id = request.args.get('assigned_to_id', type=int)
    if assigned_to_id:
        filters['assigned_to_id'] = assigned_to_id

    # Finding type filter (for UAR findings)
    finding_type = request.args.get('finding_type')
    if finding_type:
        filters['finding_type'] = finding_type

    # Pagination
    limit = request.args.get('limit', type=int, default=50)
    offset = request.args.get('offset', type=int, default=0)

    # Perform search
    results = search_service.search(
        query=query,
        entity_types=entity_types,
        filters=filters,
        limit=limit,
        offset=offset,
        user_id=session.get('user_id')
    )

    return jsonify(results)


@search_bp.route('/api/facets', methods=['GET'])
@login_required
def api_get_facets():
    """
    Get available facet options for given entity types.

    Query Parameters:
        entity_types: Comma-separated list of entity types

    Returns:
        JSON with facet options and counts
    """
    search_service = get_search_service()

    entity_types_str = request.args.get('entity_types', '')
    entity_types = [et.strip() for et in entity_types_str.split(',') if et.strip()] if entity_types_str else None

    # Facet counts are data. Asking for the status breakdown of an entity type you cannot
    # search would otherwise report how many of each there are.
    permitted = search_service.readable_entities(session.get('user_id'))
    entity_types = [et for et in entity_types if et in permitted] if entity_types else permitted

    facets = search_service._generate_facets(entity_types, {})

    return jsonify(facets)


@search_bp.route('/api/saved-searches', methods=['GET'])
@login_required
def api_get_saved_searches():
    """
    Get user's saved searches.

    Returns:
        JSON list of saved searches
    """
    # TODO: Implement when SavedSearch model is created
    return jsonify([])


@search_bp.route('/api/saved-searches', methods=['POST'])
@login_required
def api_save_search():
    """
    Save a search configuration.

    Request Body:
        name: Search name
        query: Search query
        entity_types: List of entity types
        filters: Filter configuration

    Returns:
        JSON with saved search ID
    """
    search_service = get_search_service()
    data = request.json

    name = data.get('name')
    if not name:
        return jsonify({'error': 'Name is required'}), 400

    search_id = search_service.save_search(
        user_id=session.get('user_id'),
        name=name,
        query=data.get('query', ''),
        entity_types=data.get('entity_types', []),
        filters=data.get('filters', {})
    )

    return jsonify({
        'success': True,
        'id': search_id,
        'message': f'Search "{name}" saved successfully'
    })


@search_bp.route('/api/suggestions', methods=['GET'])
@login_required
def api_get_suggestions():
    """
    Get search query suggestions based on partial input.

    Query Parameters:
        q: Partial query string
        entity_type: Entity type for suggestions

    Returns:
        JSON list of suggestions
    """

    # TODO: Implement intelligent suggestions based on entity type
    # For now, return empty list
    suggestions = []

    return jsonify(suggestions)
