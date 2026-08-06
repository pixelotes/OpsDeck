"""Shared conventions for the internal JSON API.

The application has two API layers and they are not the same thing. ``/api/v1`` is
flask-smorest: bearer tokens, marshmallow schemas, Swagger, a contract with third
parties. This module serves the *other* one — the ~80 JSON endpoints scattered across
the module blueprints that exist so the application's own JavaScript can talk to it:
TomSelect remote sources, the calendar feed, the kanban drag&drop, the Gantt.

That layer deliberately has no versioning, no schemas and no Swagger entry: its only
consumer ships in the same commit it does, and a contract between a file and itself is
paperwork. What it does need is a single answer to "who am I and how do I fail", which
is what lives here.

``json_endpoint`` is the important part. The login guard used to decide whether a
request was an API call by looking for ``/api/`` in the path, which silently excluded
the 44 JSON endpoints that do not follow that naming — they answered an unauthenticated
fetch() with a 302 to the HTML login page, and the client parsed the login form as if it
were the response. Membership is now declared by the view itself, so the ``/api/``
prefix is a naming convention again instead of the thing security depends on.
"""
from functools import wraps

from flask import current_app, jsonify, request
from werkzeug.exceptions import BadRequest, HTTPException

from ..extensions import db
# Re-exported so a module writing JSON endpoints has one import, not two: the
# permission decorator and the response convention always travel together.
from ..services.permissions_service import requires_permission_api  # noqa: F401

#: Attribute stamped on a view to declare it answers with JSON.
#:
#: An attribute rather than a registry keyed by name because functools.wraps copies
#: __dict__ outwards, so the mark survives any correctly-written decorator stacked
#: above it and there is no endpoint name to resolve or keep in sync.
JSON_VIEW_ATTR = '__opsdeck_json_endpoint__'


def json_endpoint(f):
    """Declare that this view answers with JSON, so the guards fail it as JSON.

    Marking only: it does not wrap the call or change behaviour on its own. Use
    ``api_endpoint`` for a view that should also turn exceptions into JSON.
    """
    setattr(f, JSON_VIEW_ATTR, True)
    return f


def view_is_json(view):
    """True when `view` was declared with json_endpoint or api_endpoint."""
    return bool(getattr(view, JSON_VIEW_ATTR, False))


def request_wants_json():
    """Whether the current request should be answered with JSON rather than HTML.

    Checked in this order:

    1. the view's own declaration — authoritative, and the reason this function exists;
    2. ``/api/`` in the path — kept so /api/v1 and the 34 endpoints already following
       the convention behave identically whether or not anyone marked them;
    3. an explicit ``Accept: application/json``, which is the only signal available
       when the request never reaches a view (a 404, or a body rejected before routing).

    Must not raise: it runs inside error handlers, including the one for a request with
    no matching endpoint at all.
    """
    endpoint = getattr(request, 'endpoint', None)
    if endpoint:
        view = current_app.view_functions.get(endpoint)
        if view is not None and view_is_json(view):
            return True

    if '/api/' in (request.path or ''):
        return True

    return request.accept_mimetypes.best == 'application/json'


def json_error(message, status):
    """A JSON error body with the shape every internal endpoint uses."""
    return jsonify({'error': message}), status


def api_endpoint(f):
    """Make a handler fail as JSON instead of as an HTML error page.

    ValueError/TypeError are treated as client errors because the only place they can
    surface is coercing request data (int('abc') and friends); anything else is a bug,
    so it rolls back, logs with a stack trace, and returns 500.

    Implies json_endpoint: a view that reports its errors as JSON is a JSON view, and
    letting the two drift apart would mean an endpoint whose 500 is JSON but whose 401
    is a login page.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except BadRequest as error:
            return json_error(error.description or 'Malformed request body.', 400)
        except HTTPException:
            # abort() and friends already carry the right status; turning those into a
            # 500 below would hide them.
            raise
        except (ValueError, TypeError):
            return json_error('Invalid field value.', 400)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Unhandled error in %s', f.__qualname__)
            return json_error('Internal error.', 500)

    return json_endpoint(wrapper)


def body():
    """The parsed JSON body, or an empty dict when there is none.

    A body that is present but unparseable is an error rather than an empty dict:
    treating garbage as "no fields supplied" would make a broken client look like a
    successful no-op. A missing body stays valid, since DELETE and some POSTs have none.
    """
    parsed = request.get_json(silent=True)
    if parsed is None:
        if request.get_data():
            raise BadRequest('Body is not valid JSON.')
        return {}
    if not isinstance(parsed, dict):
        raise BadRequest('Body must be a JSON object.')
    return parsed


def field_body():
    """Body for endpoints that map keys onto model fields, all of which are scalar.

    Rejecting structures once, up front, is what lets the field appliers coerce with
    str() without a list or dict reaching the database as its repr — or blowing up as a
    500 on .strip(). Bulk endpoints like reorder take a real structure, so they use
    body() directly.
    """
    parsed = body()
    if any(isinstance(value, (list, dict)) for value in parsed.values()):
        raise BadRequest('Field values must be scalars.')
    return parsed
