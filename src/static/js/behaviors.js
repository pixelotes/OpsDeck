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

    /**
     * data-action / data-change: call a named function a page has registered.
     *
     * The long tail of inline handlers is one-off calls — performSearch(), toggleSampling(),
     * deleteControl(this, id) — with nothing in common but their shape. Rather than a
     * bespoke dispatcher per page, a page registers what its markup may invoke:
     *
     *     OpsDeck.registerActions({ performSearch, clearFilters });
     *     <button data-action="performSearch">
     *
     * The name is a key in that object, never a lookup on window: the registry doubles as
     * the list of what markup is allowed to reach, and a dynamic lookup would give the
     * attribute the run of every global on the page.
     *
     * Two attributes because a checkbox fires click and change both; one listener on both
     * events would run the action twice. data-action is for clicks, data-change for
     * controls reporting a new value. The handler receives (element, data-arg).
     */
    const actions = {};

    window.OpsDeck = window.OpsDeck || {};
    window.OpsDeck.registerActions = function (newActions) {
        Object.assign(actions, newActions);
    };

    function dispatch(attribute, key) {
        return function (event) {
            const trigger = event.target.closest('[' + attribute + ']');
            if (!trigger) {
                return;
            }

            const handler = actions[trigger.dataset[key]];
            if (!handler) {
                // A registry that does not know the name means the page forgot to register
                // it, or the markup has a typo. Silence would look like a dead button.
                console.error('No action registered for', trigger.dataset[key], trigger);
                return;
            }

            handler(trigger, trigger.dataset.arg, event);
        };
    }

    document.addEventListener('click', dispatch('data-action', 'action'));
    document.addEventListener('change', dispatch('data-change', 'change'));

    /**
     * data-copy-from: copy the value of another element to the clipboard.
     *
     * Replaces onclick="navigator.clipboard.writeText(document.getElementById(…).value)",
     * which appeared on the API key page and the user detail page.
     */
    document.addEventListener('click', function (event) {
        const trigger = event.target.closest('[data-copy-from]');
        if (!trigger) {
            return;
        }

        const source = document.getElementById(trigger.dataset.copyFrom);
        if (!source) {
            console.error('data-copy-from points at no element:', trigger.dataset.copyFrom);
            return;
        }

        event.preventDefault();
        navigator.clipboard.writeText(source.value);

        // Say something happened. The old inline version copied silently, which reads as
        // a broken button.
        if (window.showToast) {
            window.showToast('Copied to clipboard', 'success');
        }
    });

    /**
     * data-filename-target: show the chosen file's name in another element.
     *
     * Replaces an inline expression on file inputs, whose only job was to tell the user
     * something had been selected.
     */
    document.addEventListener('change', function (event) {
        const input = event.target.closest('[data-filename-target]');
        if (!input) {
            return;
        }

        const label = document.getElementById(input.dataset.filenameTarget);
        if (label) {
            label.textContent = input.files.length ? input.files[0].name : 'No file selected';
        }
    });

    /**
     * data-stop-propagation: keep a click inside a clickable container.
     *
     * Replaces onclick="event.stopPropagation();" on controls sitting inside a row that
     * is itself a link.
     */
    document.addEventListener('click', function (event) {
        if (event.target.closest('[data-stop-propagation]')) {
            event.stopPropagation();
        }
    });
})();
