/**
 * AIYO WebUI - Kimi Code Style
 */

// DOM Elements
const messagesEl = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const cancelBtn = document.getElementById('cancel-btn');
const headerTitle = document.getElementById('header-title');
const toolHistoryEl = document.getElementById('tool-history');
const appContainer = document.getElementById('app');

// Stats elements
const modelNameEl = document.getElementById('model-name');
const inputTokensEl = document.getElementById('input-tokens');
const outputTokensEl = document.getElementById('output-tokens');
const totalTokensEl = document.getElementById('total-tokens');
const turnCountEl = document.getElementById('turn-count');

// Slash commands definition
const SLASH_COMMANDS = [
    { name: '/help',    desc: 'Show available commands' },
    { name: '/clear',   desc: 'Clear conversation' },
    { name: '/reset',   desc: 'Reset agent session' },
    { name: '/compact', desc: 'Compress conversation history' },
];

// State
let ws = null;
let isConnected = false;
let isProcessing = false;
let currentMessageEl = null;
let messageHistory = [];
let toolHistory = [];
let appTagline = '';
let currentStats = { model: '-', input: 0, output: 0, turns: 0 };

// Initialize
function init() {
    connect();
    setupEventListeners();
    setupToggles();
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

// Setup event listeners
function setupEventListeners() {
    sendBtn.addEventListener('click', () => {
        sendMessage();
    });

    // Cancel button click handler
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            if (isProcessing && ws) {
                ws.send(JSON.stringify({ type: 'cancel' }));
            }
        });
    }

    messageInput.addEventListener('input', () => {
        updateSendButton();
        autoResize(messageInput);
        updateSlashAutocomplete();
    });

    messageInput.addEventListener('keydown', (e) => {
        if (handleAutocompleteKey(e)) return;
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!isProcessing && messageInput.value.trim()) {
                sendMessage();
            }
        }
        if (e.key === 'Escape') hideAutocomplete();
    });

    messageInput.addEventListener('blur', () => {
        // Delay so click on autocomplete item fires first
        setTimeout(hideAutocomplete, 150);
    });

    document.getElementById('toggle-right-sidebar').addEventListener('click', () => {
        appContainer.classList.toggle('right-collapsed');
    });
}

// Setup toggles (future: Thinking/Plan modes)
function setupToggles() {
    // Thinking and Plan toggles not yet implemented
}

// Auto resize textarea
function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

// Send message
function sendMessage() {
    const text = messageInput.value.trim();
    if (!text || !isConnected || isProcessing) return;

    hideAutocomplete();
    messageInput.value = '';
    messageInput.style.height = 'auto';
    updateSendButton();

    if (text.startsWith('/')) {
        handleSlashCommand(text);
        return;
    }

    showUserMessage(text);
    ws.send(JSON.stringify({ type: 'chat', text }));
    isProcessing = true;
}

// Handle slash commands
function handleSlashCommand(cmd) {
    const name = cmd.split(' ')[0].toLowerCase();
    switch (name) {
        case '/help':
            showHelp();
            break;
        case '/clear':
            messagesEl.innerHTML = '';
            toolHistory = [];
            renderToolHistory();
            showBanner();
            headerTitle.textContent = 'New Chat';
            break;
        case '/reset':
            if (isConnected) ws.send(JSON.stringify({ type: 'reset' }));
            break;
        case '/compact':
            if (isConnected) {
                showSystemMessage('Compacting history...');
                ws.send(JSON.stringify({ type: 'compact' }));
            }
            break;
        default:
            showSystemMessage(`Unknown command: ${escapeHtml(cmd)}. Type /help for available commands.`, 'error');
    }
}

// Show help in conversation
function showHelp() {
    const banner = document.querySelector('.banner');
    if (banner) banner.remove();
    const el = document.createElement('div');
    el.className = 'system-message';
    el.innerHTML = `
        <div class="system-message-title">Available Commands</div>
        <div class="command-list">
            ${SLASH_COMMANDS.map(c =>
                `<div class="command-item"><span class="command-name">${escapeHtml(c.name)}</span><span class="command-desc">${escapeHtml(c.desc)}</span></div>`
            ).join('')}
        </div>`;
    messagesEl.appendChild(el);
    scrollToBottom();
}

