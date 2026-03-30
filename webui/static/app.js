// SecureAgent Web UI - JavaScript
// Using Tailwind CSS + daisyUI

// Configure marked.js (Markdown renderer)
marked.setOptions({
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            try {
                return hljs.highlight(code, { language: lang }).value;
            } catch (e) {}
        }
        return hljs.highlightAuto(code).value;
    },
    breaks: true,
    gfm: true,
});

// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const clearBtn = document.getElementById('clearBtn');
const modelNameEl = document.getElementById('modelName');
const agentStatusEl = document.getElementById('agentStatus');

// State
let isGenerating = false;
let sessionId = generateUUID();
let useRag = false; // RAG toggle state, initialized from backend /api/info
let skillsEnabled = false; // Skills System toggle state, initialized from backend /api/info

// Generate UUID
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Theme toggle
function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
}

// Update send button state based on input
function updateSendButton() {
    const hasContent = messageInput.value.trim().length > 0;
    if (hasContent && !isGenerating) {
        sendBtn.classList.add('active');
        sendBtn.disabled = false;
    } else {
        sendBtn.classList.remove('active');
        sendBtn.disabled = true;
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('theme') || 'light';
    setTheme(savedTheme);
    renderWelcome();
    fetchAgentInfo();
    
    // Auto-resize textarea and update button
    messageInput.addEventListener('input', () => {
        autoResize();
        updateSendButton();
    });
    
    // Keyboard events
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (messageInput.value.trim()) {
                sendMessage();
            }
        }
    });
    
    // Send button click
    sendBtn.addEventListener('click', sendMessage);
    
    // Clear button
    clearBtn.addEventListener('click', clearChat);

    // MCP source switch
    var mcpBtnLocal = document.getElementById('mcpBtnLocal');
    var mcpBtnCloud = document.getElementById('mcpBtnCloud');
    if (mcpBtnLocal) mcpBtnLocal.addEventListener('click', function() { switchMcpSource('local'); });
    if (mcpBtnCloud) mcpBtnCloud.addEventListener('click', function() { switchMcpSource('cloud'); });

    // Prompt sandbox toggle
    var sandboxToggleBtn = document.getElementById('sandboxToggleBtn');
    if (sandboxToggleBtn) sandboxToggleBtn.addEventListener('click', togglePromptSandbox);

    // RAG toggle
    var ragToggleBtn = document.getElementById('ragToggleBtn');
    if (ragToggleBtn) ragToggleBtn.addEventListener('click', toggleRag);

    // Skills toggle
    var skillsToggleBtn = document.getElementById('skillsToggleBtn');
    if (skillsToggleBtn) skillsToggleBtn.addEventListener('click', toggleSkills);
    
    // Initial button state
    updateSendButton();
});

// Auto-resize textarea
function autoResize() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
}

// Update sandbox UI from state (prompt_sandbox_enabled)
function updateSandboxUI(enabled) {
    var stateLabel = document.getElementById('sandboxStateLabel');
    var btnText = document.getElementById('sandboxToggleBtnText');
    var btn = document.getElementById('sandboxToggleBtn');
    if (stateLabel) stateLabel.textContent = enabled ? 'On' : 'Off';
    if (btnText) btnText.textContent = enabled ? 'Disable Prompt Defense' : 'Enable Prompt Defense';
    if (btn) {
        if (enabled) { btn.classList.add('btn-warning'); btn.classList.remove('btn-outline'); }
        else { btn.classList.remove('btn-warning'); btn.classList.add('btn-outline'); }
    }
}

