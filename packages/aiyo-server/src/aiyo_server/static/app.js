/**
 * AIYO WebUI - Client Application
 */

// DOM Elements
const messagesEl = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const modelNameEl = document.getElementById('model-name');
const tokenCountEl = document.getElementById('token-count');

// State
let ws = null;
let isConnected = false;
let isProcessing = false;
let currentMessageEl = null;
let activeTools = new Map();
let messageHistory = [];
let appTagline = '';

// Initialize
function init() {
    connect();
    setupEventListeners();
    showBanner();
}

// Connect to WebSocket
function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        isConnected = true;
        updateSendButton();
    };

    ws.onclose = () => {
        isConnected = false;
        isProcessing = false;
        updateSendButton();

        // Reconnect after delay
        setTimeout(connect, 3000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
    };
}

// Handle messages from server
function handleServerMessage(data) {
    switch (data.type) {
        case 'welcome':
            document.title = data.app_name || 'AI Agent';
            appTagline = data.app_tagline || '';
            modelNameEl.textContent = data.model || '-';
            // Update banner if still on page
            const bannerH1 = document.querySelector('.banner h1');
            if (bannerH1) bannerH1.textContent = data.app_name || 'AI Agent';
            const bannerP = document.querySelector('.banner p');
            if (bannerP && appTagline) bannerP.textContent = appTagline;
            break;

        case 'status':
            modelNameEl.textContent = data.model || '-';
            tokenCountEl.textContent = `${data.tokens?.total ?? 0} tokens · Turn ${data.turns ?? 0}`;
            break;

        case 'thinking':
            showThinking();
            break;

        case 'tool_start':
            showToolStart(data);
            break;

        case 'tool_end':
            showToolEnd(data);
            break;

        case 'ask_user':
            showAskUser(data);
            break;

        case 'chat_end':
            showChatEnd(data);
            break;

        case 'error':
            showError(data.message);
            break;

        case 'reset_done':
            clearMessages();
            showBanner();
            break;

        case 'compact_done':
            // Compact completed
            break;
    }
}

// Show initial banner
function showBanner() {
    const banner = document.createElement('div');
    banner.className = 'banner';
    const appName = document.title || 'AI Agent';
    banner.innerHTML = `
        <h1>${escapeHtml(appName)}</h1>
        <p>${escapeHtml(appTagline)}</p>
    `;
    messagesEl.appendChild(banner);
    scrollToBottom();
}

// Show thinking indicator
function showThinking() {
    removeThinking();
    const thinking = document.createElement('div');
    thinking.className = 'thinking';
    thinking.id = 'thinking-indicator';
    thinking.textContent = 'Thinking...';
    messagesEl.appendChild(thinking);
    scrollToBottom();
}

// Remove thinking indicator
function removeThinking() {
    const existing = document.getElementById('thinking-indicator');
    if (existing) existing.remove();
}

// Show tool start
function showToolStart(data) {
    removeThinking();

    const toolCard = document.createElement('div');
    toolCard.className = 'tool-card running';
    toolCard.id = data.id;
    toolCard.innerHTML = `
        <span class="status-dot"></span>
        <span class="tool-name">${escapeHtml(data.tool)}</span>
        <span class="tool-summary">${escapeHtml(data.summary)}</span>
    `;

    messagesEl.appendChild(toolCard);
    activeTools.set(data.id, toolCard);
    scrollToBottom();
}

// Show tool end
function showToolEnd(data) {
    const toolCard = activeTools.get(data.id);
    if (toolCard) {
        toolCard.classList.remove('running');
        if (data.error) {
            toolCard.classList.add('error');
        } else {
            toolCard.classList.add('success');
        }
        activeTools.delete(data.id);
    }
}