// Show stats in conversation
function showStats() {
    const banner = document.querySelector('.banner');
    if (banner) banner.remove();
    const el = document.createElement('div');
    el.className = 'system-message';
    el.innerHTML = `
        <div class="system-message-title">Session Stats</div>
        <div class="command-list">
            <div class="command-item"><span class="command-name">Model</span><span class="command-desc">${escapeHtml(currentStats.model)}</span></div>
            <div class="command-item"><span class="command-name">Input tokens</span><span class="command-desc">${currentStats.input}</span></div>
            <div class="command-item"><span class="command-name">Output tokens</span><span class="command-desc">${currentStats.output}</span></div>
            <div class="command-item"><span class="command-name">Turns</span><span class="command-desc">${currentStats.turns}</span></div>
        </div>`;
    messagesEl.appendChild(el);
    scrollToBottom();
}

// Show a system/info message in conversation
function showSystemMessage(text, type = 'info') {
    const banner = document.querySelector('.banner');
    if (banner) banner.remove();
    const el = document.createElement('div');
    el.className = `system-message ${type}`;
    el.textContent = text;
    messagesEl.appendChild(el);
    scrollToBottom();
}

// ── Slash autocomplete ──────────────────────────────────────────────────────

let autocompleteEl = null;
let autocompleteIndex = -1;
let autocompleteItems = [];

function updateSlashAutocomplete() {
    const val = messageInput.value;
    if (!val.startsWith('/') || val.includes(' ')) {
        hideAutocomplete();
        return;
    }
    const matches = SLASH_COMMANDS.filter(c => c.name.startsWith(val.toLowerCase()));
    if (matches.length === 0) { hideAutocomplete(); return; }

    autocompleteItems = matches;
    autocompleteIndex = -1;

    if (!autocompleteEl) {
        autocompleteEl = document.createElement('div');
        autocompleteEl.id = 'slash-autocomplete';
        document.getElementById('input-container').appendChild(autocompleteEl);
    }

    autocompleteEl.innerHTML = matches.map((c, i) => `
        <div class="autocomplete-item" data-index="${i}">
            <span class="autocomplete-name">${escapeHtml(c.name)}</span>
            <span class="autocomplete-desc">${escapeHtml(c.desc)}</span>
        </div>`).join('');

    autocompleteEl.querySelectorAll('.autocomplete-item').forEach(item => {
        item.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const idx = parseInt(item.dataset.index);
            applyAutocomplete(idx);
        });
    });

    autocompleteEl.style.display = 'block';
}

function hideAutocomplete() {
    if (autocompleteEl) autocompleteEl.style.display = 'none';
    autocompleteIndex = -1;
}

function applyAutocomplete(idx) {
    if (idx < 0 || idx >= autocompleteItems.length) return;
    messageInput.value = autocompleteItems[idx].name + ' ';
    hideAutocomplete();
    messageInput.focus();
    updateSendButton();
}

function handleAutocompleteKey(e) {
    if (!autocompleteEl || autocompleteEl.style.display === 'none') return false;
    const items = autocompleteEl.querySelectorAll('.autocomplete-item');
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        autocompleteIndex = Math.min(autocompleteIndex + 1, items.length - 1);
        items.forEach((el, i) => el.classList.toggle('active', i === autocompleteIndex));
        return true;
    }
    if (e.key === 'ArrowUp') {
        e.preventDefault();
        autocompleteIndex = Math.max(autocompleteIndex - 1, -1);
        items.forEach((el, i) => el.classList.toggle('active', i === autocompleteIndex));
        return true;
    }
    if (e.key === 'Tab' || e.key === 'Enter') {
        if (autocompleteIndex >= 0) {
            e.preventDefault();
            applyAutocomplete(autocompleteIndex);
            return true;
        }
        if (e.key === 'Tab' && autocompleteItems.length > 0) {
            e.preventDefault();
            applyAutocomplete(0);
            return true;
        }
    }
    return false;
}

// Show user message
function showUserMessage(text) {
    // Remove banner if exists
    const banner = document.querySelector('.banner');
    if (banner) banner.remove();

    const msgEl = document.createElement('div');
    msgEl.className = 'message user';
    msgEl.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
    messagesEl.appendChild(msgEl);
    scrollToBottom();
}