// Fetch agent info
async function fetchAgentInfo() {
    try {
        const response = await fetch('/api/info');
        const data = await response.json();
        modelNameEl.textContent = data.model || 'Unknown';
        var mcpLabel = document.getElementById('mcpSourceLabel');
        var btnLocal = document.getElementById('mcpBtnLocal');
        var btnCloud = document.getElementById('mcpBtnCloud');
        if (data.mcp_source === 'cloud') {
            if (mcpLabel) mcpLabel.textContent = 'Cloud MCP (Bright Data)';
            if (btnLocal) { btnLocal.classList.remove('btn-primary'); btnLocal.classList.add('btn-ghost'); }
            if (btnCloud) { btnCloud.classList.remove('btn-ghost'); btnCloud.classList.add('btn-secondary'); }
        } else {
            if (mcpLabel) mcpLabel.textContent = 'Local MCP';
            if (btnLocal) { btnLocal.classList.remove('btn-ghost'); btnLocal.classList.add('btn-primary'); }
            if (btnCloud) { btnCloud.classList.remove('btn-secondary'); btnCloud.classList.add('btn-ghost'); }
        }
        updateSandboxUI(data.prompt_sandbox_enabled === true);

        // Initialize RAG toggle (default disabled if backend does not specify)
        if (Object.prototype.hasOwnProperty.call(data, 'rag_enabled_default')) {
            useRag = data.rag_enabled_default === true;
        } else {
            useRag = false;
        }
        updateRagUI(useRag);

        // Initialize Skills toggle from backend
        if (Object.prototype.hasOwnProperty.call(data, 'skills_enabled')) {
            skillsEnabled = data.skills_enabled === true;
        } else {
            skillsEnabled = false;
        }
        updateSkillsUI(skillsEnabled);
    } catch (error) {
        console.error('Failed to fetch agent info:', error);
        modelNameEl.textContent = 'Connection failed';
    }
}

