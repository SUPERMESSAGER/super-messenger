#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
import secrets
import time
import re
from functools import wraps
from flask import Flask, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)

# ---------- SQLite для пользователей ----------
DB_PATH = 'alex_users.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT,
        password_hash TEXT NOT NULL,
        created_at INTEGER
    )''')
    conn.commit()
    conn.close()

init_db()

def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, password_hash FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2], 'password_hash': row[3]}
    return None

def get_user_by_id(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2]}
    return None

# ---------- Хранилище сообщений в памяти ----------
messages_store = {}

def add_message(from_id, to_id, content):
    key = tuple(sorted((from_id, to_id)))
    if key not in messages_store:
        messages_store[key] = []
    msg = {
        'from_id': from_id,
        'to_id': to_id,
        'content': content,
        'timestamp': int(time.time())
    }
    messages_store[key].append(msg)
    return msg

def get_messages_between(user1_id, user2_id):
    key = tuple(sorted((user1_id, user2_id)))
    return messages_store.get(key, [])

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        user = get_user_by_id(user_id)
        if not user:
            session.clear()
            return jsonify({'error': 'User not found'}), 403
        return f(user=user, *args, **kwargs)
    return decorated

# ---------- HTML (встроен) ----------
@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>ALEX — минимальный мессенджер</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background:#0a0a0f; color:#f0f0f5; font-family:system-ui, -apple-system, 'Segoe UI', Roboto; height:100vh; overflow:hidden; }
        .app { display:flex; flex-direction:column; height:100vh; width:100vw; }
        .header { background:#16161d; padding:12px 20px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #2a2a33; flex-shrink:0; }
        .logo { font-size:1.5rem; font-weight:700; background:linear-gradient(135deg,#5e9bff,#b77cff); -webkit-background-clip:text; background-clip:text; color:transparent; }
        .btn-icon { background:#22222c; border:none; color:#f0f0f5; padding:8px 16px; border-radius:30px; cursor:pointer; font-size:0.9rem; }
        .btn-icon:hover { background:#3a3a4a; }
        .auth-container { padding:30px 20px; max-width:400px; margin:auto; width:100%; }
        input { width:100%; padding:12px; background:#16161d; border:1px solid #2a2a33; border-radius:12px; color:#f0f0f5; margin-bottom:12px; outline:none; font-size:1rem; }
        button { background:#5e9bff; color:white; border:none; padding:12px; border-radius:30px; font-weight:600; cursor:pointer; width:100%; margin-bottom:10px; font-size:1rem; }
        button:active { transform:scale(0.97); }
        .btn-outline { background:transparent; border:1px solid #5e9bff; color:#5e9bff; }
        .main-layout { display:flex; flex:1; overflow:hidden; min-height:0; }
        .sidebar { width:280px; background:#16161d; border-right:1px solid #2a2a33; display:flex; flex-direction:column; overflow-y:auto; flex-shrink:0; }
        .chat-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
        .search-bar { padding:12px; border-bottom:1px solid #2a2a33; }
        .search-bar input { margin:0; }
        .dialog-item { padding:12px 16px; border-bottom:1px solid #2a2a33; cursor:pointer; transition:0.1s; }
        .dialog-item:hover { background:#22222c; }
        .dialog-name { font-weight:600; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:75%; padding:8px 12px; border-radius:18px; background:#22222c; align-self:flex-start; word-wrap:break-word; }
        .message.own { background:#5e9bff; align-self:flex-end; }
        .message .text { font-size:0.95rem; }
        .message .time { font-size:0.6rem; text-align:right; margin-top:4px; opacity:0.6; }
        .input-bar { padding:12px; background:#16161d; border-top:1px solid #2a2a33; display:flex; gap:10px; flex-shrink:0; }
        .input-bar input { flex:1; margin:0; }
        .input-bar button { width:auto; padding:12px 20px; margin:0; }
        .contact-info { padding:12px; border-bottom:1px solid #2a2a33; font-weight:bold; background:#1a1a22; }
        .hidden { display:none !important; }
        @media (max-width:640px) {
            .sidebar { position:absolute; z-index:10; height:100%; transform:translateX(-100%); width:260px; transition:0.3s; }
            .sidebar.open { transform:translateX(0); }
            .message { max-width:85%; }
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="logo">ALEX</div>
        <div>
            <button class="btn-icon" id="menuToggle" style="display:none;">☰ Чаты</button>
            <button class="btn-icon" id="logoutBtn" style="display:none;">🚪 Выход</button>
        </div>
    </div>

    <div id="authScreen">
        <div class="auth-container">
            <h2 style="margin-bottom:20px;">Вход в ALEX</h2>
            <input type="text" id="loginUsername" placeholder="Username">
            <input type="password" id="loginPassword" placeholder="Пароль">
            <button id="loginBtn">Войти</button>
            <button id="showRegisterBtn" class="btn-outline">Регистрация</button>
        </div>
        <div id="registerForm" class="hidden auth-container">
            <h2 style="margin-bottom:20px;">Регистрация</h2>
            <input type="text" id="regUsername" placeholder="Username (латиница, 4-32 символа)">
            <input type="text" id="regDisplayName" placeholder="Как вас называть">
            <input type="password" id="regPassword" placeholder="Пароль">
            <button id="doRegisterBtn">Зарегистрироваться</button>
            <button id="backToLoginBtn" class="btn-outline">Назад</button>
        </div>
    </div>

    <div id="mainScreen" class="hidden" style="flex:1; display:flex; flex-direction:column; min-height:0;">
        <div class="main-layout">
            <div class="sidebar" id="sidebar">
                <div class="search-bar">
                    <input type="text" id="searchInput" placeholder="Поиск @username">
                    <button id="searchBtn" style="margin-top:8px;">Найти</button>
                </div>
                <div id="dialogsList" style="flex:1; overflow-y:auto;"></div>
            </div>
            <div class="chat-area">
                <div id="chatHeader" class="contact-info hidden"></div>
                <div class="messages-area" id="messagesArea"></div>
                <div class="input-bar" id="inputBar" style="display:none;">
                    <input type="text" id="messageInput" placeholder="Сообщение...">
                    <button id="sendMsgBtn">Отправить</button>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    let currentUser = null;
    let currentChatUser = null;
    let dialogs = [];
    let pollingInterval = null;

    const authScreen = document.getElementById('authScreen');
    const mainScreen = document.getElementById('mainScreen');
    const loginBtn = document.getElementById('loginBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const showRegisterBtn = document.getElementById('showRegisterBtn');
    const registerForm = document.getElementById('registerForm');
    const backToLoginBtn = document.getElementById('backToLoginBtn');
    const doRegisterBtn = document.getElementById('doRegisterBtn');
    const searchInput = document.getElementById('searchInput');
    const searchBtn = document.getElementById('searchBtn');
    const dialogsList = document.getElementById('dialogsList');
    const chatHeader = document.getElementById('chatHeader');
    const messagesArea = document.getElementById('messagesArea');
    const inputBar = document.getElementById('inputBar');
    const messageInput = document.getElementById('messageInput');
    const sendMsgBtn = document.getElementById('sendMsgBtn');
    const menuToggle = document.getElementById('menuToggle');

    function showToast(msg) {
        let t = document.createElement('div');
        t.innerText = msg;
        t.style.position = 'fixed';
        t.style.bottom = '20px';
        t.style.left = '20px';
        t.style.right = '20px';
        t.style.background = '#333';
        t.style.color = '#fff';
        t.style.padding = '12px';
        t.style.borderRadius = '30px';
        t.style.textAlign = 'center';
        t.style.zIndex = '9999';
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 2000);
    }

    function escapeHtml(str) {
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    function saveMessagesToCache(userId, otherId, messages) {
        const key = `alex_msgs_${userId}_${otherId}`;
        localStorage.setItem(key, JSON.stringify(messages));
    }

    function loadMessagesFromCache(userId, otherId) {
        const key = `alex_msgs_${userId}_${otherId}`;
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : [];
    }

    function renderDialogs() {
        if (!dialogs.length) {
            dialogsList.innerHTML = '<div style="padding:12px; color:#aaa;">Нет диалогов</div>';
            return;
        }
        dialogsList.innerHTML = '';
        dialogs.forEach(d => {
            const div = document.createElement('div');
            div.className = 'dialog-item';
            div.innerHTML = `<div class="dialog-name">${escapeHtml(d.display_name || d.username)}</div><div style="font-size:0.7rem;">@${d.username}</div>`;
            div.onclick = () => openChat(d);
            dialogsList.appendChild(div);
        });
    }

    async function fetchMessagesFromServer(otherId) {
        const res = await fetch(`/api/messages?with=${otherId}`);
        if (res.ok) {
            const data = await res.json();
            return data.messages || [];
        }
        return [];
    }

    function renderMessages(messages) {
        messagesArea.innerHTML = '';
        messages.forEach(msg => {
            const isOwn = (msg.from_id === currentUser.id);
            const div = document.createElement('div');
            div.className = `message ${isOwn ? 'own' : ''}`;
            div.innerHTML = `<div class="text">${escapeHtml(msg.content)}</div><div class="time">${new Date(msg.timestamp * 1000).toLocaleTimeString()}</div>`;
            messagesArea.appendChild(div);
        });
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    async function openChat(user) {
        if (currentChatUser && currentChatUser.id === user.id) return;
        currentChatUser = user;
        chatHeader.innerHTML = `<strong>${escapeHtml(user.display_name || user.username)}</strong> <span style="font-size:0.8rem;">@${user.username}</span>`;
        chatHeader.classList.remove('hidden');
        inputBar.style.display = 'flex';

        const cached = loadMessagesFromCache(currentUser.id, user.id);
        const serverMsgs = await fetchMessagesFromServer(user.id);
        let allMessages = serverMsgs.length ? serverMsgs : cached;
        if (serverMsgs.length) saveMessagesToCache(currentUser.id, user.id, serverMsgs);
        renderMessages(allMessages);
        startPolling(user.id);
    }

    async function sendMessage(content) {
        if (!currentChatUser) return;
        const res = await fetch('/api/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_username: currentChatUser.username, content: content })
        });
        if (res.ok) {
            const data = await res.json();
            const newMsg = {
                from_id: currentUser.id,
                to_id: currentChatUser.id,
                content: content,
                timestamp: data.timestamp
            };
            const cached = loadMessagesFromCache(currentUser.id, currentChatUser.id);
            cached.push(newMsg);
            saveMessagesToCache(currentUser.id, currentChatUser.id, cached);
            renderMessages(cached);
            messageInput.value = '';
            await loadDialogs();
        } else {
            showToast('Ошибка отправки');
        }
    }

    function startPolling(otherId) {
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = setInterval(async () => {
            if (currentChatUser && currentChatUser.id === otherId) {
                const serverMsgs = await fetchMessagesFromServer(otherId);
                const cached = loadMessagesFromCache(currentUser.id, otherId);
                if (serverMsgs.length !== cached.length) {
                    saveMessagesToCache(currentUser.id, otherId, serverMsgs);
                    renderMessages(serverMsgs);
                } else if (serverMsgs.length && cached.length) {
                    const lastServer = serverMsgs[serverMsgs.length-1];
                    const lastCached = cached[cached.length-1];
                    if (lastServer.timestamp !== lastCached.timestamp) {
                        saveMessagesToCache(currentUser.id, otherId, serverMsgs);
                        renderMessages(serverMsgs);
                    }
                }
            }
        }, 10000);
    }

    async function loadDialogs() {
        const res = await fetch('/api/dialogs');
        if (res.ok) {
            const data = await res.json();
            dialogs = data.dialogs;
            renderDialogs();
        }
    }

    async function searchUser(username) {
        if (!username.startsWith('@')) username = '@' + username;
        const clean = username.substring(1);
        const res = await fetch(`/api/search?q=${encodeURIComponent(clean)}`);
        const data = await res.json();
        if (data.user) {
            if (confirm(`Начать чат с ${data.user.display_name || data.user.username}?`)) {
                if (!dialogs.some(d => d.id === data.user.id)) {
                    dialogs.unshift(data.user);
                    renderDialogs();
                }
                openChat(data.user);
            }
        } else {
            showToast('Пользователь не найден');
        }
    }

    async function afterLogin(user) {
        currentUser = user;
        sessionStorage.setItem('alex_user', JSON.stringify(user));
        authScreen.classList.add('hidden');
        mainScreen.classList.remove('hidden');
        logoutBtn.style.display = 'inline-block';
        menuToggle.style.display = 'inline-block';
        await loadDialogs();
        if (dialogs.length > 0) openChat(dialogs[0]);
        menuToggle.onclick = () => document.getElementById('sidebar').classList.toggle('open');
    }

    // ---- ОБРАБОТЧИКИ ----
    doRegisterBtn.onclick = async () => {
        const username = document.getElementById('regUsername').value.trim();
        const display_name = document.getElementById('regDisplayName').value.trim() || username;
        const password = document.getElementById('regPassword').value;
        if (!username || !password) {
            showToast('Заполните все поля');
            return;
        }
        const res = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, display_name, password })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Регистрация успешна, войдите');
            backToLoginBtn.click();
        } else {
            showToast(data.error);
        }
    };

    loginBtn.onclick = async () => {
        const username = document.getElementById('loginUsername').value.trim();
        const password = document.getElementById('loginPassword').value;
        if (!username || !password) {
            showToast('Введите username и пароль');
            return;
        }
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (res.ok) {
            await afterLogin(data.user);
        } else {
            showToast(data.error);
        }
    };

    logoutBtn.onclick = async () => {
        await fetch('/api/logout', { method: 'POST' });
        if (pollingInterval) clearInterval(pollingInterval);
        sessionStorage.clear();
        location.reload();
    };

    showRegisterBtn.onclick = () => {
        document.querySelector('.auth-container').classList.add('hidden');
        registerForm.classList.remove('hidden');
    };

    backToLoginBtn.onclick = () => {
        registerForm.classList.add('hidden');
        document.querySelector('.auth-container').classList.remove('hidden');
    };

    searchBtn.onclick = () => {
        const q = searchInput.value.trim();
        if (q) searchUser(q);
    };
    searchInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') searchBtn.click(); });

    sendMsgBtn.onclick = () => {
        const content = messageInput.value.trim();
        if (content && currentChatUser) sendMessage(content);
    };
    messageInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMsgBtn.click(); });

    const savedUser = sessionStorage.getItem('alex_user');
    if (savedUser) {
        const user = JSON.parse(savedUser);
        afterLogin(user);
    }
</script>
</body>
</html>'''

