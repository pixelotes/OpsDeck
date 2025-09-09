document.addEventListener('DOMContentLoaded', function() {
    
    /**
     * Helper function to initialize a chart on a given canvas element.
     * It reads chart labels, values, and keys from the canvas's data-* attributes.
     * @param {string} canvasId - The ID of the canvas element.
     * @param {string} chartType - The type of chart (e.g., 'doughnut', 'bar', 'line').
     * @param {object} chartData - The base data structure for the chart's datasets.
     * @param {object} chartOptions - The configuration options for the chart.
     */
    const createChart = (canvasId, chartType, chartData, chartOptions) => {
        const ctx = document.getElementById(canvasId);
        if (ctx) {
            // Read data from the canvas element's data-* attributes
            const labels = JSON.parse(ctx.dataset.labels || '[]');
            const values = JSON.parse(ctx.dataset.values || '[]');
            
            // Populate the chart data with the retrieved labels and values
            chartData.labels = labels;
            chartData.datasets[0].data = values;

            // Add keys for custom click handling if they exist
            if (ctx.dataset.keys) {
                chartData.keys = JSON.parse(ctx.dataset.keys);
            }

            // Create the new chart instance
            new Chart(ctx.getContext('2d'), {
                type: chartType,
                data: chartData,
                options: chartOptions
            });
        }
    };

    // --- Chart 1: Spending by Supplier ---
    const supplierChartData = {
        datasets: [{
            label: 'Spending in €',
            backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40'],
            borderColor: 'rgba(255, 255, 255, 0.5)',
            borderWidth: 2
        }]
    };
    const supplierChartOptions = {
        responsive: true,
        plugins: { legend: { position: 'top' } }
    };
    createChart('spendingBySupplierChart', 'doughnut', supplierChartData, supplierChartOptions);

    // --- Chart 2: Services by Type ---
    const typeChartData = {
        datasets: [{
            label: 'Number of Services',
            backgroundColor: '#4BC0C0',
            borderColor: '#4BC0C0',
            borderWidth: 1
        }]
    };
    const typeChartOptions = {
        responsive: true,
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
        plugins: { legend: { display: false } }
    };
    createChart('servicesByTypeChart', 'bar', typeChartData, typeChartOptions);

    // --- Chart 3: Spending per Month ---
    const monthlyChartData = {
        datasets: [{
            label: 'Spending in €',
            backgroundColor: 'rgba(54, 162, 235, 0.2)', // Color for the fill
            borderColor: 'rgba(54, 162, 235, 1)',
            borderWidth: 2,
            tension: 0.3,
            fill: true // This fills the area under the line
        }]
    };
    const monthlyChartOptions = {
        responsive: true,
        scales: { y: { beginAtZero: true } },
        plugins: { legend: { display: false } }
    };
    createChart('monthlySpendingChart', 'line', monthlyChartData, monthlyChartOptions);

    // --- Chart 4: Spending per Year ---
    const yearlyChartData = {
        datasets: [{
            label: 'Spending in €',
            backgroundColor: 'rgba(255, 99, 132, 0.2)', // Color for the fill
            borderColor: 'rgba(255, 99, 132, 1)',
            borderWidth: 2,
            tension: 0.3,
            fill: true // This fills the area under the line
        }]
    };
    const yearlyChartOptions = {
        responsive: true,
        scales: { y: { beginAtZero: true } },
        plugins: { legend: { display: false } }
    };
    createChart('yearlySpendingChart', 'line', yearlyChartData, yearlyChartOptions);
    
    // --- Chart 5: Upcoming Renewal Costs Forecast ---
    const forecastChartData = {
        datasets: [{
            label: 'Forecasted Cost in €',
            backgroundColor: 'rgba(153, 102, 255, 0.5)',
            borderColor: 'rgba(153, 102, 255, 1)',
            borderWidth: 1
        }]
    };
    const forecastChartOptions = {
        responsive: true,
        scales: { y: { beginAtZero: true } },
        plugins: { legend: { display: false } },
        onClick: (event, elements, chart) => {
            if (elements.length > 0) {
                const elementIndex = elements[0].index;
                const yearMonthKey = chart.data.keys[elementIndex];
                if (yearMonthKey) {
                    // Redirect to the services page with the month filter
                    window.location.href = `/services?month=${yearMonthKey}`;
                }
            }
        }
    };
    createChart('forecastChart', 'bar', forecastChartData, forecastChartOptions);

    // --- Chart 6: Service Cost History ---
    const historyChartData = {
        datasets: [{
            label: 'Cost in €',
            backgroundColor: 'rgba(75, 192, 192, 0.5)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1
        }]
    };
    const historyChartOptions = {
        responsive: true,
        scales: { y: { beginAtZero: false } }, // Start at a reasonable value, not always zero
        plugins: { legend: { display: false } }
    };
    createChart('costHistoryChart', 'bar', historyChartData, historyChartOptions);

});