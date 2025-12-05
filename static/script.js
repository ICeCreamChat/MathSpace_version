import * as THREE from 'three';

const API_URL = '/api/chat'; 
let isRecording = false;
let recognition = null;
let voiceTimeout = null; // 🎤 用来给语音倒计时的闹钟

// 记忆系统
let chatSessions = JSON.parse(localStorage.getItem('chatSessions')) || [];
let currentSessionId = localStorage.getItem('currentSessionId') || null;

// 主题状态管理
let isManualTheme = false; 

// Three.js 变量
let scene, camera, renderer, particles;
let clock = new THREE.Clock();

// WebSocket 连接变量
let ws = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log("🚀 MathSpace 视觉引擎增强版启动!");
    
    // 时间与主题检查
    checkTimeTheme();
    setInterval(checkTimeTheme, 60000);

    bindEvents();
    initVoiceFeature();
    initChatSystem(); 
    initCustomCursor(); 
    initMathParticleScene(); // 启动增强版背景
    
    if(window.marked) window.marked.setOptions({ breaks: true, gfm: true });
});

// === 1. WebSocket 发送消息逻辑 (带动画优化) ===
function sendMessage() {
    console.log("📨 准备发送消息...");
    
    // 如果正在录音，先停止
    if (isRecording) stopVoice();
    
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;
    
    // 显示用户消息
    displayMessage('user', message, true);
    input.value = '';
    
    // 显示 Loading 状态
    const loading = document.getElementById('loading');
    const loadingText = loading.querySelector('span'); 
    loading.style.display = 'block';
    
    // ✨【视觉优化】加上呼吸灯和动态省略号的 class
    loadingText.className = 'breathing-text animated-dots'; 
    loadingText.innerText = "正在连接大脑"; // 省略号交给 CSS 动画处理
    
    scrollToBottom();

    // 建立 WebSocket 连接
    // 自动判断是 ws 还是 wss (安全连接)
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;
    
    // 如果已有连接，先断开
    if (ws) ws.close();
    
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log("🔌 已连接到神经网络");
        // 连接建立后，立即发送指令
        ws.send(JSON.stringify({ prompt: message }));
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'progress') {
            // ✨ 实时更新进度条文字
            // data.step 是步骤名，data.message 是中文描述
            // 去掉后端可能自带的省略号，保证样式统一
            const cleanMessage = data.message.replace(/\.\.\.$/, '');
            loadingText.innerText = `[${data.step}] ${cleanMessage}`;
        } 
        else if (data.type === 'result') {
            // 🎉 成功收到结果
            loading.style.display = 'none';
            if (data.status === 'success') {
                const cacheTag = data.cached ? '<span style="color:#f59e0b;font-size:10px;margin-left:5px;">⚡ 秒速缓存</span>' : '';
                const videoHTML = `
                    <div class="video-container">
                        <video controls autoplay loop playsinline>
                            <source src="${data.video}" type="video/mp4">
                        </video>
                        <div class="video-info">
                            <span>DeepSeek V3 ${cacheTag}</span>
                            <span>ManimGL</span>
                        </div>
                    </div>`;
                displayMessage('bot', videoHTML, true);
            }
            ws.close(); // 任务完成，挂断电话
        } 
        else if (data.type === 'error') {
            // ❌ 报错
            loading.style.display = 'none';
            displayMessage('bot', `⚠️ 错误: ${data.message}\n详情: ${data.details || ''}`, false);
            ws.close();
        }
    };

    ws.onerror = (error) => {
        console.error("WS Error:", error);
        loading.style.display = 'none';
        displayMessage('bot', `网络连接断开，请重试`, false);
    };
    
    ws.onclose = () => {
        console.log("🔌 连接已关闭");
    };
}

