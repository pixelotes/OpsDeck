"""Inline on* handlers must only ever go down.

They are what stands between the app and a CSP without 'unsafe-inline' in script-src.
The removal cannot be partial: adding a nonce makes the browser ignore 'unsafe-inline'
altogether, so every remaining on* attribute stops working the moment the switch is
flipped. The count therefore has to reach zero before that switch exists, and a ratchet
is the only way a long migration survives contact with everyday feature work.

Lowering BASELINE is the point. Raising it means somebody added an inline handler, and
the fix is a delegated listener — see src/static/js/behaviors.js for the pattern, or
modal.js for data-confirm, which already existed.
"""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / 'src' / 'templates'

# Any on*= attribute. Deliberately broader than the handlers that exist today, so a new
# onkeyup or onmouseover is caught rather than slipping through a narrow list.
INLINE_HANDLER = re.compile(r'\son[a-z]+\s*=')

#: Inline handlers remaining. Was 137 before the first tranche:
#:   -18  onchange="this.form.submit()"      -> data-autosubmit (behaviors.js)
#:   -13  on{submit,click}="return confirm()" -> data-confirm (modal.js, already existed)
BASELINE = 106


def _counts():
    counts = {}
    for path in sorted(TEMPLATES.rglob('*.html')):
        found = len(INLINE_HANDLER.findall(path.read_text(errors='ignore')))
        if found:
            counts[str(path.relative_to(TEMPLATES))] = found
    return counts


def test_inline_handlers_do_not_increase():
    counts = _counts()
    total = sum(counts.values())

    assert total <= BASELINE, (
        f'Inline on* handlers went up: {total} now, {BASELINE} allowed.\n'
        + '\n'.join(f'  {n:3}  {f}' for f, n in
                    sorted(counts.items(), key=lambda kv: -kv[1])[:10])
        + '\n\nUse a delegated listener instead: data-autosubmit and friends in '
          'src/static/js/behaviors.js, or data-confirm which modal.js already handles.'
    )


def test_the_baseline_is_not_stale():
    """Forces BASELINE down as handlers are removed, so the ratchet keeps ratcheting.

    Without this the number would stay at its historical high and stop meaning anything.
    """
    total = sum(_counts().values())

    assert total == BASELINE, (
        f'{BASELINE - total} handler(s) were removed. Lower BASELINE to {total} in '
        f'{Path(__file__).name} so the next regression is caught against the new floor.'
    )


def test_the_delegated_replacement_is_actually_loaded():
    """A data-autosubmit attribute with nobody listening is a silently dead control."""
    layout = (TEMPLATES / 'layout.html').read_text()

    assert 'js/behaviors.js' in layout, 'behaviors.js is not included in layout.html'
    assert 'js/modal.js' in layout, 'modal.js handles data-confirm and must stay loaded'


def test_every_autosubmit_control_can_find_a_form():
    """data-autosubmit submits control.form or the closest <form>; one of them must exist.

    A select outside a form would look identical in the markup and do nothing when
    changed, which is exactly the failure the old inline handler made impossible to write.
    """
    orphans = []

    for path in sorted(TEMPLATES.rglob('*.html')):
        text = path.read_text(errors='ignore')
        if 'data-autosubmit' not in text:
            continue
        # Cheap structural check: the file has to contain a <form at all.
        if '<form' not in text:
            orphans.append(str(path.relative_to(TEMPLATES)))

    assert not orphans, (
        'Templates using data-autosubmit with no <form> in them:\n'
        + '\n'.join(f'  {o}' for o in orphans)
    )