// Update send button and input state
function updateSendButton() {
    const hasText = messageInput.value.trim().length > 0;
    sendBtn.disabled = !isConnected || isProcessing || !hasText;
    // Show/hide cancel button based on processing state
    if (cancelBtn) {
        cancelBtn.style.display = isProcessing ? 'flex' : 'none';
    }
}

// Handle server messages
function handleServerMessage(data) {
    switch (data.type) {
        case 'welcome':
            document.title = data.app_name || 'AI Agent';
            appTagline = data.app_tagline || '';
            if (data.model) { currentStats.model = data.model; }
            if (modelNameEl) modelNameEl.textContent = data.model || '-';
            if (data.status) updateStatus(data.status);
            if (data.skills) renderSkills(data.skills);
            // Update banner if still visible
            const bannerH1 = document.querySelector('.banner h1');
            if (bannerH1) bannerH1.textContent = data.app_name || 'AI Agent';
            const bannerP = document.querySelector('.banner p');
            if (bannerP) bannerP.textContent = data.app_tagline || 'Start a conversation...';
            break;

        case 'status':
            updateStats(data);
            break;

        case 'thinking':
            showThinking();
            break;

        case 'tool_start':
            addToolToHistory({
                id: data.id,
                tool: data.tool,
                summary: data.summary,
                status: 'running'
            });
            if (data.tool === 'think' && data.thought) {
                showThought(data.id, data.thought);
            }
            break;

        case 'tool_end':
            const status = data.error ? 'error' : 'success';
            addToolToHistory({
                id: data.id,
                tool: data.tool || 'unknown',
                summary: data.summary || (data.error ? 'Error' : 'Completed'),
                status: status
            });
            if (data.task_result) {
                showTaskResult(data.task_result);
            }
            if (data.todos) {
                showTodoList(data.todos);
            }
            break;

        case 'ask_user':
            showAskUser(data);
            break;

        case 'chat_end':
            showChatEnd(data);
            isProcessing = false;
            updateSendButton();
            break;

        case 'error':
            showError(data.message);
            isProcessing = false;
            updateSendButton();
            break;

        case 'cancelled':
            removeThinking();
            isProcessing = false;
            updateSendButton();
            break;

        case 'reset_done':
            messagesEl.innerHTML = '';
            toolHistory = [];
            renderToolHistory();
            showBanner();
            headerTitle.textContent = 'New Chat';
            break;
    }
}

// Update stats
function updateStats(data) {
    if (data.model) {
        currentStats.model = data.model;
        if (modelNameEl) modelNameEl.textContent = data.model;
    }
    if (data.tokens) {
        currentStats.input = data.tokens.input ?? 0;
        currentStats.output = data.tokens.output ?? 0;
        if (inputTokensEl) inputTokensEl.textContent = currentStats.input;
        if (outputTokensEl) outputTokensEl.textContent = currentStats.output;
        if (totalTokensEl) totalTokensEl.textContent = data.tokens.total ?? 0;
    }
    if (data.turns != null) {
        currentStats.turns = data.turns;
        if (turnCountEl) turnCountEl.textContent = data.turns;
    }
}

// Update service status
function updateStatus(status) {
    // Support both {services: {...}} and direct {...} format
    const services = status.services || status;

    ['jira', 'confluence', 'gerrit'].forEach(svc => {
        const dot = document.getElementById(`${svc}-dot`);
        const text = document.getElementById(`${svc}-status`);
        if (!dot || !text) return;

        const state = services[svc];
        dot.className = 'status-dot';

        if (state === 'online') {
            dot.classList.add('online');
            text.textContent = 'Online';
        } else if (state === 'offline') {
            dot.classList.add('offline');
            text.textContent = 'Offline';
        } else if (state) {
            // Unknown status value
            text.textContent = String(state);
        } else {
            text.textContent = '-';
        }
    });
}

// Tool history
function addToolToHistory(toolData) {
    const item = {
        id: toolData.id,
        name: toolData.tool,
        summary: toolData.summary,
        status: toolData.status,
        timestamp: new Date()
    };

    const existingIndex = toolHistory.findIndex(t => t.id === item.id);
    if (existingIndex >= 0) {
        toolHistory[existingIndex] = item;
    } else {
        toolHistory.unshift(item);
    }

    if (toolHistory.length > 50) {
        toolHistory = toolHistory.slice(0, 50);
    }

    renderToolHistory();
}