// Toggle prompt sandbox (prompt injection defense)
async function togglePromptSandbox() {
    var btn = document.getElementById('sandboxToggleBtn');
    if (!btn) return;
    btn.disabled = true;
    try {
        var res = await fetch('/api/security/prompt_sandbox/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        var data = await res.json().catch(function() { return {}; });
        if (res.ok && data.success) {
            updateSandboxUI(data.prompt_sandbox_enabled === true);
            sessionId = generateUUID();
            chatMessages.innerHTML = '';
            renderWelcome();
        } else {
            console.error('Toggle sandbox failed:', data.error);
        }
    } catch (err) {
        console.error('Toggle sandbox failed:', err);
    } finally {
        btn.disabled = false;
    }
}

// Update RAG UI
function updateRagUI(enabled) {
    var stateLabel = document.getElementById('ragStateLabel');
    var btnText = document.getElementById('ragToggleBtnText');
    var btn = document.getElementById('ragToggleBtn');
    if (stateLabel) stateLabel.textContent = enabled ? 'On' : 'Off';
    if (btnText) btnText.textContent = enabled ? 'Disable RAG Knowledge Base' : 'Enable RAG Knowledge Base';
    if (btn) {
        if (enabled) { btn.classList.add('btn-info'); btn.classList.remove('btn-outline'); }
        else { btn.classList.remove('btn-info'); btn.classList.add('btn-outline'); }
    }
}

// Update Skills UI
function updateSkillsUI(enabled) {
    var stateLabel = document.getElementById('skillsStateLabel');
    var btnText = document.getElementById('skillsToggleBtnText');
    var btn = document.getElementById('skillsToggleBtn');
    if (stateLabel) stateLabel.textContent = enabled ? 'On' : 'Off';
    if (btnText) btnText.textContent = enabled ? 'Disable Skills System' : 'Enable Skills System';
    if (btn) {
        if (enabled) { btn.classList.add('btn-accent'); btn.classList.remove('btn-outline'); }
        else { btn.classList.remove('btn-accent'); btn.classList.add('btn-outline'); }
    }
}

// Toggle RAG locally; no separate backend API needed
function toggleRag() {
    useRag = !useRag;
    updateRagUI(useRag);
}

// Toggle Skills System (backend API; will recreate Agent with/without Skills System)
async function toggleSkills() {
    var btn = document.getElementById('skillsToggleBtn');
    if (!btn) return;
    btn.disabled = true;
    try {
        var res = await fetch('/api/skills/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        var data = await res.json().catch(function() { return {}; });
        if (res.ok && data.success) {
            skillsEnabled = data.skills_enabled === true;
            updateSkillsUI(skillsEnabled);
            // Skills System 变化会影响 system prompt；清空当前会话更安全
            sessionId = generateUUID();
            chatMessages.innerHTML = '';
            renderWelcome();
        } else {
            console.error('Toggle skills failed:', data.error);
        }
    } catch (err) {
        console.error('Toggle skills failed:', err);
    } finally {
        btn.disabled = false;
    }
}

// Switch MCP source (local / cloud)
async function switchMcpSource(source) {
    var mcpLabel = document.getElementById('mcpSourceLabel');
    var btnLocal = document.getElementById('mcpBtnLocal');
    var btnCloud = document.getElementById('mcpBtnCloud');
    var hint = document.getElementById('mcpSwitchHint');
    if (!mcpLabel || !btnLocal || !btnCloud) return;
    var current = (mcpLabel.textContent || '').indexOf('Cloud') >= 0 ? 'cloud' : 'local';
    if (current === source) return;
    btnLocal.disabled = true;
    btnCloud.disabled = true;
    if (hint) hint.textContent = 'Switching...';
    try {
        var res = await fetch('/api/mcp/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: source })
        });
        var data = await res.json().catch(function() { return {}; });
        if (!res.ok || !data.success) {
            if (hint) hint.textContent = data.error || 'Switch failed';
            return;
        }
        sessionId = generateUUID();
        chatMessages.innerHTML = '';
        renderWelcome();
        await fetchAgentInfo();
        if (hint) hint.textContent = 'Switching will clear the current conversation.';
    } catch (err) {
        console.error('MCP switch failed:', err);
        if (hint) hint.textContent = 'Switch failed, please try again.';
    } finally {
        btnLocal.disabled = false;
        btnCloud.disabled = false;
    }
}

// Set input content (for tip clicks)
function setInput(text) {
    messageInput.value = text;
    messageInput.focus();
    autoResize();
    updateSendButton();
}

// Send message
async function sendMessage() {
    const message = messageInput.value.trim();
    
    if (!message || isGenerating) return;
    
    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';
    updateSendButton();
    
    // Remove welcome message
    const welcomeMsg = chatMessages.querySelector('.welcome-message');
    if (welcomeMsg) {
        welcomeMsg.remove();
    }
    
    // Add user message (no avatar)
    addUserMessage(message);
    
    // Set generating state
    setGenerating(true);
    
    // Add assistant message with thinking panel
    const assistantMsgEl = addAssistantMessage('', true);
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: message,
                session_id: sessionId,
                stream: true,
                use_rag: useRag
            })
        });
        
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            updateAssistantMessage(assistantMsgEl, '❌ ' + (err.error || response.statusText));
            setGenerating(false);
            return;
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalResponse = '';
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);
                    if (data.status === 'done') {
                        finalResponse = data.response || '';
                        break;
                    }
                    if (data.status === 'error') {
                        finalResponse = '❌ ' + (data.error || 'Unknown error');
                        break;
                    }
                    if (data.status === 'timeout') {
                        finalResponse = '❌ Request timeout.';
                        break;
                    }
                    // Push thinking step and render panel
                    const steps = pushThinkingStep(assistantMsgEl, data);
                    renderThinkingPanel(assistantMsgEl, steps, false);
                    updateAgentStatusBar(data.status);
                } catch (e) {
                    console.warn('Parse stream line:', e);
                }
            }
            if (finalResponse) break;
        }
        
        if (buffer.trim()) {
            try {
                const data = JSON.parse(buffer);
                if (data.status === 'done') finalResponse = data.response || '';
                else if (data.status === 'error') finalResponse = '❌ ' + (data.error || '');
            } catch (_) {}
        }
        
        // Mark thinking done (collapse) and show final reply
        updateAgentStatusBar('done');
        const steps = assistantMsgEl._thinkingSteps || [];
        renderThinkingPanel(assistantMsgEl, steps, true);
        const replyBlock = assistantMsgEl.querySelector('.assistant-reply-block');
        if (replyBlock) {
            replyBlock.style.display = '';
            replyBlock.innerHTML = formatMessage(finalResponse || 'No valid response received.', false);
        } else {
            updateAssistantMessage(assistantMsgEl, finalResponse || 'No valid response received.');
        }
    } catch (error) {
        console.error('Failed to send message:', error);
        updateAssistantMessage(assistantMsgEl, '❌ Network error. Please check server connection.');
    } finally {
        setGenerating(false);
    }
}

