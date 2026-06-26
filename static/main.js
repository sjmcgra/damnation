/**
 * DAM - Digital Asset Management
 * Main JavaScript file
 */

// Utility Functions

/**
 * Copy text to clipboard
 */
function copyToClipboard(text, feedbackElement = null) {
    navigator.clipboard.writeText(text).then(() => {
        if (feedbackElement) {
            const originalText = feedbackElement.textContent;
            feedbackElement.textContent = '✓ Copied!';
            setTimeout(() => {
                feedbackElement.textContent = originalText;
            }, 2000);
        }
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

/**
 * Format file size to human readable format
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const k = 1024;
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + units[i];
}

/**
 * Format date to readable format
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Debounce function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Throttle function
 */
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// API Helpers

/**
 * Make API request
 */
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API request failed:', error);
        throw error;
    }
}

/**
 * Get asset versions
 */
async function getAssetVersions(assetId) {
    return apiRequest(`/api/assets/${assetId}/versions`);
}

// UI Helpers

/**
 * Show notification
 */
function showNotification(message, type = 'success', duration = 3000) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.textContent = message;
    alertDiv.style.position = 'fixed';
    alertDiv.style.top = '20px';
    alertDiv.style.right = '20px';
    alertDiv.style.zIndex = '9999';
    alertDiv.style.maxWidth = '400px';
    
    document.body.appendChild(alertDiv);
    
    setTimeout(() => {
        alertDiv.remove();
    }, duration);
}

/**
 * Show loading spinner
 */
function showLoading(element) {
    element.innerHTML = '<div class="loading" style="margin: 20px auto;"></div>';
}

/**
 * Clear loading spinner
 */
function clearLoading(element) {
    element.innerHTML = '';
}

// Search & Filter

/**
 * Setup search with debouncing
 */
function setupSearch() {
    const searchInput = document.querySelector('input[name="q"]');
    if (!searchInput) return;
    
    const form = searchInput.closest('form');
    
    searchInput.addEventListener('input', debounce(() => {
        // Auto-submit search after user stops typing
        // Optional: uncomment to auto-submit
        // form.submit();
    }, 300));
}

/**
 * Setup filter listeners
 */
function setupFilters() {
    const filterSelects = document.querySelectorAll('select[name="project"], select[name="type"]');
    filterSelects.forEach(select => {
        select.addEventListener('change', function() {
            this.form.submit();
        });
    });
}

// Initialize on page load

document.addEventListener('DOMContentLoaded', () => {
    setupSearch();
    setupFilters();
});

// Export for use in other scripts
window.DAM = {
    copyToClipboard,
    formatFileSize,
    formatDate,
    debounce,
    throttle,
    apiRequest,
    getAssetVersions,
    showNotification,
    showLoading,
    clearLoading
};
