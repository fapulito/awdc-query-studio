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
                addMessageToDisplay('assistant', data.response, data.queries || [], data.result || null);
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

    function addMessageToDisplay(role, content, queries, result) {
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

        // Chart — rendered before the SQL toggle so it sits right under the text
        if (role === 'assistant' && result) {
            var chartSpec = classifyChart(result);
            if (chartSpec) {
                messageDiv.appendChild(buildChart(result, chartSpec, queries || []));
            }
        }

        // "View SQL" transparency toggle — only for assistant messages with queries
        // (when a chart is present the toggle is already inlined inside the chart block)
        if (role === 'assistant' && Array.isArray(queries) && queries.length > 0 && !(result && classifyChart(result))) {
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


    // -----------------------------------------------------------------------
    // Chart classification and inline SVG rendering
    // All data comes from result.rows — nothing from the model's answer text.
    // -----------------------------------------------------------------------

    /**
     * Determine whether result is chartable and what chart type to use.
     * Returns {type, labelCol, valueCol} or null.
     *
     * Rules (applied in order):
     *   1. date/month bucket col + numeric col → "line"
     *   2. categorical text col + numeric col → "bar"
     *   3. otherwise → null (no chart)
     *
     * A column is "date-like" if its name contains date/month/year/period/week/day
     * OR if the first non-null value looks like an ISO date (YYYY-MM... or YYYY-01-01...).
     * A column is "numeric" if the first non-null value is a JS number (not a string).
     */
    function classifyChart(result) {
        if (!result || !Array.isArray(result.columns) || !Array.isArray(result.rows)) return null;
        if (result.rows.length === 0) return null;
        var cols = result.columns;
        if (cols.length < 2) return null;

        // Find first non-null value for each column
        function firstVal(col) {
            for (var i = 0; i < result.rows.length; i++) {
                var v = result.rows[i][col];
                if (v !== null && v !== undefined && v !== '') return v;
            }
            return null;
        }

        function isDateLike(col) {
            var nameLower = col.toLowerCase();
            if (/date|month|year|period|week|day/.test(nameLower)) return true;
            var v = firstVal(col);
            if (typeof v === 'string' && /^\d{4}-\d{2}/.test(v)) return true;
            return false;
        }

        function isNumeric(col) {
            var v = firstVal(col);
            return typeof v === 'number';
        }

        // Try date+numeric pair
        for (var i = 0; i < cols.length; i++) {
            if (isDateLike(cols[i])) {
                for (var j = 0; j < cols.length; j++) {
                    if (j !== i && isNumeric(cols[j])) {
                        return {type: 'line', labelCol: cols[i], valueCol: cols[j]};
                    }
                }
            }
        }

        // Try categorical+numeric pair (first categorical col, first numeric col)
        var catCol = null, numCol = null;
        for (var i = 0; i < cols.length; i++) {
            var v = firstVal(cols[i]);
            if (typeof v === 'string' && !isDateLike(cols[i]) && catCol === null) catCol = cols[i];
            if (isNumeric(cols[i]) && numCol === null) numCol = cols[i];
        }
        if (catCol && numCol) {
            return {type: 'bar', labelCol: catCol, valueCol: numCol};
        }

        return null;
    }

    /**
     * Build the chart container element (visible by default).
     * Includes an inlined "View SQL" provenance toggle if queries is non-empty.
     */
    function buildChart(result, spec, queries) {
        var wrapper = document.createElement('div');
        wrapper.className = 'chart-wrapper';

        // Title row
        var titleRow = document.createElement('div');
        titleRow.className = 'chart-title-row';
        var titleSpan = document.createElement('span');
        titleSpan.className = 'chart-title';
        titleSpan.textContent = spec.valueCol + ' by ' + spec.labelCol;
        titleRow.appendChild(titleSpan);
        wrapper.appendChild(titleRow);

        // Build the SVG chart
        var svgEl = spec.type === 'line'
            ? buildLineChart(result, spec)
            : buildBarChart(result, spec);
        wrapper.appendChild(svgEl);

        // Inline "View SQL" provenance toggle
        if (Array.isArray(queries) && queries.length > 0) {
            wrapper.appendChild(buildSqlToggle(queries));
        }

        return wrapper;
    }

    /** Prepare data for line chart: extract (label, value) pairs sorted by label. */
    function prepLineData(result, spec) {
        return result.rows
            .map(function(row) { return {label: String(row[spec.labelCol] || ''), value: row[spec.valueCol]}; })
            .sort(function(a, b) { return a.label < b.label ? -1 : a.label > b.label ? 1 : 0; });
    }

    /**
     * Prepare data for bar chart: sort descending by value, top 12 categories,
     * remaining grouped as "Other".
     */
    function prepBarData(result, spec) {
        var pairs = result.rows.map(function(row) {
            return {label: String(row[spec.labelCol] || ''), value: row[spec.valueCol]};
        });
        pairs.sort(function(a, b) { return b.value - a.value; });
        var MAX_BARS = 12;
        if (pairs.length <= MAX_BARS) return pairs;
        var top = pairs.slice(0, MAX_BARS);
        var otherSum = pairs.slice(MAX_BARS).reduce(function(s, p) { return s + p.value; }, 0);
        top.push({label: 'Other', value: otherSum});
        return top;
    }

    /** Format a number for axis labels (compact notation for large values). */
    function fmtNum(n) {
        if (n === null || n === undefined) return '';
        if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
        if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
        return String(n);
    }

    /** Create an SVG element with given width/height. */
    function makeSvg(w, h) {
        var el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        el.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
        el.setAttribute('width', '100%');
        el.setAttribute('height', h);
        el.style.display = 'block';
        return el;
    }

    /** SVG text element helper. */
    function svgText(x, y, txt, cls) {
        var el = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        el.setAttribute('x', x);
        el.setAttribute('y', y);
        if (cls) el.setAttribute('class', cls);
        el.textContent = txt;
        return el;
    }

    function buildLineChart(result, spec) {
        var data = prepLineData(result, spec);
        if (data.length === 0) return document.createDocumentFragment();

        var W = 560, H = 220;
        var PAD_L = 52, PAD_R = 16, PAD_T = 16, PAD_B = 48;
        var plotW = W - PAD_L - PAD_R;
        var plotH = H - PAD_T - PAD_B;

        var values = data.map(function(d) { return d.value; });
        var minV = Math.min.apply(null, values);
        var maxV = Math.max.apply(null, values);
        if (minV === maxV) { minV = 0; }

        function xPos(i) { return PAD_L + (data.length > 1 ? i / (data.length - 1) : 0.5) * plotW; }
        function yPos(v) { return PAD_T + plotH - ((v - minV) / (maxV - minV || 1)) * plotH; }

        var svg = makeSvg(W, H);

        // Y grid lines + labels (5 ticks)
        var TICKS = 5;
        for (var t = 0; t <= TICKS; t++) {
            var yv = minV + (maxV - minV) * t / TICKS;
            var ypx = yPos(yv);
            var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            line.setAttribute('x1', PAD_L); line.setAttribute('x2', W - PAD_R);
            line.setAttribute('y1', ypx); line.setAttribute('y2', ypx);
            line.setAttribute('class', 'chart-grid');
            svg.appendChild(line);
            svg.appendChild(svgText(PAD_L - 4, ypx + 4, fmtNum(Math.round(yv)), 'chart-axis-label chart-axis-right'));
        }

        // X axis labels (show up to 8 evenly spaced)
        var XLABELS = Math.min(8, data.length);
        for (var i = 0; i < XLABELS; i++) {
            var idx = Math.round(i * (data.length - 1) / (XLABELS > 1 ? XLABELS - 1 : 1));
            var xpx = xPos(idx);
            var lbl = data[idx].label;
            if (lbl.length > 10) lbl = lbl.slice(0, 7) + '…';
            svg.appendChild(svgText(xpx, H - PAD_B + 16, lbl, 'chart-axis-label chart-axis-center'));
        }

        // Axis lines
        var axisX = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        axisX.setAttribute('x1', PAD_L); axisX.setAttribute('x2', W - PAD_R);
        axisX.setAttribute('y1', PAD_T + plotH); axisX.setAttribute('y2', PAD_T + plotH);
        axisX.setAttribute('class', 'chart-axis');
        svg.appendChild(axisX);

        // Polyline
        var pts = data.map(function(d, i) { return xPos(i) + ',' + yPos(d.value); }).join(' ');
        var poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        poly.setAttribute('points', pts);
        poly.setAttribute('class', 'chart-line');
        svg.appendChild(poly);

        // Dots
        data.forEach(function(d, i) {
            var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('cx', xPos(i));
            circle.setAttribute('cy', yPos(d.value));
            circle.setAttribute('r', data.length <= 24 ? 3 : 2);
            circle.setAttribute('class', 'chart-dot');
            svg.appendChild(circle);
        });

        // Axis column name labels
        svg.appendChild(svgText(W / 2, H - 4, spec.labelCol, 'chart-col-label chart-axis-center'));

        return svg;
    }

    function buildBarChart(result, spec) {
        var data = prepBarData(result, spec);
        if (data.length === 0) return document.createDocumentFragment();

        var BAR_H = 22, BAR_GAP = 6;
        var PAD_L = 110, PAD_R = 60, PAD_T = 12, PAD_B = 20;
        var W = 560;
        var H = PAD_T + data.length * (BAR_H + BAR_GAP) + PAD_B;
        var plotW = W - PAD_L - PAD_R;

        var maxV = Math.max.apply(null, data.map(function(d) { return d.value; }));

        var svg = makeSvg(W, H);

        data.forEach(function(d, i) {
            var y = PAD_T + i * (BAR_H + BAR_GAP);
            var barW = maxV > 0 ? (d.value / maxV) * plotW : 0;

            // Bar
            var rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            rect.setAttribute('x', PAD_L);
            rect.setAttribute('y', y);
            rect.setAttribute('width', Math.max(barW, 1));
            rect.setAttribute('height', BAR_H);
            rect.setAttribute('class', 'chart-bar');
            svg.appendChild(rect);

            // Category label (left)
            var lbl = d.label.length > 14 ? d.label.slice(0, 12) + '…' : d.label;
            svg.appendChild(svgText(PAD_L - 6, y + BAR_H / 2 + 4, lbl, 'chart-axis-label chart-axis-right'));

            // Value label (right of bar)
            svg.appendChild(svgText(PAD_L + barW + 4, y + BAR_H / 2 + 4, fmtNum(d.value), 'chart-bar-value'));
        });

        // Column name label (bottom right)
        svg.appendChild(svgText(W - PAD_R + 4, H - 4, spec.valueCol, 'chart-col-label'));

        return svg;
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