// Agent step labels (aligned with backend: planning, decision, execute, memory, reflection)
const STATUS_LABELS = {
    planning: 'Planning Agent',
    decision: 'Decision Agent',
    execute: 'Tool Execution',
    memory: 'Memory Agent',
    reflection: 'Reflection Agent'
};

function getStatusLabel(status) {
    return STATUS_LABELS[status] || status;
}

// Update top status bar: show current step while streaming, "Ready" when done
function updateAgentStatusBar(currentStatus) {
    if (!agentStatusEl) return;
    if (!currentStatus || currentStatus === 'done' || currentStatus === 'error' || currentStatus === 'timeout') {
        agentStatusEl.innerHTML = `
            <span class="w-2 h-2 rounded-full bg-success"></span>
            <span class="text-base-content">Ready</span>
        `;
        return;
    }
    const label = getStatusLabel(currentStatus);
    agentStatusEl.innerHTML = `
        <span class="loading loading-spinner loading-xs"></span>
        <span class="text-base-content">${escapeHtml(label)}</span>
    `;
}

// Push or update one thinking step; returns the steps array for the message
function pushThinkingStep(assistantMsgEl, data) {
    let steps = assistantMsgEl._thinkingSteps;
    if (!steps) steps = assistantMsgEl._thinkingSteps = [];
    const hasDuration = data.duration_sec != null;
    const last = steps[steps.length - 1];
    if (hasDuration && last && last.status === data.status && last.duration_sec == null) {
        last.content = data.content || '';
        last.duration_sec = data.duration_sec;
    } else {
        steps.push({
            status: data.status,
            detail: data.detail || '',
            content: data.content || '',
            duration_sec: data.duration_sec
        });
    }
    return steps;
}

// Set thinking panel expanded/collapsed state (CSS max-height drives visibility; we only toggle class and arrow)
function setThinkingExpanded(panel, expanded) {
    if (!panel) return;
    panel.classList.toggle('thinking-expanded', expanded);
    const arrow = panel.querySelector('.thinking-summary-arrow');
    if (arrow) arrow.classList.toggle('thinking-arrow-expanded', expanded);
}

