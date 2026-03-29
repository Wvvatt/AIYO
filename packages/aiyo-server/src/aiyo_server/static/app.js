/**
 * AIYO WebUI - Client Application
 */

// DOM Elements
const messagesEl = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const modelNameEl = document.getElementById('model-name');
const tokenCountEl = document.getElementById('token-count');
const modeIndicator = document.getElementById('mode-indicator');

// State
let ws = null;
let isConnected = false;
let isProcessing = false;
let currentMessageEl = null;
let activeTools = new Map();
let messageHistory = [];

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
            modelNameEl.textContent = data.model || 'AIYO';
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
    banner.innerHTML = `
        <h1>AIYO</h1>
        <p>AI Agent ready to help</p>
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

// Update send button state
function updateSendButton() {
    sendBtn.disabled = !isConnected || isProcessing || !messageInput.value.trim();
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Setup event listeners
function setupEventListeners() {
    // Send button
    sendBtn.addEventListener('click', sendMessage);

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
