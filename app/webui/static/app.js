// 全局变量
let sessionId = generateUUID();
let currentImagePath = null;
let isGenerating = false;

// DOM 元素
const imageInput = document.getElementById('imageInput');
const uploadArea = document.getElementById('uploadArea');
const uploadPlaceholder = document.getElementById('uploadPlaceholder');
const uploadedImage = document.getElementById('uploadedImage');
const resultImage = document.getElementById('resultImage');
const resultArea = document.getElementById('resultArea');
const chatbot = document.getElementById('chatbot');
const taskInput = document.getElementById('taskInput');
const submitBtn = document.getElementById('submitBtn');
const clearBtn = document.getElementById('clearBtn');
const stopBtn = document.getElementById('stopBtn');

// 生成 UUID
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// 图片上传相关
uploadArea.addEventListener('click', () => imageInput.click());

uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) {
        uploadImage(file);
    }
});

imageInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        uploadImage(file);
    }
});

async function uploadImage(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentImagePath = data.path;
            const imageUrl = `/uploads/${data.filename}`;
            console.log('Image uploaded:', imageUrl);
            
            uploadedImage.onload = function() {
                console.log('Image loaded successfully');
                uploadedImage.style.display = 'block';
                uploadPlaceholder.style.display = 'none';
                uploadArea.classList.add('has-image');
            };
            
            uploadedImage.onerror = function() {
                console.error('Failed to load image:', imageUrl);
                alert('Image loading failed, please retry');
            };
            
            uploadedImage.src = imageUrl;
        } else {
            alert('Upload failed: ' + data.error);
        }
    } catch (error) {
        console.error('Upload error:', error);
        alert('Upload failed, please retry');
    }
}

// 提交任务 - 自动执行工作流（与原client.py一致）
submitBtn.addEventListener('click', async () => {
    const task = taskInput.value.trim();
    
    if (!task) {
        alert('Please enter your task description');
        return;
    }
    
    // 清空输入框
    taskInput.value = '';
    
    // 添加用户消息
    addMessage('user', task);
    
    // 添加等待消息
    const botMessageId = addMessage('bot', 'Please wait for CogAgent\'s operation...');
    
    // 禁用按钮
    setGenerating(true);
    
    try {
        const response = await fetch('/workflow', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId,
                task: task
            })
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        // 清除等待消息
        clearMessage(botMessageId);
        
        while (true) {
            const { done, value } = await reader.read();
            
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleStreamEvent(data);
                    } catch (e) {
                        console.error('Parse error:', e);
                    }
                }
            }
        }
    } catch (error) {
        console.error('Execution error:', error);
        addMessage('error', 'Execution error: ' + error.message);
    } finally {
        setGenerating(false);
    }
});

// 处理流式事件
function handleStreamEvent(data) {
    switch (data.type) {
        case 'round':
            addMessage('round', `Round ${data.round}`);
            break;
            
        case 'response':
            addMessage('bot', data.content);
            break;
            
        case 'image':
            console.log('Result image path:', data.path);
            resultImage.onload = function() {
                console.log('Result image loaded successfully');
                resultImage.style.display = 'block';
                resultArea.querySelector('.result-placeholder').style.display = 'none';
                resultArea.classList.add('has-image');
            };
            resultImage.onerror = function() {
                console.error('Failed to load result image:', data.path);
            };
            resultImage.src = data.path;
            break;
            
        case 'done':
            setGenerating(false);
            break;
            
        case 'stopped':
            addMessage('status', 'Operation stopped');
            setGenerating(false);
            break;
            
        case 'error':
            addMessage('error', data.message);
            setGenerating(false);
            break;
            
        case 'warning_start':
            // 显示警告：CogAgent正在处理，请勿操作键盘鼠标
            console.log('CogAgent is processing. Please do not interact with the keyboard or mouse.');
            break;
            
        case 'warning_end':
            // 显示警告：CogAgent已完成
            console.log('CogAgent has finished. Please input a new task.');
            break;
    }
}

// 停止生成
stopBtn.addEventListener('click', async () => {
    try {
        await fetch('/stop', { method: 'POST' });
        setGenerating(false);
    } catch (error) {
        console.error('Stop error:', error);
    }
});

// 清空历史
clearBtn.addEventListener('click', async () => {
    try {
        await fetch('/clear', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ session_id: sessionId })
        });
        
        chatbot.innerHTML = '<div class="chat-empty">Start conversation...</div>';
        resultImage.style.display = 'none';
        resultArea.querySelector('.result-placeholder').style.display = 'block';
        resultArea.classList.remove('has-image');
        
        // 生成新的session
        sessionId = generateUUID();
    } catch (error) {
        console.error('Clear error:', error);
    }
});

// 添加消息
function addMessage(role, content) {
    // 移除空状态提示
    const emptyMsg = chatbot.querySelector('.chat-empty');
    if (emptyMsg) {
        emptyMsg.remove();
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${role}`;
    messageDiv.dataset.id = generateUUID();
    
    const label = document.createElement('div');
    label.className = 'message-label';
    
    switch (role) {
        case 'user':
            label.textContent = 'User';
            break;
        case 'bot':
            label.textContent = 'Assistant';
            break;
        case 'round':
            label.textContent = 'Round';
            messageDiv.className = 'chat-message status';
            break;
        case 'status':
            label.textContent = 'Status';
            break;
        case 'error':
            label.textContent = 'Error';
            messageDiv.className = 'chat-message error';
            break;
        default:
            label.textContent = 'System';
    }
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = content;
    
    messageDiv.appendChild(label);
    messageDiv.appendChild(contentDiv);
    chatbot.appendChild(messageDiv);
    
    // 滚动到底部
    chatbot.scrollTop = chatbot.scrollHeight;
    
    return messageDiv.dataset.id;
}

// 清除指定消息
function clearMessage(messageId) {
    const messages = chatbot.querySelectorAll('.chat-message');
    for (const msg of messages) {
        if (msg.dataset.id === messageId) {
            msg.remove();
            break;
        }
    }
}

// 追加到消息
function appendToMessage(messageId, content) {
    const messages = chatbot.querySelectorAll('.chat-message');
    for (const msg of messages) {
        if (msg.dataset.id === messageId) {
            const contentDiv = msg.querySelector('.message-content');
            contentDiv.textContent += content;
            chatbot.scrollTop = chatbot.scrollHeight;
            break;
        }
    }
}

// 设置生成状态
function setGenerating(generating) {
    isGenerating = generating;
    submitBtn.disabled = generating;
    stopBtn.disabled = !generating;
    
    if (generating) {
        submitBtn.textContent = 'Processing...';
    } else {
        submitBtn.textContent = 'Submit';
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('CogAgent Client initialized');
    stopBtn.disabled = true;
});