// Render thinking panel (single box, continuous content; streaming: expanded; done: collapsed by default)
function renderThinkingPanel(container, steps, isDone) {
    const panel = container.querySelector('.thinking-panel');
    if (!panel) return;
    const summaryCollapsed = panel.querySelector('.thinking-summary-collapsed');
    const summaryExpanded = panel.querySelector('.thinking-summary-expanded');
    const stepsContainer = panel.querySelector('.thinking-content');
    if (!stepsContainer) return;

    const totalSec = steps.reduce((s, t) => s + (t.duration_sec || 0), 0);
    const totalStr = totalSec > 0 ? totalSec.toFixed(1) + 's' : '';

    if (isDone) {
        panel.classList.add('thinking-done');
        panel.classList.remove('thinking-streaming');
        summaryCollapsed.querySelector('.thinking-summary-text').textContent =
            steps.length ? `Thinking (${steps.length} steps)` : 'Thinking';
        const totalEl = summaryCollapsed.querySelector('.thinking-summary-total');
        if (totalEl) totalEl.textContent = totalStr ? ` · ${totalStr}` : '';
        summaryCollapsed.style.display = '';
        setThinkingExpanded(panel, false);
    } else {
        panel.classList.remove('thinking-done');
        panel.classList.add('thinking-streaming');
        summaryCollapsed.style.display = 'none';
    }

    // Before re-rendering while streaming: remember which steps are expanded and restore them after redraw
    const expandedIndices = new Set();
    stepsContainer.querySelectorAll('.thinking-step-wrap.step-expanded').forEach(wrap => {
        const head = wrap.querySelector('.thinking-step-head[data-step-idx]');
        if (head) {
            const idx = parseInt(head.getAttribute('data-step-idx'), 10);
            if (!isNaN(idx)) expandedIndices.add(idx);
        }
    });

    stepsContainer.innerHTML = '';
    steps.forEach((step, i) => {
        const label = getStatusLabel(step.status);
        const isCurrent = !isDone && i === steps.length - 1 && step.duration_sec == null;
        const timeStr = step.duration_sec != null ? ` — ${step.duration_sec}s` : '';
        const stepWrap = document.createElement('div');
        stepWrap.className = 'thinking-step-wrap' + (isCurrent ? ' thinking-step-current' : '');
        stepWrap.innerHTML = `
            <div class="thinking-step-head" data-step-idx="${i}">
                <span class="thinking-step-name">${escapeHtml(label)}</span>
                <span class="thinking-step-time">${escapeHtml(timeStr)}</span>
                ${isCurrent ? '<span class="thinking-step-spinner"></span>' : ''}
                ${step.content && !isCurrent ? '<span class="thinking-step-toggle" aria-hidden="true"></span>' : ''}
            </div>
            ${step.content ? `<div class="thinking-step-body">${escapeHtml(truncateContent(step.content, 500))}</div>` : ''}
        `;
        stepsContainer.appendChild(stepWrap);
    });

    // Toggle step body visibility on head click; use CSS classes to rotate the caret icon
    stepsContainer.querySelectorAll('.thinking-step-head').forEach(h => {
        const stepIdx = parseInt(h.getAttribute('data-step-idx'), 10);
        const step = steps[stepIdx];
        if (!step || !step.content) return;
        const stepWrap = h.closest('.thinking-step-wrap');
        const bodyEl = stepWrap.querySelector('.thinking-step-body');
        const toggle = stepWrap.querySelector('.thinking-step-toggle');
        if (!bodyEl) return;
        const wasExpanded = expandedIndices.has(stepIdx);
        if (wasExpanded) {
            stepWrap.classList.add('step-expanded');
            bodyEl.style.display = '';
            if (toggle) toggle.classList.add('thinking-step-toggle-expanded');
        } else {
            bodyEl.style.display = 'none';
        }
        h.addEventListener('click', () => {
            stepWrap.classList.toggle('step-expanded');
            bodyEl.style.display = bodyEl.style.display === 'none' ? '' : 'none';
            if (toggle) toggle.classList.toggle('thinking-step-toggle-expanded', stepWrap.classList.contains('step-expanded'));
        });
    });
}

