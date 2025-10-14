document.addEventListener('DOMContentLoaded', function() {
    
    /**
     * Helper function to initialize a chart on a given canvas element.
     */
    const createChart = (canvasId, chartType, chartData, chartOptions) => {
        const ctx = document.getElementById(canvasId);
        if (ctx) {
            const labels = JSON.parse(ctx.dataset.labels || '[]');
            const values = JSON.parse(ctx.dataset.values || '[]');
            
            chartData.labels = labels;

            if (chartType === 'bar' && ctx.dataset.valuesOriginal) {
                // Handle grouped bar chart for depreciation by location
                chartData.datasets = [
                    {
                        label: 'Original Value (€)',
                        data: JSON.parse(ctx.dataset.valuesOriginal),
                        backgroundColor: 'rgba(54, 162, 235, 0.5)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Depreciated Value (€)',
                        data: JSON.parse(ctx.dataset.valuesDepreciated),
                        backgroundColor: 'rgba(255, 99, 132, 0.5)',
                        borderColor: 'rgba(255, 99, 132, 1)',
                        borderWidth: 1
                    }
                ];
            } else {
                chartData.datasets[0].data = values;
            }

            if (ctx.dataset.keys) {
                chartData.keys = JSON.parse(ctx.dataset.keys);
            }

            new Chart(ctx.getContext('2d'), {
                type: chartType,
                data: chartData,
                options: chartOptions
            });
        }
    };

    // --- Base Chart Options ---
    const doughnutPieOptions = {
        responsive: true,
        plugins: { legend: { position: 'top' } }
    };
    const barOptions = {
        responsive: true,
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
        plugins: { legend: { display: true } } // Display legend for bar charts
    };
    const lineOptions = {
        responsive: true,
        scales: { y: { beginAtZero: true } },
        plugins: { legend: { display: false } }
    };

    // --- Base Chart Data Structures ---
    const doughnutPieData = {
        datasets: [{
            backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#E7E9ED', '#8A2BE2'],
            borderColor: 'rgba(255, 255, 255, 0.5)',
            borderWidth: 2
        }]
    };
    const barData = {
        datasets: [{
            backgroundColor: '#4BC0C0',
            borderColor: '#4BC0C0',
            borderWidth: 1
        }]
    };
    const lineData = (color) => ({
        datasets: [{
            backgroundColor: `rgba(${color}, 0.2)`,
            borderColor: `rgba(${color}, 1)`,
            borderWidth: 2,
            tension: 0.3,
            fill: true
        }]
    });

    // --- Subscription Report Charts ---
    createChart('spendingBySupplierChart', 'doughnut', { ...doughnutPieData, datasets: [{...doughnutPieData.datasets[0], label: 'Spending in €'}] }, doughnutPieOptions);
    createChart('subscriptionsByTypeChart', 'bar', { ...barData, datasets: [{...barData.datasets[0], label: 'Number of Subscriptions'}] }, barOptions);
    createChart('monthlySpendingChart', 'line', { ...lineData('54, 162, 235'), datasets: [{...lineData('54, 162, 235').datasets[0], label: 'Spending in €'}] }, lineOptions);
    createChart('yearlySpendingChart', 'line', { ...lineData('255, 99, 132'), datasets: [{...lineData('255, 99, 132').datasets[0], label: 'Spending in €'}] }, lineOptions);
    
    // --- Dashboard Forecast Chart ---
    const forecastChartOptions = {
        ...barOptions,
        onClick: (event, elements, chart) => {
            if (elements.length > 0) {
                const elementIndex = elements[0].index;
                const yearMonthKey = chart.data.keys[elementIndex];
                if (yearMonthKey) {
                    window.location.href = `/subscriptions?month=${yearMonthKey}`;
                }
            }
        }
    };
    createChart('forecastChart', 'bar', { ...barData, datasets: [{...barData.datasets[0], backgroundColor: 'rgba(153, 102, 255, 0.5)', borderColor: 'rgba(153, 102, 255, 1)', label: 'Forecasted Cost in €'}] }, forecastChartOptions);

    // --- Subscription Detail Cost History Chart ---
    createChart('costHistoryChart', 'bar', { ...barData, datasets: [{...barData.datasets[0], backgroundColor: 'rgba(75, 192, 192, 0.5)', borderColor: 'rgba(75, 192, 192, 1)', label: 'Cost in €'}] }, { ...barOptions, scales: {y: {beginAtZero: false}}});


    // --- Asset Report Charts ---
    createChart('assetsByBrandChart', 'doughnut', { ...doughnutPieData, datasets: [{...doughnutPieData.datasets[0], label: 'Assets by Brand'}] }, doughnutPieOptions);
    createChart('assetsBySupplierChart', 'pie', { ...doughnutPieData, datasets: [{...doughnutPieData.datasets[0], label: 'Assets by Supplier'}] }, doughnutPieOptions);
    createChart('assetsByStatusChart', 'bar', { ...barData, datasets: [{...barData.datasets[0], label: 'Assets by Status'}] }, barOptions);
    createChart('warrantyStatusChart', 'pie', { ...doughnutPieData, datasets: [{...doughnutPieData.datasets[0], label: 'Warranty Status'}] }, doughnutPieOptions);

    // --- Depreciation Report Charts ---
    createChart('totalVsDepreciatedChart', 'doughnut', { ...doughnutPieData, datasets: [{...doughnutPieData.datasets[0], label: 'Value'}] }, doughnutPieOptions);
    
    const depreciationByLocationCtx = document.getElementById('depreciationByLocationChart');
    if (depreciationByLocationCtx) {
        const labels = JSON.parse(depreciationByLocationCtx.dataset.labels || '[]');
        const originalValues = JSON.parse(depreciationByLocationCtx.dataset.valuesOriginal || '[]');
        const depreciatedValues = JSON.parse(depreciationByLocationCtx.dataset.valuesDepreciated || '[]');

        new Chart(depreciationByLocationCtx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Original Value (€)',
                        data: originalValues,
                        backgroundColor: 'rgba(54, 162, 235, 0.5)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Depreciated Value (€)',
                        data: depreciatedValues,
                        backgroundColor: 'rgba(255, 99, 132, 0.5)',
                        borderColor: 'rgba(255, 99, 132, 1)',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    title: {
                        display: true,
                        text: 'Original vs. Depreciated Value by Location'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }
});