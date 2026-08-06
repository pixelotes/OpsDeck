"""Shared HTML sanitization.

Used to neutralise stored-XSS when user-supplied text is rendered as HTML
(notably the `markdown` Jinja filter). Allows the tag/attribute set that the
markdown renderer legitimately produces and strips everything else
(``<script>``, event handlers, ``javascript:`` URLs, etc.).
"""
import bleach
from bleach.css_sanitizer import CSSSanitizer

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


# --- Email bodies ------------------------------------------------------------
#
# EmailTemplate.body_html and Campaign.body_html are authored in a WYSIWYG editor and
# sent as email, so they legitimately need what the markdown set above excludes: table
# layout and inline styles. That is most of what email HTML is made of.
#
# They are also rendered back into the app — the campaign detail page shows the body —
# which made them a stored-XSS vector: whoever could edit a campaign could run script
# in the session of any admin who looked at it.
#
# Jinja placeholders survive this untouched, including inside href, so
# href="{{ event_url }}" and {% if manager %} come out as written. That is what makes
# sanitising on save viable rather than corrupting the templates.

EMAIL_ALLOWED_TAGS = [
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'colgroup', 'col',
    'p', 'div', 'span', 'br', 'hr', 'center',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'strong', 'b', 'em', 'i', 'u', 's', 'del', 'ins', 'mark', 'small', 'sub', 'sup',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'blockquote', 'pre', 'code', 'a', 'img', 'font',
]

EMAIL_ALLOWED_ATTRIBUTES = {
    '*': ['style', 'class', 'id', 'title', 'align', 'valign', 'width', 'height',
          'bgcolor', 'dir', 'lang'],
    'a': ['href', 'name', 'rel', 'target'],
    'img': ['src', 'alt', 'width', 'height', 'border'],
    'table': ['border', 'cellpadding', 'cellspacing', 'summary', 'role'],
    'td': ['colspan', 'rowspan', 'nowrap'],
    'th': ['colspan', 'rowspan', 'scope'],
    'col': ['span'],
    'colgroup': ['span'],
    'font': ['color', 'face', 'size'],
}

# Presentational properties only. Nothing that can fetch or execute: no `behavior`,
# no `-moz-binding`, and url() values are dropped with the properties that carry them.
EMAIL_ALLOWED_CSS = [
    'background', 'background-color', 'border', 'border-bottom', 'border-collapse',
    'border-color', 'border-left', 'border-radius', 'border-right', 'border-spacing',
    'border-style', 'border-top', 'border-width', 'color', 'display', 'font',
    'font-family', 'font-size', 'font-style', 'font-variant', 'font-weight', 'height',
    'letter-spacing', 'line-height', 'list-style', 'list-style-type', 'margin',
    'margin-bottom', 'margin-left', 'margin-right', 'margin-top', 'max-width',
    'min-width', 'padding', 'padding-bottom', 'padding-left', 'padding-right',
    'padding-top', 'text-align', 'text-decoration', 'text-transform', 'vertical-align',
    'white-space', 'width', 'word-break',
]


def sanitize_email_html(html):
    """Return a copy of an email body with anything executable removed.

    Keeps the table layout, inline styles and Jinja placeholders these bodies are built
    from; drops script, event handlers, iframes, embeds, forms and javascript: URLs.
    """
    if not html:
        return html

    css_sanitizer = CSSSanitizer(allowed_css_properties=EMAIL_ALLOWED_CSS)
    return bleach.clean(
        html,
        tags=EMAIL_ALLOWED_TAGS,
        attributes=EMAIL_ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=css_sanitizer,
        strip=True,
    )