function renderToolHistory() {
    if (!toolHistoryEl) return;

    if (toolHistory.length === 0) {
        toolHistoryEl.innerHTML = '<div class="empty-state">Tool calls will appear here</div>';
        return;
    }

    toolHistoryEl.innerHTML = toolHistory.map(item => `
        <div class="tool-history-item ${item.status}">
            <div class="tool-row">
                <span class="tool-name">${escapeHtml(item.name)}</span>
                <span class="tool-status-badge ${item.status}">
                    ${item.status === 'running' ? '●' : item.status === 'success' ? '✓' : '✗'}
                </span>
            </div>
            <div class="tool-summary">${escapeHtml(item.summary)}</div>
        </div>
    `).join('');
}

// Show banner
function showBanner() {
    const banner = document.createElement('div');
    banner.className = 'banner';
    banner.innerHTML = `
        <h1>${document.title}</h1>
        <p>${appTagline || 'Start a conversation...'}</p>
    `;
    messagesEl.appendChild(banner);
}

// Show thinking
function showThinking() {
    removeThinking();
    const thinking = document.createElement('div');
    thinking.className = 'thinking';
    thinking.id = 'thinking-indicator';
    thinking.textContent = 'Thinking...';
    messagesEl.appendChild(thinking);
    scrollToBottom();
}

function removeThinking() {
    const indicator = document.getElementById('thinking-indicator');
    if (indicator) indicator.remove();
}

// Show chat end
function showChatEnd(data) {
    removeThinking();

    if (!currentMessageEl) {
        currentMessageEl = document.createElement('div');
        currentMessageEl.className = 'message assistant';
        currentMessageEl.innerHTML = '<div class="avatar">AI</div><div class="content"></div>';
        messagesEl.appendChild(currentMessageEl);
    }

    const content = currentMessageEl.querySelector('.content');
    content.innerHTML = marked.parse(data.content || '');

    content.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightElement(block);
    });

    currentMessageEl = null;
    scrollToBottom();
}

// Show ask user form
function showAskUser(data) {
    removeThinking();

    const formEl = document.createElement('div');
    formEl.className = 'ask-user-form';

    data.questions.forEach((q, qi) => {
        const qEl = document.createElement('div');
        qEl.className = 'ask-user-question';

        const labelEl = document.createElement('div');
        labelEl.className = 'ask-user-label';
        labelEl.textContent = q.question;
        qEl.appendChild(labelEl);

        if (q.options && q.options.length > 0) {
            const optsEl = document.createElement('div');
            optsEl.className = 'ask-user-options';

            q.options.forEach((opt) => {
                const lbl = document.createElement('label');
                lbl.className = 'ask-user-option';

                const input = document.createElement('input');
                input.type = q.multi_select ? 'checkbox' : 'radio';
                input.name = `q${qi}`;
                input.value = opt.label;

                const textEl = document.createElement('span');
                textEl.textContent = opt.label;

                lbl.appendChild(input);
                lbl.appendChild(textEl);
                optsEl.appendChild(lbl);
            });

            qEl.appendChild(optsEl);
        }

        formEl.appendChild(qEl);
    });

    const submitBtn = document.createElement('button');
    submitBtn.className = 'ask-user-submit';
    submitBtn.textContent = 'Submit';
    submitBtn.addEventListener('click', () => {
        const answers = {};
        data.questions.forEach((q, qi) => {
            const inputs = formEl.querySelectorAll(`input[name="q${qi}"]:checked`);
            answers[q.question] = Array.from(inputs).map(i => i.value).join(', ');
        });

        ws.send(JSON.stringify({
            type: 'ask_user_response',
            ask_user_id: data.id,
            answers,
            annotations: {},
            metadata: { source: 'ask_user' }
        }));

        formEl.remove();
    });

    formEl.appendChild(submitBtn);
    messagesEl.appendChild(formEl);
    scrollToBottom();
}

