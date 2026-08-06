from src.models.services import ServiceDependency


def get_full_dependency_tree(root_service, direction='upstream', visited=None, edges=None):
    """
    Recorre recursivamente las dependencias.
    direction: 'upstream' (what this depends on) or 'downstream' (what depends on it).
    """
    if visited is None: visited = set()
    if edges is None: edges = []

    visited.add(root_service.id)

    if direction == 'upstream':
        links = ServiceDependency.query.filter_by(child_id=root_service.id).all()
    else:
        links = ServiceDependency.query.filter_by(parent_id=root_service.id).all()

    for link in links:
        if direction == 'upstream':
            related_service = link.parent
            edges.append({
                'from': related_service.id,
                'from_name': related_service.name,
                'to': root_service.id,
                'to_name': root_service.name,
                'label': link.label.value if link.label else None
            })
        else:
            related_service = link.child
            edges.append({
                'from': root_service.id,
                'from_name': root_service.name,
                'to': related_service.id,
                'to_name': related_service.name,
                'label': link.label.value if link.label else None
            })

        if related_service.id not in visited:
            get_full_dependency_tree(related_service, direction, visited, edges)

    return edges
