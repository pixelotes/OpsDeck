/**
 * Exports the data from a given HTML table to a CSV file.
 * @param {string} tableId The ID of the HTML table to export.
 * @param {string} filename The desired name for the downloaded CSV file.
 */
function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) {
        console.error(`Table with id "${tableId}" not found.`);
        return;
    }

    let csv = [];
    const headers = [];
    // Get headers, skipping the 'Actions' column
    table.querySelectorAll('thead th').forEach(header => {
        if (header.innerText.toLowerCase() !== 'actions') {
            headers.push(`"${header.innerText.replace(/"/g, '""')}"`);
        }
    });
    csv.push(headers.join(','));

    // Get rows
    table.querySelectorAll('tbody tr').forEach(row => {
        const rowData = [];
        // Get cells, skipping the one that corresponds to the 'Actions' header
        row.querySelectorAll('td').forEach((cell, index) => {
            // Check if the current column is not the 'Actions' column
            if (index < headers.length) {
                 // Clean up the text: remove extra whitespace and handle quotes
                let cellText = cell.innerText.trim().replace(/\s\s+/g, ' ');
                rowData.push(`"${cellText.replace(/"/g, '""')}"`);
            }
        });
        csv.push(rowData.join(','));
    });

    // Create a Blob and trigger the download
    const csvContent = "data:text/csv;charset=utf-8," + csv.join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * Delegated wiring for the export buttons.
 *
 * Replaces onclick="exportTableToCSV('x-table', 'x.csv')", which appeared on 31 list
 * pages, so that script-src can eventually drop 'unsafe-inline'. Delegated because
 * several of these tables are redrawn by simple-datatables after load.
 */
document.addEventListener('click', function (event) {
    const trigger = event.target.closest('[data-export-table]');
    if (!trigger) {
        return;
    }

    event.preventDefault();
    exportTableToCSV(
        trigger.dataset.exportTable,
        trigger.dataset.exportFilename || 'export.csv'
    );
});

/**
 * Server-side export: reload the current URL with export=csv appended, keeping the
 * filters the user already applied.
 *
 * Used where the export cannot be built from the rendered table because the table is
 * paginated server-side — the audit log, whose export must cover every matching row and
 * not just the page on screen.
 */
document.addEventListener('click', function (event) {
    const trigger = event.target.closest('[data-export-url]');
    if (!trigger) {
        return;
    }

    event.preventDefault();
    const params = new URLSearchParams(window.location.search);
    params.set('export', 'csv');
    window.location.href = trigger.dataset.exportUrl + '?' + params.toString();
});