// Show ask_user form
function showAskUser(data) {
    removeThinking();

    const formEl = document.createElement('div');
    formEl.className = 'ask-user-form';

    (data.questions || []).forEach((q, qi) => {
        const qEl = document.createElement('div');
        qEl.className = 'ask-user-question';

        // Label row
        const labelEl = document.createElement('div');
        labelEl.className = 'ask-user-label';
        if (q.header) {
            const chip = document.createElement('span');
            chip.className = 'ask-user-chip';
            chip.textContent = q.header;
            labelEl.appendChild(chip);
        }
        labelEl.appendChild(document.createTextNode(q.question));
        qEl.appendChild(labelEl);

        const options = q.options || [];
        if (options.length > 0) {
            const optsEl = document.createElement('div');
            optsEl.className = 'ask-user-options';

            [...options, { label: 'Other', _other: true }].forEach((opt) => {
                const lbl = document.createElement('label');
                lbl.className = 'ask-user-option';

                const input = document.createElement('input');
                input.type = q.multi_select ? 'checkbox' : 'radio';
                input.name = `ask-q${qi}`;
                input.value = opt._other ? '__other__' : opt.label;
                lbl.appendChild(input);

                const textEl = document.createElement('span');
                textEl.className = 'ask-user-option-text';
                textEl.textContent = opt.label;
                lbl.appendChild(textEl);

                if (opt.description) {
                    const descEl = document.createElement('span');
                    descEl.className = 'ask-user-option-desc';
                    descEl.textContent = opt.description;
                    lbl.appendChild(descEl);
                }

                if (opt._other) {
                    const otherInput = document.createElement('input');
                    otherInput.type = 'text';
                    otherInput.className = 'ask-user-other-input';
                    otherInput.placeholder = 'Type your answer...';
                    otherInput.style.display = 'none';
                    input.addEventListener('change', () => {
                        otherInput.style.display = input.checked ? 'block' : 'none';
                        if (input.checked) otherInput.focus();
                    });
                    lbl.appendChild(otherInput);
                }

                optsEl.appendChild(lbl);
            });

            qEl.appendChild(optsEl);
        } else {
            const textInput = document.createElement('input');
            textInput.type = 'text';
            textInput.className = 'ask-user-text-input';
            textInput.placeholder = 'Type your answer...';
            qEl.appendChild(textInput);
        }

        formEl.appendChild(qEl);
    });

    const submitBtn = document.createElement('button');
    submitBtn.className = 'ask-user-submit';
    submitBtn.textContent = 'Submit';
    submitBtn.addEventListener('click', () => {
        const answers = {};
        const annotations = {};

        (data.questions || []).forEach((q, qi) => {
            const qEl = formEl.querySelectorAll('.ask-user-question')[qi];
            const options = q.options || [];

            if (options.length > 0) {
                const checked = [...qEl.querySelectorAll(`input[name="ask-q${qi}"]:checked`)];
                const values = checked.map(cb => {
                    if (cb.value === '__other__') {
                        return qEl.querySelector('.ask-user-other-input').value.trim() || 'Other';
                    }
                    return cb.value;
                });
                answers[q.question] = q.multi_select ? values.join(', ') : (values[0] || '');
            } else {
                answers[q.question] = qEl.querySelector('.ask-user-text-input').value.trim();
            }
            annotations[q.question] = { preview: null, notes: null };
        });

        // Replace form with user bubble summary
        const summaryEl = document.createElement('div');
        summaryEl.className = 'message user';
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.textContent = Object.values(answers).filter(Boolean).join(' / ') || '(submitted)';
        summaryEl.appendChild(bubble);
        formEl.replaceWith(summaryEl);

        ws.send(JSON.stringify({
            type: 'ask_user_response',
            ask_user_id: data.id,
            answers,
            annotations,
            metadata: { source: 'ask_user' },
        }));
        scrollToBottom();
    });

    formEl.appendChild(submitBtn);
    messagesEl.appendChild(formEl);
    scrollToBottom();
}

// Show chat response
function showChatEnd(data) {
    removeThinking();
    isProcessing = false;
    updateSendButton();

    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';

    // Render markdown content
    const renderedContent = marked.parse(data.content || '');

    messageDiv.innerHTML = `
        <div class="avatar">AI</div>
        <div class="content">${renderedContent}</div>
    `;

    messagesEl.appendChild(messageDiv);

    // Apply syntax highlighting
    messageDiv.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightElement(block);
    });

    scrollToBottom();
}

// Show error
function showError(message) {
    removeThinking();
    isProcessing = false;
    updateSendButton();

    const errorDiv = document.createElement('div');
    errorDiv.className = 'message assistant';
    errorDiv.innerHTML = `
        <div class="avatar" style="background: var(--error)">!</div>
        <div class="content" style="color: var(--error)">${escapeHtml(message)}</div>
    `;
    messagesEl.appendChild(errorDiv);
    scrollToBottom();
}

// Send message
function sendMessage() {
    const text = messageInput.value.trim();
    if (!text || !isConnected || isProcessing) return;

    // Add user message
    addUserMessage(text);

    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';

    // Send to server
    ws.send(JSON.stringify({
        type: 'chat',
        text: text
    }));

    isProcessing = true;
    updateSendButton();
}

// Add user message to UI
function addUserMessage(text) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message user';
    messageDiv.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
    messagesEl.appendChild(messageDiv);
    scrollToBottom();

    // Store in history
    messageHistory.push({ role: 'user', content: text });
}

// Clear all messages
function clearMessages() {
    messagesEl.innerHTML = '';
    messageHistory = [];
    activeTools.clear();
}

// Scroll to bottom of messages
function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

const ICON_SEND = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>`;
const ICON_CANCEL = `<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`;

// Update send/cancel button state
function updateSendButton() {
    if (isProcessing) {
        sendBtn.disabled = false;
        sendBtn.classList.add('cancel');
        sendBtn.innerHTML = ICON_CANCEL;
        messageInput.disabled = true;
    } else {
        sendBtn.disabled = !isConnected || !messageInput.value.trim();
        sendBtn.classList.remove('cancel');
        sendBtn.innerHTML = ICON_SEND;
        messageInput.disabled = false;
    }
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Setup event listeners
function setupEventListeners() {
    // Send / cancel button
    sendBtn.addEventListener('click', () => {
        if (isProcessing) {
            if (ws) ws.send(JSON.stringify({ type: 'cancel' }));
        } else {
            sendMessage();
        }
    });

    // Input handling
    messageInput.addEventListener('input', () => {
        // Auto-resize textarea
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + 'px';
        updateSendButton();
    });

    // Key handling
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        } else if (e.key === 'Escape') {
            // Cancel current operation
            if (isProcessing && ws) {
                ws.send(JSON.stringify({ type: 'cancel' }));
            }
        }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + K to focus input
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            messageInput.focus();
        }

        // Ctrl/Cmd + Shift + R to reset
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'R') {
            e.preventDefault();
            if (ws) {
                ws.send(JSON.stringify({ type: 'reset' }));
            }
        }
    });
}

// Start
init();