// Show error
function showError(message) {
    removeThinking();
    const errorEl = document.createElement('div');
    errorEl.className = 'message assistant';
    errorEl.innerHTML = `<div class="avatar" style="background:#ef4444">!</div><div class="content" style="color:#ef4444">${escapeHtml(message)}</div>`;
    messagesEl.appendChild(errorEl);
    scrollToBottom();
}

// Scroll to bottom
function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Todo status icons (○ pending, ◐ in_progress, ● done)
const TODO_STATUS_ICON = { pending: '○', in_progress: '◐', done: '●' };
const TODO_STATUS_CLASS = { pending: 'pending', in_progress: 'in-progress', done: 'done' };

// Show todo list in conversation
function showTodoList(todos) {
    if (!todos || todos.length === 0) return;

    const banner = document.querySelector('.banner');
    if (banner) banner.remove();

    const el = document.createElement('div');
    el.className = 'todo-card';

    el.innerHTML = `<div class="todo-card-header">Todo List</div>` +
        todos.map(t => `
        <div class="todo-item">
            <span class="todo-icon ${TODO_STATUS_CLASS[t.status] || ''}">${TODO_STATUS_ICON[t.status] || '○'}</span>
            <span class="todo-title ${t.status === 'done' ? 'done' : ''}">${escapeHtml(t.title)}</span>
        </div>`).join('');

    messagesEl.appendChild(el);
    scrollToBottom();
}

// Show task result in conversation
const TASK_STATUS_ICON = { pending: '○', in_progress: '◑', completed: '●' };
const TASK_STATUS_CLASS = { pending: 'pending', in_progress: 'in-progress', completed: 'completed' };

function showTaskResult(result) {
    const action = result.action || '';
    if (action === 'delete') return; // no card for delete

    const tasks = result.tasks || (result.task ? [result.task] : []);
    if (tasks.length === 0) return;

    const banner = document.querySelector('.banner');
    if (banner) banner.remove();

    const el = document.createElement('div');
    el.className = 'task-card';

    const actionLabel = { create: 'Tasks Created', update: 'Task Updated', list: 'Tasks' }[action] || 'Tasks';
    el.innerHTML = `<div class="task-card-header">${escapeHtml(actionLabel)}</div>` +
        tasks.map(t => `
        <div class="task-item">
            <span class="task-icon ${TASK_STATUS_CLASS[t.status] || ''}">${TASK_STATUS_ICON[t.status] || '○'}</span>
            <div class="task-body">
                <div class="task-title">${escapeHtml(t.title)}</div>
                ${t.description ? `<div class="task-desc">${escapeHtml(t.description)}</div>` : ''}
            </div>
            <span class="task-priority ${t.priority || ''}">${escapeHtml(t.priority || '')}</span>
        </div>`).join('');

    messagesEl.appendChild(el);
    scrollToBottom();
}

// Show think content in conversation
function showThought(id, thought) {
    removeThinking();
    const el = document.createElement('div');
    el.className = 'thought-block';
    el.id = `thought-${id}`;
    el.innerHTML = `<div class="thought-label">Thinking</div><div class="thought-content">${escapeHtml(thought)}</div>`;
    messagesEl.appendChild(el);
    scrollToBottom();
}

// Render skills list
function renderSkills(skills) {
    const el = document.getElementById('skills-list');
    if (!el) return;
    if (!skills || skills.length === 0) {
        el.innerHTML = '<span class="info-label" style="font-size:11px">No skills loaded</span>';
        return;
    }
    el.innerHTML = '';
    skills.forEach(s => {
        const item = document.createElement('div');
        item.className = 'skill-item';
        item.title = 'Click to load skill into conversation';
        item.innerHTML = `<div class="skill-name">${escapeHtml(s.name)}</div><div class="skill-desc">${escapeHtml(s.description)}</div>`;
        item.addEventListener('click', () => loadSkill(s.name));
        el.appendChild(item);
    });
}

// Load a skill into the conversation
function loadSkill(name) {
    if (!isConnected || isProcessing) return;
    const text = `/skill ${name}`;
    showUserMessage(text);
    ws.send(JSON.stringify({ type: 'chat', text: `请加载并使用 skill: ${name}` }));
    isProcessing = true;
    updateSendButton();
}

// Init
init();