function escapeHtml(s) {
    if (!s) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function truncateContent(s, maxLen) {
    if (!s || s.length <= maxLen) return s || '';
    return s.slice(0, maxLen) + '…';
}

// Add user message (no avatar, right-aligned)
function addUserMessage(content) {
    const container = document.createElement('div');
    container.className = 'message-container user animate-slide-up';
    
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble-user';
    bubble.innerHTML = formatMessage(content, true);
    
    container.appendChild(bubble);
    chatMessages.appendChild(container);
    
    scrollToBottom();
}

// Add assistant message (with gradient avatar, no bubble)
function addAssistantMessage(content, isLoading = false) {
    const container = document.createElement('div');
    container.className = 'message-container assistant animate-slide-up';
    
    // Avatar - gradient style like logo
    const avatar = document.createElement('div');
    avatar.className = 'agent-avatar';
    avatar.innerHTML = '<span class="iconify" data-icon="mdi:robot-happy"></span>';
    
    // Content wrapper - thinking panel above, reply below
    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'assistant-content markdown-content';
    
    if (isLoading) {
        // Thinking panel first (above reply); when done, show collapsed summary (click to expand)
        const thinking = document.createElement('div');
        thinking.className = 'thinking-panel';
        thinking.innerHTML = `
            <div class="thinking-summary-collapsed" style="display:none;">
                <span class="thinking-summary-text">Thinking</span>
                <span class="thinking-summary-total"></span>
                <span class="thinking-summary-arrow" aria-hidden="true"></span>
            </div>
            <div class="thinking-summary-expanded">
                <div class="thinking-content"></div>
            </div>
        `;
        contentWrapper.appendChild(thinking);
        // Reply area below thinking (empty until done)
        const replyBlock = document.createElement('div');
        replyBlock.className = 'assistant-reply-block';
        replyBlock.style.display = 'none';
        contentWrapper.appendChild(replyBlock);
        thinking.querySelector('.thinking-summary-collapsed').addEventListener('click', () => {
            if (!thinking.classList.contains('thinking-done')) return;
            setThinkingExpanded(thinking, !thinking.classList.contains('thinking-expanded'));
        });
    } else {
        contentWrapper.innerHTML = formatMessage(content, false);
    }
    
    container.appendChild(avatar);
    container.appendChild(contentWrapper);
    chatMessages.appendChild(container);
    
    scrollToBottom();
    
    return container;
}

// Update assistant message (replaces status indicator with final content)
function updateAssistantMessage(container, content) {
    const contentWrapper = container.querySelector('.assistant-content');
    if (!contentWrapper) return;
    contentWrapper.innerHTML = formatMessage(content, false);
    scrollToBottom();
}

// Format message (with Markdown rendering)
function formatMessage(content, isUser = false) {
    if (!content) return '';
    
    // User messages: simple processing, no Markdown
    if (isUser) {
        return content
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');
    }
    
    // Assistant messages: render Markdown
    try {
        let html = marked.parse(content);
        
        // Add target="_blank" for external links
        html = html.replace(
            /<a href="(https?:\/\/[^"]+)"/g,
            '<a href="$1" target="_blank" rel="noopener"'
        );
        
        return html;
    } catch (e) {
        console.error('Markdown rendering failed:', e);
        return content
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');
    }
}

// Scroll to bottom - ensure it scrolls after content is rendered
function scrollToBottom() {
    // Use multiple frames to ensure DOM is fully updated
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    });
}

// Set generating state (shows "Processing" at start; current step is set by updateAgentStatusBar during stream)
function setGenerating(generating) {
    isGenerating = generating;
    updateSendButton();
    
    if (generating) {
        agentStatusEl.innerHTML = `
            <span class="loading loading-spinner loading-xs"></span>
            <span class="text-base-content">Processing</span>
        `;
    } else {
        updateAgentStatusBar('done');
    }
}

function renderWelcome() {
    const tpl = document.getElementById('welcomeTemplate');
    if (!tpl || !chatMessages) return;
    chatMessages.appendChild(tpl.content.cloneNode(true));
    if (typeof Iconify !== 'undefined') Iconify.scan(chatMessages);
}

// Clear chat
async function clearChat() {
    if (!confirm('Are you sure you want to clear the chat history?')) return;
    try {
        await fetch('/api/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId })
        });
        sessionId = generateUUID();
        chatMessages.innerHTML = '';
        renderWelcome();
    } catch (error) {
        console.error('Failed to clear chat:', error);
        alert('Failed to clear chat. Please try again.');
    }
}