// === 2. 语音输入逻辑 (智能自动发送版) ===
function initVoiceFeature() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SR) { 
        const micBtn = document.getElementById('mic-btn');
        if(micBtn) micBtn.style.display='none'; 
        return; 
    }
    
    recognition = new SR(); 
    recognition.lang = 'zh-CN';
    recognition.continuous = true;      // 允许连续说话
    recognition.interimResults = true;  // ✨【关键】允许实时显示（像打字机一样）

    recognition.onstart = () => {
        isRecording = true; 
        document.getElementById('mic-btn').classList.add('recording');
        document.getElementById('chat-input').placeholder = "同学请讲，ICe在听...";
    };

    recognition.onend = () => {
        isRecording = false; 
        document.getElementById('mic-btn').classList.remove('recording');
        document.getElementById('chat-input').placeholder = "探索数学未知之地...";
    };

    recognition.onresult = (e) => {
        // 获取当前听到的所有内容
        const transcript = Array.from(e.results)
            .map(result => result[0].transcript)
            .join('');
            
        const inputField = document.getElementById('chat-input');
        inputField.value = transcript;

        // ✨【核心逻辑】防抖动自动发送
        // 每次说话，都把之前的闹钟关了，重新定一个 1.5 秒的闹钟
        if (voiceTimeout) clearTimeout(voiceTimeout);

        voiceTimeout = setTimeout(() => {
            // 如果 1.5 秒内没再说话，且内容不为空，就自动发送
            if (transcript.trim().length > 0) {
                console.log("🎤 检测到语音停顿，自动发送...");
                stopVoice(); // 停止录音
                sendMessage(); // 发送！
            }
        }, 1500); // 1.5秒 = 1500毫秒
    };
}

function stopVoice() { 
    if(recognition) recognition.stop(); 
    if (voiceTimeout) clearTimeout(voiceTimeout); // 停止时也要清除闹钟，防止重复发
}

// === 3. 主题切换逻辑 ===
function checkTimeTheme() {
    if (isManualTheme) return;
    const hour = new Date().getHours();
    // 06:00 - 19:00 为亮色模式
    if (hour >= 6 && hour < 19) {
        if (!document.body.classList.contains('light-mode')) document.body.classList.add('light-mode');
    } else {
        if (document.body.classList.contains('light-mode')) document.body.classList.remove('light-mode');
    }
}

// === 4. 核心：增强版数学粒子引擎 ===
function initMathParticleScene() {
    const container = document.getElementById('math-canvas-container');
    if (!container) return;

    const width = window.innerWidth;
    const height = window.innerHeight;

    scene = new THREE.Scene();
    // 稍微调整雾效，适应高密度粒子
    scene.fog = new THREE.FogExp2(0x050b14, 0.002);

    camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
    camera.position.z = 50;

    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(renderer.domElement);

    // 扩充符号库
    const symbols = ['∑', '∫', 'π', 'e', '0', '1', 'sin', 'cos', '∞', '√', 'tan', 'log'];
    const materials = [];
    
    symbols.forEach(sym => {
        const canvas = document.createElement('canvas');
        canvas.width = 128; canvas.height = 128;
        const ctx = canvas.getContext('2d');
        ctx.font = 'bold 60px "JetBrains Mono", monospace';
        ctx.fillStyle = 'white';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(sym, 64, 64);
        const tex = new THREE.CanvasTexture(canvas);
        materials.push(new THREE.SpriteMaterial({ 
            map: tex, transparent: true, opacity: 0.5, color: 0xffffff 
        }));
    });

    particles = new THREE.Group();
    // 还原高密度：3000个粒子
    const particleCount = 3000; 

    for (let i = 0; i < particleCount; i++) {
        const mat = materials[Math.floor(Math.random() * materials.length)].clone();
        const sprite = new THREE.Sprite(mat);
        
        sprite.position.x = (Math.random() - 0.5) * 400;
        sprite.position.y = (Math.random() - 0.5) * 300;
        sprite.position.z = (Math.random() - 0.5) * 200;
        
        const scale = 0.5 + Math.random() * 2.0;
        sprite.scale.set(scale, scale, 1);
        
        // 赋予粒子不同的运动类型
        sprite.userData = {
            speed: 0.05 + Math.random() * 0.1,
            type: Math.floor(Math.random() * 3), // 0, 1, 2 三种运动模式
            offset: Math.random() * 100,
            amp: 0.5 + Math.random() * 2
        };
        
        sprite.material.opacity = 0.1 + Math.random() * 0.4;
        particles.add(sprite);
    }
    scene.add(particles);

    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    animate();
}

