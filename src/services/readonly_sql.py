"""Run an operator-supplied SELECT against the application database, and nothing else.

The User Access Review module lets an administrator name a dataset with raw SQL — "the
people in this table are who currently has access to X". That is a legitimate feature
and an obvious hazard: the text comes from a form and goes to ``db.text()``. Until
v6.0.15 the only guard was a substring blocklist ("no INSERT, no DROP"), which stopped
nobody from ``SELECT password_hash, api_token FROM "user"``, nor a ``UNION`` onto any
other table, and was reachable by anyone with read access to the compliance module.

The defence is now layered, and no single layer is the one we rely on:

1. **Who.** Only a global administrator may author or preview such a query. That is
   enforced by the callers (they know who is asking); this module only knows SQL.
2. **Shape.** One statement, starting with SELECT or WITH, no comment markers, no
   statement separator. That is cheap and rules out the classic stacked-query tricks.
3. **Names.** Identifiers that name secrets (password hashes, API tokens, webhook URLs
   carrying their signing secret, the migrations table, the catalog schemas) are refused
   wherever they appear in the text, so they cannot be selected, filtered on, or
   compared against — a WHERE clause leaks a secret one bit at a time just as well as a
   SELECT list does.
4. **Connection.** The statement runs on a connection the database itself holds
   read-only (``PRAGMA query_only`` on SQLite, a read-only transaction on PostgreSQL),
   inside a transaction that is always rolled back. A write that slips past every check
   above is refused by the engine, which is the only party that actually parses SQL.
5. **Output.** Rows are capped, and any column whose name looks like a secret is
   dropped from the result regardless of how it got there.

None of this makes arbitrary SQL from a non-administrator safe. It makes SQL from an
administrator — who already has the credential vault and the user list — no more
dangerous than the rest of what an administrator can do.
"""
import re
import time
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db

#: Wall-clock bound for one statement, on either database.
STATEMENT_TIMEOUT_SECONDS = 15

#: Default cap on returned rows. A review dataset is a list of people, not a table dump.
DEFAULT_MAX_ROWS = 10_000

#: Words that mark an identifier as secret-bearing wherever they appear inside it:
#: ``password_hash``, ``stripe_api_token``, ``oauth_secret``. Matched as substrings of an
#: identifier, and the *same* list drives the output scrub below, so a column that cannot
#: be named in the query is also never returned by it — the two layers cannot disagree.
SECRET_WORDS = ('password', 'passwd', 'secret', 'token', 'api_key', 'license_key', 'webhook', 'hash')

#: Exact identifiers refused: infrastructure tables, catalog schemas, and the server-side
#: file and network functions. Whole-word.
FORBIDDEN_NAMES = (
    'alembic_version',
    'information_schema', 'pg_catalog', 'sqlite_master', 'sqlite_schema',
    'pg_read_file', 'pg_read_binary_file', 'pg_ls_dir', 'lo_import', 'lo_export',
    'dblink', 'copy', 'readfile', 'writefile', 'load_extension',
)

_IDENT = r'[A-Za-z_][A-Za-z0-9_]*'
_SECRET_IDENT = re.compile(
    r'(?<![A-Za-z0-9_])(' + _IDENT + r')(?![A-Za-z0-9_])'
)
_SECRET_WORD = re.compile('|'.join(re.escape(w) for w in SECRET_WORDS), re.I)
_FORBIDDEN_NAME = re.compile(
    r'(?<![A-Za-z0-9_])(' + '|'.join(re.escape(w) for w in FORBIDDEN_NAMES) + r')(?![A-Za-z0-9_])',
    re.I,
)
#: Single-quoted SQL string literals (with '' escapes). Their contents are data, not names.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_HEAD = re.compile(r'^\(*\s*(SELECT|WITH)(?![A-Za-z0-9_])', re.I)

_COMMENT = re.compile(r'(--|/\*|\*/)')


class ForbiddenQuery(ValueError):
    """The statement was refused before reaching the database."""


def validate_readonly_sql(sql: str) -> str:
    """Return the statement normalised for execution, or raise ForbiddenQuery.

    Pure: no database access. Kept separate so the shape rules can be tested and so
    a form can reject a query at save time, not only when a scheduled run trips on it.
    """
    if sql is None or not sql.strip():
        raise ForbiddenQuery('Query is empty')
    statement = sql.strip()
    # One trailing separator is a habit, not an attack. Anything else is a second statement.
    if statement.endswith(';'):
        statement = statement[:-1].rstrip()
    if ';' in statement:
        raise ForbiddenQuery('Only a single statement is allowed')
    if _COMMENT.search(statement):
        raise ForbiddenQuery('Comments are not allowed in a data-source query')
    if not _HEAD.match(statement):
        raise ForbiddenQuery('Only SELECT queries are allowed')
    # Names are checked with string literals blanked out: WHERE notes = 'token sent'
    # compares against text, it does not read a column called token.
    code = _STRING_LITERAL.sub("''", statement)
    hit = _FORBIDDEN_NAME.search(code)
    if hit:
        raise ForbiddenQuery(f'Query references a forbidden identifier: {hit.group(1)}')
    for ident in _SECRET_IDENT.findall(code):
        if _SECRET_WORD.search(ident):
            raise ForbiddenQuery(f'Query references a forbidden identifier: {ident}')
    return statement


def _scrub(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if not _SECRET_WORD.search(str(k))}


def run_readonly_query(sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> List[Dict[str, Any]]:
    """Validate `sql`, run it on a read-only connection, return at most `max_rows` dicts.

    Raises ForbiddenQuery when the statement is refused by the shape or identifier rules,
    and ValueError when the database refuses it (a write attempt, a syntax error, an
    unknown table). Callers that want one exception type can catch ValueError: both are.
    """
    statement = validate_readonly_sql(sql)
    dialect = db.engine.dialect.name

    with db.engine.connect() as connection:
        if dialect == 'postgresql':
            connection = connection.execution_options(postgresql_readonly=True)
        transaction = connection.begin()
        sqlite_conn = None
        try:
            if dialect == 'sqlite':
                connection.exec_driver_sql('PRAGMA query_only = 1')
                # SQLite has no statement timeout; a progress handler that returns
                # non-zero aborts the running statement. Checked every ~10k VM steps.
                sqlite_conn = connection.connection.dbapi_connection
                deadline = time.monotonic() + STATEMENT_TIMEOUT_SECONDS
                sqlite_conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
            elif dialect == 'postgresql':
                connection.exec_driver_sql(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_SECONDS}s'")
            result = connection.execute(text(statement))
            rows = result.fetchmany(max_rows)
            columns = list(result.keys())
            return [_scrub(dict(zip(columns, row))) for row in rows]
        except SQLAlchemyError as exc:
            # The driver's message names the table or the write it refused, which is what
            # the operator needs to fix the query; the SQL itself is theirs already.
            raise ValueError(f'Query execution failed: {getattr(exc, "orig", exc)}') from exc
        finally:
            # Nothing here ever commits. On SQLite the pragma is per-connection and the
            # pool would hand this connection to the next request, so put it back.
            transaction.rollback()
            if sqlite_conn is not None:
                sqlite_conn.set_progress_handler(None, 0)
            if dialect == 'sqlite':
                connection.exec_driver_sql('PRAGMA query_only = 0')
