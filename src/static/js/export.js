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