import * as THREE from 'three';

const API_URL = '/api/chat'; 
let isRecording = false;
let recognition = null;

// 记忆系统
let chatSessions = JSON.parse(localStorage.getItem('chatSessions')) || [];
let currentSessionId = localStorage.getItem('currentSessionId') || null;

// 主题状态管理
let isManualTheme = false; 

// Three.js 变量
let scene, camera, renderer, particles;
let clock = new THREE.Clock();

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

// === 1. 主题自动切换逻辑 ===
function checkTimeTheme() {
    if (isManualTheme) return;
    const hour = new Date().getHours();
    // 06:00 - 19:00 为亮色
    if (hour >= 6 && hour < 19) {
        if (!document.body.classList.contains('light-mode')) document.body.classList.add('light-mode');
    } else {
        if (document.body.classList.contains('light-mode')) document.body.classList.remove('light-mode');
    }
}

// === 2. 核心：增强版数学粒子引擎 (还原 3000 粒子) ===
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
        // 亮色模式用深灰蓝，暗色模式用浅蓝白
        const targetColor = isLight ? new THREE.Color(0x64748b) : new THREE.Color(0xccf0ff);
        sprite.material.color.lerp(targetColor, 0.1);
        sprite.material.opacity = isLight ? 0.2 : 0.3;
    });

    renderer.render(scene, camera);
}

// === 3. 点击爆破特效 (同步更新符号库) ===
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

// === 4. 发送消息 (保留后端视频生成能力) ===
function sendMessage() {
    console.log("📨 准备发送消息...");
    if (isRecording) stopVoice();
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;
    
    displayMessage('user', message, true);
    input.value = '';
    
    const loading = document.getElementById('loading');
    loading.style.display = 'block';
    scrollToBottom();

    // 关键：保持与 main.py 的连接，而不是直接调用 DeepSeek
    fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: message })
    })
    .then(res => res.json())
    .then(data => {
        loading.style.display = 'none';
        if (data.error) {
            displayMessage('bot', `⚠️ 错误: ${data.error}`, false);
        } else {
            const videoHTML = `
                <div class="video-container">
                    <video controls autoplay loop playsinline>
                        <source src="${data.video}" type="video/mp4">
                    </video>
                    <div class="video-info"><span>DeepSeek V3</span><span>ManimGL</span></div>
                </div>`;
            displayMessage('bot', videoHTML, true);
        }
    })
    .catch(err => {
        loading.style.display = 'none';
        displayMessage('bot', `网络错误: ${err.message}`, false);
    });
}

// === 5. 通用辅助函数 ===
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
    chatSessions.unshift({ id: currentSessionId, title: "新场景 "+new Date().toLocaleTimeString(), messages: [{ role: 'bot', text: "数学宇宙已连接" }] });
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
        list.appendChild(div);
    });
}
function saveData() { localStorage.setItem('chatSessions', JSON.stringify(chatSessions)); }

function initVoiceFeature() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SR) { document.getElementById('mic-btn').style.display='none'; return; }
    recognition = new SR(); recognition.lang='zh-CN';
    recognition.onstart=()=>{isRecording=true; document.getElementById('mic-btn').classList.add('recording');};
    recognition.onend=()=>{isRecording=false; document.getElementById('mic-btn').classList.remove('recording');};
    recognition.onresult=(e)=>{document.getElementById('chat-input').value = e.results[0][0].transcript;};
}
function stopVoice() { if(recognition) recognition.stop(); }

function bindEvents() {
    const sendBtn = document.getElementById('send-btn');
    if(sendBtn) sendBtn.addEventListener('click', sendMessage);

    document.getElementById('mic-btn').addEventListener('click', ()=>{isRecording?recognition.stop():recognition.start()});
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
    
    document.getElementById('btn-clear').addEventListener('click', ()=>{ if(confirm('清空历史?')) { chatSessions=[]; startNewChat(); } });
}