# ---------- API маршруты ----------
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    display_name = data.get('display_name', username)
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if not re.match(r'^[a-zA-Z0-9_]{4,32}$', username):
        return jsonify({'error': 'Username 4-32 letters/digits/_'}), 400
    if get_user_by_username(username):
        return jsonify({'error': 'Username already exists'}), 409
    pwd_hash = generate_password_hash(password)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = int(time.time())
    c.execute("INSERT INTO users (username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
              (username, display_name, pwd_hash, ts))
    user_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'user_id': user_id})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    user = get_user_by_username(username)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401
    session['user_id'] = user['id']
    return jsonify({'status': 'ok', 'user': {'id': user['id'], 'username': user['username'], 'display_name': user['display_name']}})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'status': 'ok'})

@app.route('/api/search', methods=['GET'])
def search():
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify({'user': None})
    user = get_user_by_username(q)
    if not user:
        return jsonify({'user': None})
    return jsonify({'user': {'id': user['id'], 'username': user['username'], 'display_name': user['display_name']}})

@app.route('/api/send', methods=['POST'])
@login_required
def send_message(user):
    data = request.json
    to_username = data.get('to_username')
    content = data.get('content')
    if not to_username or not content:
        return jsonify({'error': 'Missing parameters'}), 400
    to_user = get_user_by_username(to_username)
    if not to_user:
        return jsonify({'error': 'Recipient not found'}), 404
    msg = add_message(user['id'], to_user['id'], content)
    return jsonify({'status': 'ok', 'timestamp': msg['timestamp']})

@app.route('/api/messages', methods=['GET'])
@login_required
def get_messages(user):
    other_id = request.args.get('with', type=int)
    if not other_id:
        return jsonify({'error': 'Missing "with" param'}), 400
    other = get_user_by_id(other_id)
    if not other:
        return jsonify({'error': 'User not found'}), 404
    msgs = get_messages_between(user['id'], other_id)
    return jsonify({'messages': msgs})

@app.route('/api/dialogs', methods=['GET'])
@login_required
def get_dialogs(user):
    dialogs_set = set()
    for (u1, u2), msgs in messages_store.items():
        if user['id'] in (u1, u2):
            other_id = u2 if u1 == user['id'] else u1
            dialogs_set.add(other_id)
    dialogs_list = []
    for uid in dialogs_set:
        u = get_user_by_id(uid)
        if u:
            dialogs_list.append({'id': u['id'], 'username': u['username'], 'display_name': u['display_name']})
    dialogs_list.sort(key=lambda d: max((msg['timestamp'] for (u1,u2), msgs in messages_store.items() if d['id'] in (u1,u2) for msg in msgs), default=0), reverse=True)
    return jsonify({'dialogs': dialogs_list})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)