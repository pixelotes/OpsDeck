/**
 * OpsDeck Declarative Behaviors
 *
 * Delegated replacement for inline on* handlers, so the Content-Security-Policy can
 * eventually drop 'unsafe-inline' from script-src. That switch cannot be flipped while
 * any on* attribute is left: a nonce makes the browser ignore 'unsafe-inline' entirely,
 * and every remaining inline handler would stop working at once. So the attributes go
 * first, in tranches.
 *
 * Confirmation prompts are deliberately NOT here. modal.js already implements
 * data-confirm on both forms and links, with a styled dialog instead of window.confirm,
 * so the onsubmit="return confirm(...)" handlers were converted to that existing
 * attribute rather than to anything new.
 *
 * One listener on the document, not one per element: the tables these are used in
 * redraw and paginate, and a listener attached at load would not survive that.
 */

(function () {
    'use strict';

    /**
     * data-autosubmit: submit the closest form when the control changes.
     *
     * Replaces onchange="this.form.submit()" — filter dropdowns that reload the list.
     */
    document.addEventListener('change', function (event) {
        const control = event.target.closest('[data-autosubmit]');
        if (!control) {
            return;
        }

        const form = control.form || control.closest('form');
        if (form) {
            form.submit();
        }
    });

})();
