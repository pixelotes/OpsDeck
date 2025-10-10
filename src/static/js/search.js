document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('global-search-input');
    const searchResults = document.getElementById('global-search-results');
    let searchTimeout;

    if (searchInput) {
        searchInput.addEventListener('keyup', function() {
            const query = this.value.trim();
            clearTimeout(searchTimeout);

            if (query.length < 2) {
                searchResults.innerHTML = '';
                searchResults.style.display = 'none';
                return;
            }

            // Debounce the search to avoid sending too many requests while typing
            searchTimeout = setTimeout(() => {
                fetch(`/api/search?q=${encodeURIComponent(query)}`)
                    .then(response => response.json())
                    .then(data => {
                        searchResults.innerHTML = '';
                        searchResults.style.display = 'block';

                        if (data.length > 0) {
                            data.forEach(item => {
                                const a = document.createElement('a');
                                a.href = item.url;
                                a.className = 'list-group-item list-group-item-action py-2';
                                a.innerHTML = `${item.name} <span class="badge bg-secondary float-end">${item.type}</span>`;
                                searchResults.appendChild(a);
                            });
                        } else {
                            const noResults = document.createElement('span');
                            noResults.className = 'list-group-item disabled text-muted';
                            noResults.innerText = 'No results found';
                            searchResults.appendChild(noResults);
                        }
                    }).catch(error => {
                        console.error('Error during search:', error);
                        searchResults.innerHTML = '<div class="list-group-item disabled text-danger">Search failed</div>';
                        searchResults.style.display = 'block';
                    });
            }, 300); // Wait 300ms after user stops typing
        });

        // Hide results when clicking anywhere else on the page
        document.addEventListener('click', function(e) {
            if (!searchInput.contains(e.target)) {
                searchResults.innerHTML = '';
                searchResults.style.display = 'none';
            }
        });
    }
});