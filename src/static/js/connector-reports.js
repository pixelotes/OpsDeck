/*
 * Shared helpers for the API connector report views (Settings > API Connectors):
 * the report modal and diff modal in connectors/reports.html and the full-screen
 * report page. Report data comes from external APIs, so cells are built with DOM
 * nodes and textContent, never by concatenating values into HTML.
 */
(function (global) {
    'use strict';

    // Columns shown by default for known payloads; everything else starts hidden.
    const DEFAULT_COLUMNS = [
        {
            detect: ['full_name', 'private', 'owner', 'default_branch'],   // GitHub repositories
            show: ['name', 'url', 'visibility', 'created_at', 'archived', 'disabled', 'default_branch'],
        },
        {
            detect: ['login', 'avatar_url', 'html_url', 'site_admin'],     // GitHub users
            show: ['html_url', 'id', 'login', 'site_admin', 'type', 'user_view_type'],
        },
        {
            detect: ['email', 'firstname', 'lastname', 'systemusername', 'ldap_binding_user'],  // JumpCloud users
            show: ['id', 'created', 'email', 'firstname', 'lastname', 'ldap_binding_user', 'password_date',
                'state', 'suspended', 'systemusername', 'username'],
        },
        {
            detect: ['hostname', 'displayname', 'os', 'lastcontact', 'serialnumber'],   // JumpCloud systems
            show: ['id', 'active', 'arch', 'created', 'description', 'displayname', 'hostname', 'hwvendor',
                'ispolicybound', 'lastcontact', 'os', 'remoteip', 'serialnumber', 'version'],
        },
        {
            detect: ['key', 'name', 'type', '_expandable', '_links'],      // Confluence spaces
            hide: ['_expandable', '_ari'],
        },
    ];

    function extractItems(data) {
        if (data && Array.isArray(data.items)) return data.items;
        if (Array.isArray(data)) return data;
        return [data];
    }

    function humanize(column) {
        return column.replaceAll('_', ' ').replaceAll(/\b\w/g, l => l.toUpperCase());
    }

    function stringify(value) {
        return typeof value === 'object' ? JSON.stringify(value) : String(value);
    }

    /** Columns to show first for a payload, or null to show them all. */
    function defaultVisibleColumns(columns) {
        const lower = columns.map(c => c.toLowerCase());
        const rule = DEFAULT_COLUMNS.find(r => r.detect.some(f => lower.includes(f)));
        if (!rule) return null;
        if (rule.show) {
            const show = new Set(rule.show);
            return columns.filter(c => show.has(c.toLowerCase()));
        }
        const hide = new Set(rule.hide);
        return columns.filter(c => !hide.has(c.toLowerCase()));
    }

    function filterItems(items, columns, hiddenColumns, query) {
        if (!query) return items;
        return items.filter(item => columns.some((col, idx) => {
            if (hiddenColumns.has(idx)) return false;
            const value = item[col];
            return value !== null && value !== undefined && stringify(value).toLowerCase().includes(query);
        }));
    }

    function compareValues(a, b) {
        if (typeof a === 'boolean') {
            if (a === b) return 0;
            return a ? -1 : 1;
        }
        if (typeof a === 'number') return a - b;
        if (typeof a === 'string') return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
        return String(a).localeCompare(String(b));
    }

    /** Sorted copy of items; missing values always go last. */
    function sortItems(items, column, direction) {
        const sign = direction === 'asc' ? 1 : -1;
        return [...items].sort((x, y) => {
            const a = x[column];
            const b = y[column];
            const aMissing = a === null || a === undefined;
            const bMissing = b === null || b === undefined;
            if (aMissing || bMissing) return Number(aMissing) - Number(bMissing);
            return sign * compareValues(a, b);
        });
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function isHttpUrl(value) {
        try {
            const url = new URL(value);
            return url.protocol === 'http:' || url.protocol === 'https:';
        } catch {
            return false;
        }
    }

    /** Fill a table cell with a value, formatted by type and column name. */
    function renderCell(td, column, value) {
        if (value === null || value === undefined) {
            td.textContent = '-';
            td.className = 'text-muted';
        } else if (typeof value === 'boolean') {
            td.appendChild(element('span', value ? 'badge bg-success' : 'badge bg-secondary', value ? 'Yes' : 'No'));
        } else if (typeof value === 'object') {
            td.appendChild(element('code', 'small', JSON.stringify(value)));
        } else if (column.includes('avatar') && isHttpUrl(value)) {
            const img = element('img', 'rounded');
            img.src = value;
            img.alt = '';
            img.width = 32;
            img.height = 32;
            td.appendChild(img);
        } else if (column.includes('url') && isHttpUrl(value)) {
            const link = element('a', 'small text-truncate d-inline-block', value);
            link.href = value;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.style.maxWidth = '300px';
            td.appendChild(link);
        } else if (column.includes('date') || column.includes('_at')) {
            td.appendChild(element('small', null, new Date(value).toLocaleString()));
        } else {
            td.textContent = value;
        }
    }

    function renderRows(tbody, items, columns, hiddenColumns) {
        items.forEach(item => {
            const tr = document.createElement('tr');
            columns.forEach((col, idx) => {
                if (hiddenColumns && hiddenColumns.has(idx)) return;
                const td = document.createElement('td');
                renderCell(td, col, item[col]);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    }

    function renderEmpty(tbody) {
        const tr = document.createElement('tr');
        tr.appendChild(element('td', 'text-center text-muted', 'No data'));
        tbody.appendChild(tr);
    }

    // --- Diff view ---------------------------------------------------------

    function valueNode(value) {
        if (typeof value === 'object' && value !== null) {
            return element('pre', 'm-0 bg-transparent p-0', JSON.stringify(value, null, 2));
        }
        return document.createTextNode(String(value));
    }

    function diffRow(rowClass, icon, path, before, after) {
        const tr = element('tr', rowClass);
        const field = document.createElement('td');
        field.appendChild(element('i', icon));
        field.appendChild(element('strong', null, path));
        tr.appendChild(field);
        [before, after].forEach(cell => {
            const td = document.createElement('td');
            if (cell.placeholder) {
                td.className = 'text-muted fst-italic';
                td.textContent = cell.placeholder;
            } else {
                td.appendChild(valueNode(cell.value));
            }
            tr.appendChild(td);
        });
        return tr;
    }

    function renderDiffTable(diff) {
        const table = element('table', 'table table-sm table-bordered');
        const head = table.createTHead().insertRow();
        [['Field', '40%'], ['Previous Value', '30%'], ['New Value', '30%']].forEach(([label, width]) => {
            const th = element('th', null, label);
            th.scope = 'col';
            th.style.width = width;
            head.appendChild(th);
        });
        const body = table.createTBody();
        const added = diff.added || [];
        const removed = diff.removed || [];
        const changed = diff.changed || [];

        added.forEach(([path, value]) => body.appendChild(diffRow(
            'table-success', 'fas fa-plus-circle text-success me-2', path, { placeholder: 'None' }, { value })));
        removed.forEach(([path, value]) => body.appendChild(diffRow(
            'table-danger', 'fas fa-minus-circle text-danger me-2', path, { value }, { placeholder: 'Removed' })));
        changed.forEach(([path, oldValue, newValue]) => body.appendChild(diffRow(
            'table-warning', 'fas fa-pencil-alt text-warning me-2', path, { value: oldValue }, { value: newValue })));

        if (!added.length && !removed.length && !changed.length) {
            const td = element('td', 'text-center text-muted', 'No changes detected.');
            td.colSpan = 3;
            body.insertRow().appendChild(td);
        }
        const wrapper = element('div', 'diff-viewer');
        wrapper.appendChild(table);
        return wrapper;
    }

    function renderDiffSummary(data) {
        const summary = document.createElement('div');
        const row = element('div', 'row');
        [['New Report', data.report_new_id, data.report_new_date],
         ['Previous Report', data.report_old_id, data.report_old_date]].forEach(([label, id, date]) => {
            const col = element('div', 'col-md-6');
            col.appendChild(element('strong', null, `${label}:`));
            col.appendChild(document.createTextNode(` #${id}`));
            col.appendChild(document.createElement('br'));
            col.appendChild(element('small', 'text-muted', date));
            row.appendChild(col);
        });
        summary.appendChild(row);
        summary.appendChild(data.has_changes
            ? element('div', 'alert alert-warning mt-2', 'Changes detected')
            : element('div', 'alert alert-success mt-2', 'No changes'));
        return summary;
    }

    global.ConnectorReports = {
        extractItems, humanize, stringify, defaultVisibleColumns, filterItems, sortItems,
        renderCell, renderRows, renderEmpty, renderDiffTable, renderDiffSummary,
    };
})(globalThis);
