#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
import json
import secrets
import time
import re
import uuid
from functools import wraps
from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ---------- База данных SQLite ----------
DB_PATH = 'data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE,
        username TEXT UNIQUE,
        display_name TEXT,
        password_hash TEXT,
        status TEXT DEFAULT 'online',
        last_seen INTEGER,
        is_admin BOOLEAN DEFAULT 0,
        is_banned BOOLEAN DEFAULT 0,
        created_at INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS dialogs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER,
        user2_id INTEGER,
        last_message TEXT,
        last_message_time INTEGER,
        UNIQUE(user1_id, user2_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        creator_id INTEGER,
        invite_link TEXT,
        created_at INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS group_members (
        group_id INTEGER,
        user_id INTEGER,
        role TEXT DEFAULT 'member',
        PRIMARY KEY (group_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        creator_id INTEGER,
        subscribers INTEGER DEFAULT 0,
        created_at INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS channel_subs (
        channel_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (channel_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_type TEXT,
        chat_id INTEGER,
        sender_id INTEGER,
        content TEXT,
        timestamp INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS saved_messages (
        user_id INTEGER,
        message_id INTEGER,
        saved_at INTEGER,
        PRIMARY KEY (user_id, message_id)
    )''')
    conn.commit()
    conn.close()

init_db()

# ---------- Вспомогательные функции ----------
def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, password_hash, status, last_seen, is_admin, is_banned FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2], 'password_hash': row[3], 'status': row[4], 'last_seen': row[5], 'is_admin': bool(row[6]), 'is_banned': bool(row[7])}
    return None

def get_user_by_phone(phone):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, password_hash, status, last_seen, is_admin, is_banned FROM users WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2], 'password_hash': row[3], 'status': row[4], 'last_seen': row[5], 'is_admin': bool(row[6]), 'is_banned': bool(row[7])}
    return None

def get_user_by_id(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, status, last_seen, is_admin, is_banned FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2], 'status': row[3], 'last_seen': row[4], 'is_admin': bool(row[5]), 'is_banned': bool(row[6])}
    return None

def create_dialog(u1, u2):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO dialogs (user1_id, user2_id) VALUES (?, ?)", (min(u1,u2), max(u1,u2)))
    conn.commit()
    conn.close()

def save_message(chat_type, chat_id, sender_id, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = int(time.time())
    c.execute("INSERT INTO messages (chat_type, chat_id, sender_id, content, timestamp) VALUES (?, ?, ?, ?, ?)",
              (chat_type, chat_id, sender_id, content, ts))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id, ts

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        user = get_user_by_id(user_id)
        if not user or user['is_banned']:
            session.clear()
            return jsonify({'error': 'Banned or not exist'}), 403
        return f(user=user, *args, **kwargs)
    return decorated

# ---------- API маршруты ----------
@app.route('/')
def index():
    # Вся HTML-страница с интерфейсом (тёмная тема, адаптив, WebSocket)
    return '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Super Messenger — облачный мессенджер</title>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
        :root { --bg:#0a0a0f; --surface:#16161d; --surface-light:#22222c; --primary:#5e9bff; --primary-dark:#3a7bdb; --text:#f0f0f5; --text-secondary:#aaaabc; --border:#2a2a33; --success:#4cd964; }
        body { background:var(--bg); color:var(--text); font-family:system-ui, -apple-system, 'Segoe UI', Roboto; height:100vh; overflow:hidden; }
        .app { display:flex; flex-direction:column; height:100%; }
        .header { background:var(--surface); padding:14px 20px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }
        .logo { font-weight:700; font-size:1.4rem; background:linear-gradient(135deg,#5e9bff,#b77cff); -webkit-background-clip:text; background-clip:text; color:transparent; }
        .btn-icon { background:var(--surface-light); border:none; color:var(--text); padding:6px 12px; border-radius:30px; cursor:pointer; font-size:1.2rem; }
        .auth-container { padding:30px 20px; max-width:400px; margin:auto; width:100%; }
        input, textarea { width:100%; padding:14px 16px; background:var(--surface); border:1px solid var(--border); border-radius:14px; color:var(--text); font-size:1rem; margin-bottom:16px; outline:none; }
        input:focus { border-color:var(--primary); }
        button { background:var(--primary); color:white; border:none; padding:14px; border-radius:30px; font-weight:600; font-size:1rem; cursor:pointer; width:100%; margin-bottom:10px; transition:0.2s; }
        button:active { transform:scale(0.97); }
        .btn-outline { background:transparent; border:1px solid var(--primary); color:var(--primary); }
        .chat-container { display:flex; flex:1; overflow:hidden; }
        .sidebar { width:280px; background:var(--surface); border-right:1px solid var(--border); display:flex; flex-direction:column; overflow-y:auto; transition:transform 0.3s; }
        .chat-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:75%; padding:10px 14px; border-radius:18px; background:var(--surface-light); align-self:flex-start; word-wrap:break-word; }
        .message.own { background:var(--primary); align-self:flex-end; }
        .message .sender { font-size:0.7rem; opacity:0.7; margin-bottom:4px; }
        .message .text { font-size:0.95rem; }
        .message .time { font-size:0.6rem; text-align:right; margin-top:4px; opacity:0.6; }
        .input-bar { padding:12px; background:var(--surface); border-top:1px solid var(--border); display:flex; gap:10px; }
        .input-bar input { flex:1; margin:0; }
        .input-bar button { width:auto; padding:12px 20px; margin:0; }
        .contact-item, .group-item, .channel-item { padding:12px 16px; border-bottom:1px solid var(--border); cursor:pointer; transition:0.1s; }
        .contact-item:hover, .group-item:hover, .channel-item:hover { background:var(--surface-light); }
        .online { color:var(--success); font-size:0.7rem; }
        .hidden { display:none !important; }
        .tab-bar { background:var(--surface); display:flex; justify-content:space-around; padding:8px 0; border-bottom:1px solid var(--border); }
        .tab { flex:1; text-align:center; padding:10px; background:none; color:var(--text-secondary); border-radius:0; font-size:0.9rem; cursor:pointer; }
        .tab.active { color:var(--primary); border-bottom:2px solid var(--primary); }
        @media (max-width:640px) {
            .sidebar { position:absolute; z-index:10; height:100%; transform:translateX(-100%); width:80%; }
            .sidebar.open { transform:translateX(0); }
            .message { max-width:85%; }
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="logo">☢️ SuperMessenger</div>
        <div><button class="btn-icon" id="logoutBtn" style="display:none;">🚪</button></div>
    </div>
    <div id="authScreen">
        <div class="auth-container">
            <h2>Вход</h2>
            <input type="text" id="loginInput" placeholder="Телефон или @username">
            <input type="password" id="passwordInput" placeholder="Пароль">
            <button id="loginBtn">Войти</button>
            <button id="showRegisterBtn" class="btn-outline">Регистрация</button>
        </div>
        <div id="registerForm" class="hidden auth-container">
            <h2>Регистрация</h2>
            <input type="text" id="regPhone" placeholder="Телефон +7...">
            <input type="text" id="regUsername" placeholder="@username (латиница)">
            <input type="text" id="regDisplayName" placeholder="Имя">
            <input type="password" id="regPassword" placeholder="Пароль">
            <button id="doRegisterBtn">Зарегистрироваться</button>
            <button id="backToLoginBtn" class="btn-outline">Назад</button>
        </div>
    </div>
    <div id="mainScreen" class="hidden" style="flex:1; display:flex; flex-direction:column;">
        <div class="tab-bar">
            <button class="tab active" data-tab="chats">💬 Чаты</button>
            <button class="tab" data-tab="contacts">👥 Контакты</button>
            <button class="tab" data-tab="groups">👥 Группы</button>
            <button class="tab" data-tab="channels">📢 Каналы</button>
        </div>
        <div class="chat-container">
            <div class="sidebar" id="sidebar">
                <div id="chatsList" style="flex:1; overflow-y:auto;"></div>
                <div id="contactsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
                <div id="groupsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
                <div id="channelsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
            </div>
            <div class="chat-area">
                <div id="currentChatHeader" style="padding:12px; border-bottom:1px solid var(--border); font-weight:bold;"></div>
                <div class="messages-area" id="messagesArea"></div>
                <div class="input-bar">
                    <input type="text" id="messageInput" placeholder="Сообщение...">
                    <button id="sendMsgBtn">📤</button>
                </div>
            </div>
        </div>
    </div>
</div>
<script>
    let socket = null, currentUser = null, currentChat = null;
    const authScreen = document.getElementById('authScreen');
    const mainScreen = document.getElementById('mainScreen');
    const loginBtn = document.getElementById('loginBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const showRegisterBtn = document.getElementById('showRegisterBtn');
    const registerForm = document.getElementById('registerForm');
    const backToLoginBtn = document.getElementById('backToLoginBtn');
    const doRegisterBtn = document.getElementById('doRegisterBtn');
    const sendMsgBtn = document.getElementById('sendMsgBtn');
    const messageInput = document.getElementById('messageInput');
    const messagesArea = document.getElementById('messagesArea');
    const currentChatHeader = document.getElementById('currentChatHeader');
    const sidebar = document.getElementById('sidebar');
    const chatsListDiv = document.getElementById('chatsList');
    const contactsListDiv = document.getElementById('contactsList');
    const groupsListDiv = document.getElementById('groupsList');
    const channelsListDiv = document.getElementById('channelsList');
    const tabs = document.querySelectorAll('.tab');

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

    function appendMessage(msg, isOwn) {
        let div = document.createElement('div');
        div.className = `message ${isOwn ? 'own' : ''}`;
        div.innerHTML = `<div class="sender">${isOwn ? 'Вы' : (msg.sender_name || 'Пользователь')}</div>
                         <div class="text">${escapeHtml(msg.content || '')}</div>
                         <div class="time">${new Date(msg.timestamp * 1000).toLocaleTimeString()}</div>`;
        messagesArea.appendChild(div);
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    async function loadMessages(chatType, chatId) {
        const res = await fetch(`/api/messages/${chatType}/${chatId}?limit=50`);
        const data = await res.json();
        messagesArea.innerHTML = '';
        data.messages.forEach(m => appendMessage(m, m.sender_id === currentUser.id));
    }

    async function loadDialogs() {
        const res = await fetch('/api/search?q=');
        const data = await res.json();
        chatsListDiv.innerHTML = '';
        data.results.forEach(u => {
            let div = document.createElement('div');
            div.className = 'contact-item';
            div.innerHTML = `<strong>${u.display_name || u.username}</strong><div class="online">онлайн</div>`;
            div.onclick = () => {
                currentChat = { type: 'private', id: u.id, name: u.username };
                currentChatHeader.innerText = `Чат с ${u.username}`;
                loadMessages('private', Math.min(currentUser.id, u.id));
            };
            chatsListDiv.appendChild(div);
        });
    }

    function initSocket() {
        socket = io();
        socket.on('connect', () => console.log('Socket connected'));
        socket.on('new_private_message', (data) => {
            if (currentChat && currentChat.type === 'private' && currentChat.id === data.from) {
                appendMessage({ content: data.message, timestamp: data.timestamp, sender_id: data.from }, false);
            }
            loadDialogs();
        });
        socket.emit('register');
    }

    // Логин
    loginBtn.onclick = async () => {
        const login = document.getElementById('loginInput').value;
        const pwd = document.getElementById('passwordInput').value;
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ login, password: pwd })
        });
        const data = await res.json();
        if (res.ok) {
            currentUser = data.user;
            sessionStorage.setItem('user', JSON.stringify(currentUser));
            initSocket();
            authScreen.classList.add('hidden');
            mainScreen.classList.remove('hidden');
            logoutBtn.style.display = 'inline-block';
            loadDialogs();
        } else {
            showToast(data.error || 'Ошибка');
        }
    };

    // Регистрация
    showRegisterBtn.onclick = () => {
        document.querySelector('.auth-container').classList.add('hidden');
        registerForm.classList.remove('hidden');
    };
    backToLoginBtn.onclick = () => {
        registerForm.classList.add('hidden');
        document.querySelector('.auth-container').classList.remove('hidden');
    };
    doRegisterBtn.onclick = async () => {
        const phone = document.getElementById('regPhone').value;
        const username = document.getElementById('regUsername').value;
        const display_name = document.getElementById('regDisplayName').value;
        const pwd = document.getElementById('regPassword').value;
        const res = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone, username, display_name, password: pwd })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Регистрация успешна, войдите');
            backToLoginBtn.click();
        } else {
            showToast(data.error);
        }
    };

    // Выход
    logoutBtn.onclick = async () => {
        await fetch('/api/logout', { method: 'POST' });
        if (socket) socket.disconnect();
        sessionStorage.clear();
        location.reload();
    };

    // Отправка сообщения
    sendMsgBtn.onclick = async () => {
        if (!currentChat || !messageInput.value.trim()) return;
        const content = messageInput.value;
        await fetch('/api/message/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_type: currentChat.type,
                chat_id: currentChat.id,
                content: content
            })
        });
        messageInput.value = '';
        loadMessages(currentChat.type, currentChat.id);
    };

    messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMsgBtn.click();
    });

    // Переключение вкладок
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            chatsListDiv.classList.add('hidden');
            contactsListDiv.classList.add('hidden');
            groupsListDiv.classList.add('hidden');
            channelsListDiv.classList.add('hidden');
            if (target === 'chats') chatsListDiv.classList.remove('hidden');
            if (target === 'contacts') contactsListDiv.classList.remove('hidden');
            if (target === 'groups') groupsListDiv.classList.remove('hidden');
            if (target === 'channels') channelsListDiv.classList.remove('hidden');
        });
    });

    // Автоматический вход, если есть сохранённая сессия
    const saved = sessionStorage.getItem('user');
    if (saved) {
        currentUser = JSON.parse(saved);
        initSocket();
        authScreen.classList.add('hidden');
        mainScreen.classList.remove('hidden');
        logoutBtn.style.display = 'inline-block';
        loadDialogs();
    }
</script>
</body>
</html>
    '''

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    phone = data.get('phone')
    username = data.get('username')
    display_name = data.get('display_name', username)
    password = data.get('password')
    if not phone or not username or not password:
        return jsonify({'error': 'Phone, username and password required'}), 400
    if not re.match(r'^\+?[0-9]{7,15}$', phone):
        return jsonify({'error': 'Invalid phone'}), 400
    if not re.match(r'^[a-zA-Z0-9_]{4,32}$', username):
        return jsonify({'error': 'Username 4-32 letters/digits/_'}), 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone = ? OR username = ?", (phone, username))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Phone or username exists'}), 409
    pwd_hash = generate_password_hash(password)
    ts = int(time.time())
    c.execute("INSERT INTO users (phone, username, display_name, password_hash, status, last_seen, created_at, is_admin) VALUES (?, ?, ?, ?, 'online', ?, ?, 0)",
              (phone, username, display_name, pwd_hash, ts, ts))
    user_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'user_id': user_id, 'username': username})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    login_input = data.get('login')
    password = data.get('password')
    if not login_input or not password:
        return jsonify({'error': 'Login and password required'}), 400
    user = get_user_by_username(login_input) or get_user_by_phone(login_input)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401
    if user['is_banned']:
        return jsonify({'error': 'You are banned'}), 403
    session['user_id'] = user['id']
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET status = 'online', last_seen = ? WHERE id = ?", (int(time.time()), user['id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'user': {'id': user['id'], 'username': user['username'], 'display_name': user['display_name'], 'is_admin': user['is_admin']}})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout(user):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET status = 'offline', last_seen = ? WHERE id = ?", (int(time.time()), user['id']))
    conn.commit()
    conn.close()
    session.clear()
    return jsonify({'status': 'ok'})

@app.route('/api/search', methods=['GET'])
@login_required
def search(user):
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify({'results': []})
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name FROM users WHERE (username LIKE ? OR display_name LIKE ?) AND id != ? LIMIT 20",
              (f'%{q}%', f'%{q}%', user['id']))
    rows = c.fetchall()
    conn.close()
    results = [{'id': r[0], 'username': r[1], 'display_name': r[2]} for r in rows]
    return jsonify({'results': results})

@app.route('/api/messages/<chat_type>/<int:chat_id>', methods=['GET'])
@login_required
def get_messages(user, chat_type, chat_id):
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, sender_id, content, timestamp FROM messages WHERE chat_type = ? AND chat_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
              (chat_type, chat_id, limit, offset))
    rows = c.fetchall()
    conn.close()
    messages = [{'id': r[0], 'sender_id': r[1], 'content': r[2], 'timestamp': r[3]} for r in rows]
    messages.reverse()
    return jsonify({'messages': messages})

@app.route('/api/message/send', methods=['POST'])
@login_required
def send_message(user):
    data = request.json
    chat_type = data['chat_type']
    chat_id = data['chat_id']
    content = data.get('content', '')
    if not content:
        return jsonify({'error': 'Empty message'}), 400
    msg_id, ts = save_message(chat_type, chat_id, user['id'], content)
    if chat_type == 'private':
        other_id = chat_id
        create_dialog(user['id'], other_id)
        socketio.emit('new_private_message', {
            'from': user['id'],
            'to': other_id,
            'message': content,
            'message_id': msg_id,
            'timestamp': ts
        }, room=f'user_{other_id}')
    return jsonify({'message_id': msg_id, 'timestamp': ts})

# ---------- WebSocket события ----------
@socketio.on('register')
def on_register():
    user_id = session.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')

# ---------- Запуск ----------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)