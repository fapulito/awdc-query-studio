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
                addMessageToDisplay('assistant', data.response);
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

    function addMessageToDisplay(role, content) {
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
        
        const timestamp = document.createElement('div');
        timestamp.className = 'message-timestamp';
        timestamp.textContent = new Date().toLocaleTimeString();
        
        messageDiv.appendChild(messageContent);
        messageDiv.appendChild(timestamp);
        
        conversationDisplay.appendChild(messageDiv);
        
        // Scroll to bottom
        conversationDisplay.scrollTop = conversationDisplay.scrollHeight;
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
