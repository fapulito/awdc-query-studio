// Chat functionality for the MCP chatbot application

document.addEventListener('DOMContentLoaded', function() {
    const chatForm = document.getElementById('chat-form');
    const messageInput = document.getElementById('message-input');
    const conversationDisplay = document.getElementById('conversation');
    const loadingIndicator = document.getElementById('loading');
    const sendButton = document.getElementById('send-button');

    // Clear session on page load to start fresh
    clearSessionOnLoad();

    // Handle form submission
    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        sendMessage();
    });

    // Handle Enter key for message submission
    messageInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Track if a request is in progress
    let requestInProgress = false;

    function sendMessage() {
        const message = messageInput.value.trim();
        
        if (!message || requestInProgress) {
            return;
        }

        // Mark request as in progress
        requestInProgress = true;

        // Display user message
        addMessageToDisplay('user', message);
        
        // Clear input and disable form
        messageInput.value = '';
        setFormEnabled(false);
        showLoading(true);

        // Show typing indicator
        const typingIndicator = addTypingIndicator();

        // Send AJAX request to backend
        fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: message })
        })
        .then(response => {
            // Handle 401 Unauthorized - redirect to login
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.message || 'Failed to get response from server');
                });
            }
            return response.json();
        })
        .then(data => {
            // Remove typing indicator
            removeTypingIndicator(typingIndicator);
            
            // Display assistant response
            if (data.response) {
                addMessageToDisplay('assistant', data.response, data.queries || []);
            } else {
                throw new Error('No response received from server');
            }
        })
        .catch(error => {
            // Remove typing indicator
            removeTypingIndicator(typingIndicator);
            
            // Display error message
            displayError(error.message);
        })
        .finally(() => {
            // Mark request as complete
            requestInProgress = false;
            
            // Re-enable form and hide loading
            setFormEnabled(true);
            showLoading(false);
            messageInput.focus();
        });
    }

    function addMessageToDisplay(role, content, queries) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}-message`;
        
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        
        // Apply basic markdown formatting for assistant messages
        if (role === 'assistant') {
            messageContent.innerHTML = formatMarkdown(content);
        } else {
            messageContent.textContent = content;
        }
        
        messageDiv.appendChild(messageContent);

        // "View SQL" transparency toggle — only for assistant messages with queries
        if (role === 'assistant' && Array.isArray(queries) && queries.length > 0) {
            messageDiv.appendChild(buildSqlToggle(queries));
        }
        
        const timestamp = document.createElement('div');
        timestamp.className = 'message-timestamp';
        timestamp.textContent = new Date().toLocaleTimeString();
        
        messageDiv.appendChild(timestamp);
        
        conversationDisplay.appendChild(messageDiv);
        
        // Scroll to bottom
        conversationDisplay.scrollTop = conversationDisplay.scrollHeight;
    }

    /**
     * Build a collapsed "View SQL" disclosure widget for the given queries array.
     * Each entry: {table, sql, parameters, row_count}
     * The widget is closed by default; clicking the toggle opens/closes it.
     */
    function buildSqlToggle(queries) {
        const wrapper = document.createElement('div');
        wrapper.className = 'sql-toggle-wrapper';

        const toggle = document.createElement('button');
        toggle.className = 'sql-toggle-btn';
        toggle.setAttribute('aria-expanded', 'false');
        toggle.innerHTML =
            '<svg class="sql-toggle-icon" width="12" height="12" viewBox="0 0 24 24" ' +
            'fill="none" stroke="currentColor" stroke-width="2.5" ' +
            'stroke-linecap="round" stroke-linejoin="round">' +
            '<polyline points="9 18 15 12 9 6"></polyline></svg>' +
            ' View SQL';

        const body = document.createElement('div');
        body.className = 'sql-toggle-body';
        body.style.display = 'none';

        queries.forEach(function(q, idx) {
            const block = document.createElement('div');
            block.className = 'sql-block';

            // Table + row count header
            const header = document.createElement('div');
            header.className = 'sql-block-header';
            header.textContent = q.table + ' \u2014 ' + q.row_count + ' row' + (q.row_count !== 1 ? 's' : '');
            block.appendChild(header);

            // SQL pre with copy button
            const preWrap = document.createElement('div');
            preWrap.className = 'sql-pre-wrap';

            const pre = document.createElement('pre');
            pre.className = 'sql-pre';
            pre.textContent = q.sql;
            preWrap.appendChild(pre);

            const copyBtn = document.createElement('button');
            copyBtn.className = 'sql-copy-btn';
            copyBtn.title = 'Copy SQL';
            copyBtn.innerHTML =
                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>' +
                '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>' +
                '</svg>';
            copyBtn.addEventListener('click', function() {
                navigator.clipboard.writeText(q.sql).then(function() {
                    copyBtn.title = 'Copied!';
                    setTimeout(function() { copyBtn.title = 'Copy SQL'; }, 1500);
                }).catch(function() {
                    // Fallback for browsers without clipboard API
                    const ta = document.createElement('textarea');
                    ta.value = q.sql;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                });
            });
            preWrap.appendChild(copyBtn);
            block.appendChild(preWrap);

            // Parameters line (only when non-empty)
            if (Array.isArray(q.parameters) && q.parameters.length > 0) {
                const params = document.createElement('div');
                params.className = 'sql-params';
                params.textContent = 'Parameters: ' + q.parameters.join(', ');
                block.appendChild(params);
            }

            body.appendChild(block);
        });

        toggle.addEventListener('click', function() {
            const open = body.style.display !== 'none';
            body.style.display = open ? 'none' : 'block';
            toggle.setAttribute('aria-expanded', String(!open));
            toggle.querySelector('.sql-toggle-icon').style.transform = open ? '' : 'rotate(90deg)';
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(body);
        return wrapper;
    }

    function formatMarkdown(text) {
        // Escape HTML to prevent XSS
        let formatted = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        
        // Bold: **text** or __text__
        formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        formatted = formatted.replace(/__(.+?)__/g, '<strong>$1</strong>');
        
        // Italic: *text* or _text_
        formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>');
        formatted = formatted.replace(/_(.+?)_/g, '<em>$1</em>');
        
        // Code: `code`
        formatted = formatted.replace(/`(.+?)`/g, '<code>$1</code>');
        
        // Line breaks
        formatted = formatted.replace(/\n/g, '<br>');
        
        return formatted;
    }

    function displayError(errorMessage) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message error-message';
        
        const errorContent = document.createElement('div');
        errorContent.className = 'message-content';
        errorContent.textContent = `Error: ${errorMessage}`;
        
        errorDiv.appendChild(errorContent);
        conversationDisplay.appendChild(errorDiv);
        
        // Scroll to bottom
        conversationDisplay.scrollTop = conversationDisplay.scrollHeight;
    }

    function setFormEnabled(enabled) {
        messageInput.disabled = !enabled;
        sendButton.disabled = !enabled;
    }

    function showLoading(show) {
        loadingIndicator.style.display = show ? 'block' : 'none';
    }

    function addTypingIndicator() {
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message assistant-message typing-indicator';
        typingDiv.id = 'typing-indicator';
        
        const typingContent = document.createElement('div');
        typingContent.className = 'message-content';
        typingContent.innerHTML = '<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>';
        
        typingDiv.appendChild(typingContent);
        conversationDisplay.appendChild(typingDiv);
        
        // Scroll to bottom
        conversationDisplay.scrollTop = conversationDisplay.scrollHeight;
        
        return typingDiv;
    }

    function removeTypingIndicator(indicator) {
        if (indicator && indicator.parentNode) {
            indicator.parentNode.removeChild(indicator);
        }
    }

    function clearSessionOnLoad() {
        // Clear the conversation display immediately
        conversationDisplay.innerHTML = '';
        
        // Clear the session when page loads to start with a fresh conversation
        fetch('/api/session/clear', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            // Handle 401 Unauthorized - redirect to login
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            console.debug('Session cleared on page load');
        })
        .catch(error => {
            // Silently fail - session might not exist yet
            console.debug('Session clear on load:', error.message);
        });
    }

    // Logout button handler
    const logoutButton = document.getElementById('logout-button');
    if (logoutButton) {
        logoutButton.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Clear local conversation display
            conversationDisplay.innerHTML = '';
            
            // Redirect to logout endpoint
            window.location.href = '/logout';
        });
    }

    // Check session expiration periodically (every 5 minutes)
    setInterval(checkSessionExpiration, 5 * 60 * 1000);

    function checkSessionExpiration() {
        // Make a lightweight request to check if session is still valid
        fetch('/api/user', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            // Handle 401 Unauthorized - session expired
            if (response.status === 401) {
                // Show a message before redirecting
                displayError('Your session has expired. Redirecting to login...');
                setTimeout(() => {
                    window.location.href = '/login';
                }, 2000);
            }
        })
        .catch(error => {
            console.debug('Session check error:', error.message);
        });
    }

    // Focus on input when page loads
    messageInput.focus();
});
