"""Shared literal constants for model definitions.

Leaf module (imports nothing from the package) so it can be imported by any
model module without risking circular imports. Centralises frequently-repeated
SQLAlchemy relationship literals (avoids duplication, Sonar S1192).
"""

# Cascade applied to owning relationships so children are deleted with the parent.
CASCADE_ALL_DELETE_ORPHAN = 'all, delete-orphan'

# Relationship loading strategy returning a query instead of a collection.
LAZY_DYNAMIC = 'dynamic'
