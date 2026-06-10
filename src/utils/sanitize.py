"""Shared HTML sanitization.

Used to neutralise stored-XSS when user-supplied text is rendered as HTML
(notably the `markdown` Jinja filter). Allows the tag/attribute set that the
markdown renderer legitimately produces and strips everything else
(``<script>``, event handlers, ``javascript:`` URLs, etc.).
"""
import bleach

# Tags emitted by Markdown + the 'extra'/'codehilite'/'toc'/'sane_lists'
# extensions. Deliberately excludes <script>, <style>, <iframe>, <object>, ...
ALLOWED_TAGS = [
    'p', 'br', 'hr', 'span', 'div',
    'strong', 'b', 'em', 'i', 'u', 's', 'del', 'ins', 'mark', 'small', 'sub', 'sup',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'blockquote', 'pre', 'code', 'kbd', 'samp', 'var',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
    'a', 'img',
    'abbr', 'acronym', 'cite', 'q', 'dfn',
]

# 'class'/'id' are needed for codehilite spans and toc heading anchors.
ALLOWED_ATTRIBUTES = {
    '*': ['class', 'id', 'title'],
    'a': ['href', 'name', 'rel'],
    'img': ['src', 'alt', 'width', 'height'],
    'th': ['align', 'scope', 'colspan', 'rowspan'],
    'td': ['align', 'colspan', 'rowspan'],
    'col': ['span'],
    'colgroup': ['span'],
}

# Note: no 'javascript', 'data' or 'vbscript' — blocks javascript: and data: URIs.
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def sanitize_html(html):
    """Return a sanitized copy of ``html`` safe to mark as Markup.

    Disallowed tags/attributes are stripped (``strip=True``) rather than escaped,
    keeping rendered content clean.
    """
    if not html:
        return html
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