function animate() {
    requestAnimationFrame(animate);
    const time = clock.getElapsedTime();

    particles.children.forEach(sprite => {
        const d = sprite.userData;
        
        // 垂直下落
        sprite.position.y -= d.speed;
        
        // 复杂的水平波动逻辑
        if (d.type === 0) {
            sprite.position.x += Math.sin(time * 0.5 + d.offset) * 0.02 * d.amp;
        } else if (d.type === 1) {
            sprite.position.x += Math.cos(time * 0.4 + d.offset) * 0.02 * d.amp;
        } else {
            sprite.position.x += Math.sin(time * 0.3) * 0.01 + Math.cos(time * 0.6) * 0.01;
        }

        sprite.material.rotation += 0.005;

        // 循环重置
        if (sprite.position.y < -150) {
            sprite.position.y = 150;
            sprite.position.x = (Math.random() - 0.5) * 400;
        }
        
        // 颜色自适应主题
        const isLight = document.body.classList.contains('light-mode');
        const targetColor = isLight ? new THREE.Color(0x64748b) : new THREE.Color(0xccf0ff);
        sprite.material.color.lerp(targetColor, 0.1);
        sprite.material.opacity = isLight ? 0.2 : 0.3;
    });

    renderer.render(scene, camera);
}

// === 5. 点击爆破特效 ===
function initCustomCursor() {
    document.addEventListener('mousedown', (e) => {
        createExplosion(e.clientX, e.clientY);
    });
}

function createExplosion(x, y) {
    // 扩充后的爆破符号库
    const symbols = ['∑', '∫', 'π', '∞', '√', '≈', '≠', '±', '∂', '∇', 'x', 'y'];
    const particleCount = 12; 
    
    // 动态获取当前文字颜色作为粒子颜色
    const themeColor = getComputedStyle(document.body).getPropertyValue('--text-primary').trim() || '#00f0ff';

    for (let i = 0; i < particleCount; i++) {
        const el = document.createElement('div');
        el.classList.add('math-particle-dom');
        el.textContent = symbols[Math.floor(Math.random() * symbols.length)];
        el.style.color = themeColor;
        document.body.appendChild(el);

        el.style.left = `${x}px`;
        el.style.top = `${y}px`;

        const angle = Math.random() * Math.PI * 2;
        const velocity = 60 + Math.random() * 60;
        const tx = Math.cos(angle) * velocity + 'px';
        const ty = Math.sin(angle) * velocity + 'px';
        const rot = (Math.random() - 0.5) * 360 + 'deg';

        el.style.setProperty('--tx', tx);
        el.style.setProperty('--ty', ty);
        el.style.setProperty('--rot', rot);

        setTimeout(() => el.remove(), 1000);
    }
}

// === 6. 通用辅助函数 ===
function displayMessage(role, content, shouldSave = false) {
    if (shouldSave) saveMessageToCurrentSession(role, content);
    const container = document.getElementById('messages');
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    
    const avatar = document.createElement('img');
    avatar.src = role === 'user' ? '/static/user-avatar.jpg' : '/static/bot-avatar.jpg';
    avatar.onerror = function() { this.src = 'https://via.placeholder.com/40'; };
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    if (role === 'bot' && content.trim().startsWith('<div')) {
        contentDiv.innerHTML = content;
    } else {
        contentDiv.innerHTML = window.marked ? window.marked.parse(content) : content;
        if (window.renderMathInElement) {
            requestAnimationFrame(() => window.renderMathInElement(contentDiv, {
                delimiters: [{left: '$$', right: '$$', display: true}, {left: '$', right: '$', display: false}],
                throwOnError: false
            }));
        }
    }
    
    msgDiv.appendChild(avatar); 
    msgDiv.appendChild(contentDiv); 
    container.appendChild(msgDiv); 
    scrollToBottom();
}

function scrollToBottom() {
    const container = document.getElementById('messages');
    requestAnimationFrame(() => container.scrollTop = container.scrollHeight);
}

