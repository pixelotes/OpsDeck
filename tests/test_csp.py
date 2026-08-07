"""The Content-Security-Policy, and the inventory that lets it stay this tight.

'unsafe-eval' was dropped on the strength of reading every vendored bundle: none of
them evaluates code on a browser that has globalThis and a native
Function.prototype.bind. That is a claim about third-party code we do not control and
that a dependency bump can invalidate silently — the symptom would be a page that
quietly stops working in production, since a CSP violation is a console error, not a
server-side failure.

So the inventory is pinned below. A bump that adds a dynamic-code site fails here, and
whoever bumps it has to look at the new site and decide, rather than discovering it from
a bug report.
"""
import re
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parent.parent / 'src' / 'static' / 'vendor'

# `new Function(`, a bare `Function(` call, or `eval(` — excluding method calls like
# .eval( and identifiers that merely end in Function(, e.g. compareFunction(.
DYNAMIC_CODE = re.compile(r'(new\s+Function\(|[^A-Za-z0-9_$]Function\(|[^.A-Za-z0-9_$]eval\()')

#: Known dynamic-code sites per bundle, all unreachable in a supported browser:
#:
#: mermaid                        4  lodash's `globalThis || Function("return this")()`
#: swagger-ui-bundle              5  the same, plus the Function.prototype.bind shim
#: swagger-ui-es-bundle-core      1  the same globalThis fallback
#: swagger-ui-es-bundle           5  as swagger-ui-bundle
#: swagger-ui-standalone-preset   4  as swagger-ui-bundle, one fewer globalThis spelling
#:
#: Raising a number is not automatically wrong — but it must be a deliberate edit made
#: after looking at the new site, not a side effect of `npm update`.
EXPECTED_DYNAMIC_CODE = {
    'mermaid/mermaid.min.js': 4,
    'swagger-ui/swagger-ui-bundle.js': 5,
    'swagger-ui/swagger-ui-es-bundle-core.js': 1,
    'swagger-ui/swagger-ui-es-bundle.js': 5,
    'swagger-ui/swagger-ui-standalone-preset.js': 4,
}


def _vendor_js():
    # is_file() matters: one of the vendored directories is itself named chart.js.
    return sorted(p for p in VENDOR.rglob('*.js') if p.is_file())


def test_no_vendored_bundle_gained_a_dynamic_code_site():
    """Fails when a dependency bump introduces eval where there was none."""
    assert VENDOR.is_dir(), f'vendor directory not found at {VENDOR}'

    found = {}
    for path in _vendor_js():
        count = len(DYNAMIC_CODE.findall(path.read_text(errors='ignore')))
        if count:
            found[str(path.relative_to(VENDOR))] = count

    assert found == EXPECTED_DYNAMIC_CODE, (
        'The dynamic-code inventory changed.\n'
        f'  expected: {EXPECTED_DYNAMIC_CODE}\n'
        f'  found:    {found}\n'
        'Look at each new site before updating the numbers. If any of them actually runs '
        "in a browser, the app needs 'unsafe-eval' back for that page and the CSP in "
        'src/__init__.py has to say so.'
    )


def test_every_known_dynamic_code_site_is_a_polyfill_fallback():
    """The sites are tolerated because of what they are, so check what they are.

    Both shapes read a global that exists in every browser the app supports and only
    fall back to building a function when it does not. Counting alone would not notice a
    bundle swapping a polyfill for a real eval while keeping the total the same.
    """
    offenders = []

    for name in EXPECTED_DYNAMIC_CODE:
        text = (VENDOR / name).read_text(errors='ignore')
        for match in DYNAMIC_CODE.finditer(text):
            context = text[max(0, match.start() - 120):match.end() + 60]
            is_global_this = 'return this' in context
            is_bind_shim = 'binder' in context
            if not (is_global_this or is_bind_shim):
                offenders.append(f'{name}: ...{context[100:200]}...')

    assert not offenders, (
        'Dynamic-code sites that are neither a globalThis fallback nor the bind shim:\n'
        + '\n'.join(f'  {o}' for o in offenders)
    )


# --- the header itself ------------------------------------------------------------

def _csp(client):
    response = client.get('/login')
    return response.headers.get('Content-Security-Policy', '')


def test_the_policy_no_longer_allows_eval(client):
    assert "'unsafe-eval'" not in _csp(client)


@pytest.mark.parametrize('directive', [
    "default-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'self'",
    "form-action 'self'",
])
def test_the_directives_that_do_the_work_are_present(client, directive):
    """These are what stop external script loading, clickjacking and off-site posts."""
    assert directive in _csp(client)


def test_script_src_no_longer_allows_inline_script(client):
    """The point of the whole exercise: an injected <script> will not run.

    script-src carries a nonce, which also makes a browser ignore 'unsafe-inline' even if
    it came back, so this is belt and braces — but the keyword being absent is what makes
    the policy readable as strict.
    """
    directive = next(part.strip() for part in _csp(client).split(';')
                     if part.strip().startswith('script-src'))

    assert "'unsafe-inline'" not in directive, directive
    assert "'unsafe-eval'" not in directive, directive


def test_each_response_carries_a_fresh_script_nonce(client):
    """A nonce reused across responses is worth no more than 'unsafe-inline'.

    It is what tells the browser which blocks are ours; if an attacker could learn or
    predict it, injected script could claim it too.
    """
    first = next(p.strip() for p in _csp(client).split(';')
                 if p.strip().startswith('script-src'))
    second = next(p.strip() for p in _csp(client).split(';')
                  if p.strip().startswith('script-src'))

    assert "'nonce-" in first, first
    assert first != second, 'the same nonce was served twice'


def test_the_rendered_page_uses_the_nonce_from_its_own_header(client):
    """The header and the markup have to agree, or nothing executes.

    Checked against a real response rather than the template source, because the nonce is
    generated per request and a template could just as easily render an empty attribute.
    """
    response = client.get('/login')
    header = response.headers['Content-Security-Policy']
    html = response.get_data(as_text=True)

    nonce = re.search(r"'nonce-([^']+)'", header).group(1)

    assert f'nonce="{nonce}"' in html, (
        'no inline script on the login page carries the nonce from its own CSP header'
    )
    assert 'nonce=""' not in html, 'an inline script rendered an empty nonce'