function initChatSystem() {
    if (!currentSessionId || !chatSessions.find(s=>s.id===currentSessionId)) startNewChat();
    else loadSession(currentSessionId);
}
function startNewChat() {
    currentSessionId = Date.now().toString();
    chatSessions.unshift({ id: currentSessionId, title: "新突触 "+new Date().toLocaleTimeString(), messages: [{ role: 'bot', text: "数学宇宙已连接，请下达指令。" }] });
    saveData(); renderHistoryList(); loadSession(currentSessionId);
}
function loadSession(id) {
    currentSessionId = id; localStorage.setItem('currentSessionId', id);
    const s = chatSessions.find(x=>x.id===id);
    document.getElementById('messages').innerHTML = '';
    if(s) s.messages.forEach(m=>displayMessage(m.role, m.content||m.text, false));
    renderHistoryList();
}
function saveMessageToCurrentSession(role, content) {
    const s = chatSessions.find(x=>x.id===currentSessionId);
    if(s) { s.messages.push({role, content}); saveData(); }
}
function renderHistoryList() {
    const list = document.getElementById('history-list'); list.innerHTML = '';
    chatSessions.forEach(s => {
        const div = document.createElement('div');
        div.className = `history-item ${s.id===currentSessionId?'active':''}`;
        div.textContent = s.title;
        div.onclick = () => loadSession(s.id);
        
        // 删除按钮
        const delBtn = document.createElement('span');
        delBtn.textContent = '×';
        delBtn.className = 'delete-chat';
        delBtn.style.float = 'right';
        delBtn.onclick = (e) => {
            e.stopPropagation();
            if(confirm('删除此突触?')) {
                chatSessions = chatSessions.filter(x=>x.id!==s.id);
                saveData();
                if(chatSessions.length === 0) startNewChat();
                else if(currentSessionId === s.id) loadSession(chatSessions[0].id);
                else renderHistoryList();
            }
        };
        div.appendChild(delBtn);
        list.appendChild(div);
    });
}
function saveData() { localStorage.setItem('chatSessions', JSON.stringify(chatSessions)); }

// === 7. 事件绑定 ===
function bindEvents() {
    const sendBtn = document.getElementById('send-btn');
    if(sendBtn) sendBtn.addEventListener('click', sendMessage);

    // 麦克风点击事件：点击切换录音/停止
    document.getElementById('mic-btn').addEventListener('click', ()=>{
        if (isRecording) {
            stopVoice();
        } else {
            if (recognition) recognition.start();
            else initVoiceFeature(); // 防止初始化失败的情况
        }
    });

    document.getElementById('new-chat-btn').addEventListener('click', startNewChat);
    document.getElementById('chat-input').addEventListener('keypress', (e)=>{if(e.key==='Enter') sendMessage()});
    
    const moreBtn = document.getElementById('more-btn');
    const menu = document.getElementById('dropdownMenu');
    if(moreBtn) moreBtn.addEventListener('click', (e)=>{ e.stopPropagation(); menu.classList.toggle('show'); });
    window.addEventListener('click', ()=>{ if(menu) menu.classList.remove('show'); });
    
    document.getElementById('btn-theme').addEventListener('click', ()=>{ 
        isManualTheme = true;
        document.body.classList.toggle('light-mode'); 
    });
    
    // 升级后的彻底清除逻辑 (核按钮)
    document.getElementById('btn-clear').addEventListener('click', async () => { 
        if(confirm('警告：此操作将永久删除所有历史记录和生成的视频文件，且不可恢复。\n\n确定要彻底断开突触吗？')) { 
            try {
                // 1. 先呼叫后台进行“大扫除”
                await fetch('/api/reset', { method: 'POST' });
                
                // 2. 后台扫干净了，前台再清空记忆
                chatSessions = []; 
                localStorage.removeItem('chatSessions');
                localStorage.removeItem('currentSessionId');
                
                // 3. 重新开始
                startNewChat(); 
                alert('神经突触已彻底断开');
            } catch (e) {
                alert('清除失败，请检查后台连接');
            }
        } 
    });
}