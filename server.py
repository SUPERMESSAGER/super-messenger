#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
import secrets
import time
import re
from functools import wraps
from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ---------- Пути к файлам ----------
DB_PATH = 'alex_users.db'
USERS_TXT_PATH = 'users.txt'

# ---------- Инициализация БД ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT,
        password_hash TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        created_at INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id INTEGER,
        to_id INTEGER,
        content TEXT,
        timestamp INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS registration_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        display_name TEXT,
        password_hash TEXT,
        created_at INTEGER
    )''')
    conn.commit()
    conn.close()

init_db()

# ---------- Загрузка пользователей из users.txt ----------
def sync_users_from_file():
    if not os.path.exists(USERS_TXT_PATH):
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    with open(USERS_TXT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(':', 2)
            if len(parts) != 3:
                continue
            username, display_name, password = parts
            pwd_hash = generate_password_hash(password)
            c.execute('''INSERT INTO users (username, display_name, password_hash, created_at)
                         VALUES (?, ?, ?, ?)
                         ON CONFLICT(username) DO UPDATE SET
                         display_name=excluded.display_name,
                         password_hash=excluded.password_hash''',
                      (username, display_name, pwd_hash, int(time.time())))
    c.execute("UPDATE users SET is_admin = 1 WHERE username = '123'")
    conn.commit()
    conn.close()

sync_users_from_file()

# ---------- Функции работы с БД ----------
def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, password_hash, is_admin, is_banned FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2], 'password_hash': row[3],
                'is_admin': bool(row[4]), 'is_banned': bool(row[5])}
    return None

def get_user_by_id(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, is_admin, is_banned FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2],
                'is_admin': bool(row[3]), 'is_banned': bool(row[4])}
    return None

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, is_admin, is_banned, created_at FROM users")
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'username': r[1], 'display_name': r[2], 'is_admin': bool(r[3]), 'is_banned': bool(r[4]), 'created_at': r[5]} for r in rows]

def save_message(from_id, to_id, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = int(time.time())
    c.execute("INSERT INTO messages (from_id, to_id, content, timestamp) VALUES (?, ?, ?, ?)",
              (from_id, to_id, content, ts))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id, ts

def get_messages_between(user1_id, user2_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, from_id, to_id, content, timestamp FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?) ORDER BY timestamp ASC",
              (user1_id, user2_id, user2_id, user1_id))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'from_id': r[1], 'to_id': r[2], 'content': r[3], 'timestamp': r[4]} for r in rows]

def get_all_messages():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, from_id, to_id, content, timestamp FROM messages ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'from_id': r[1], 'to_id': r[2], 'content': r[3], 'timestamp': r[4]} for r in rows]

def add_registration_request(username, display_name, password_hash):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO registration_requests (username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
              (username, display_name, password_hash, int(time.time())))
    conn.commit()
    conn.close()

def get_registration_requests():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, password_hash, created_at FROM registration_requests ORDER BY created_at ASC")
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'username': r[1], 'display_name': r[2], 'password_hash': r[3], 'created_at': r[4]} for r in rows]

def delete_registration_request(req_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM registration_requests WHERE id = ?", (req_id,))
    conn.commit()
    conn.close()

def ban_user(user_id, ban=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = ? WHERE id = ?", (1 if ban else 0, user_id))
    conn.commit()
    conn.close()

def set_admin(user_id, admin=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if admin else 0, user_id))
    conn.commit()
    conn.close()

# ---------- Декораторы ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        user = get_user_by_id(user_id)
        if not user or user.get('is_banned'):
            session.clear()
            return jsonify({'error': 'Banned or not exist'}), 403
        return f(user=user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(user, *args, **kwargs):
        if not user.get('is_admin') and user.get('username') != '123':
            return jsonify({'error': 'Admin rights required'}), 403
        return f(user=user, *args, **kwargs)
    return decorated

# ---------- HTML (встроен, исправленный) ----------
@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>ALEX — мессенджер</title>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
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
        .dialog-item { padding:12px 16px; border-bottom:1px solid #2a2a33; cursor:pointer; transition:0.1s; display:flex; justify-content:space-between; align-items:center; }
        .dialog-item:hover { background:#22222c; }
        .dialog-name { font-weight:600; }
        .admin-badge { color:gold; margin-left:5px; font-size:0.8rem; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:75%; padding:8px 12px; border-radius:18px; background:#22222c; align-self:flex-start; word-wrap:break-word; }
        .message.own { background:#5e9bff; align-self:flex-end; }
        .message .text { font-size:0.95rem; }
        .message .time { font-size:0.6rem; text-align:right; margin-top:4px; opacity:0.6; }
        .input-bar { padding:12px; background:#16161d; border-top:1px solid #2a2a33; display:flex; gap:10px; flex-shrink:0; }
        .input-bar input { flex:1; margin:0; }
        .input-bar button { width:auto; padding:12px 20px; margin:0; }
        .contact-info { padding:12px; border-bottom:1px solid #2a2a33; font-weight:bold; background:#1a1a22; display:flex; justify-content:space-between; align-items:center; }
        .hidden { display:none !important; }
        .admin-panel { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.9); z-index:1000; display:flex; justify-content:center; align-items:center; }
        .admin-panel-content { background:#16161d; width:90%; max-width:800px; max-height:80%; overflow:auto; border-radius:20px; padding:20px; }
        .admin-panel-content table { width:100%; border-collapse:collapse; }
        .admin-panel-content th, .admin-panel-content td { border:1px solid #2a2a33; padding:8px; text-align:left; }
        .admin-panel-content button { width:auto; margin:2px; padding:4px 8px; }
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
            <button class="btn-icon" id="adminBtn" style="display:none;">⚙️ Админ</button>
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
            <h2 style="margin-bottom:20px;">Регистрация (заявка)</h2>
            <input type="text" id="regUsername" placeholder="Username (латиница, 4-32 символа)">
            <input type="text" id="regDisplayName" placeholder="Как вас называть">
            <input type="password" id="regPassword" placeholder="Пароль">
            <button id="doRegisterBtn">Отправить заявку</button>
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
    let socket = null;
    let currentUser = null;
    let currentChatUser = null;
    let dialogs = [];

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
    const adminBtn = document.getElementById('adminBtn');

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
            div.innerHTML = `<div><span class="dialog-name">${escapeHtml(d.display_name || d.username)}</span>${d.is_admin ? '<span class="admin-badge">👑</span>' : ''}<div style="font-size:0.7rem;">@${d.username}</div></div>`;
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
        chatHeader.innerHTML = `<strong>${escapeHtml(user.display_name || user.username)}${user.is_admin ? ' 👑' : ''}</strong> <span style="font-size:0.8rem;">@${user.username}</span>`;
        chatHeader.classList.remove('hidden');
        inputBar.style.display = 'flex';

        const serverMsgs = await fetchMessagesFromServer(user.id);
        saveMessagesToCache(currentUser.id, user.id, serverMsgs);
        renderMessages(serverMsgs);
    }

    async function sendMessage(content) {
        if (!currentChatUser) return;
        const res = await fetch('/api/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_username: currentChatUser.username, content: content })
        });
        if (res.ok) {
            messageInput.value = '';
            await loadDialogs();
        } else {
            showToast('Ошибка отправки');
        }
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

    // WebSocket
    function initSocket() {
        socket = io();
        socket.on('connect', () => console.log('WebSocket connected'));
        socket.on('new_message', (data) => {
            if (currentChatUser && (data.from_id === currentChatUser.id || data.to_id === currentChatUser.id)) {
                fetchMessagesFromServer(currentChatUser.id).then(msgs => {
                    saveMessagesToCache(currentUser.id, currentChatUser.id, msgs);
                    renderMessages(msgs);
                });
            }
            loadDialogs();
        });
        socket.emit('register');
    }

    // Админ-панель (исправленная)
    async function openAdminPanel() {
        const usersRes = await fetch('/api/admin/users');
        const users = await usersRes.json();
        const messagesRes = await fetch('/api/admin/messages');
        const allMessages = await messagesRes.json();
        const requestsRes = await fetch('/api/admin/requests');
        const requests = await requestsRes.json();

        let html = `<div class="admin-panel"><div class="admin-panel-content">
            <h3>Админ-панель</h3>
            <button id="syncUsersBtn">Синхронизировать пользователей из users.txt</button>
            <hr><h4>Пользователи</h4>
            <table><tr><th>ID</th><th>Username</th><th>Имя</th><th>Админ</th><th>Бан</th><th>Действия</th></tr>`;
        for (let u of users) {
            html += `<tr>
                <td>${u.id}</td>
                <td>${escapeHtml(u.username)}</td>
                <td>${escapeHtml(u.display_name)}</td>
                <td>${u.is_admin ? '✅' : '❌'}</td>
                <td>${u.is_banned ? '🔴' : '🟢'}</td>
                <td>
                    <button class="setAdminBtn" data-id="${u.id}" data-admin="${!u.is_admin}">${u.is_admin ? 'Снять админа' : 'Назначить админа'}</button>
                    <button class="banBtn" data-id="${u.id}" data-ban="${!u.is_banned}">${u.is_banned ? 'Разбанить' : 'Забанить'}</button>
                </td>
            </tr>`;
        }
        html += `</table><hr><h4>Заявки на регистрацию</h4><table><tr><th>Username</th><th>Имя</th><th>Дата</th><th>Действие</th></tr>`;
        for (let r of requests) {
            html += `<tr>
                <td>${escapeHtml(r.username)}</td>
                <td>${escapeHtml(r.display_name)}</td>
                <td>${new Date(r.created_at*1000).toLocaleString()}</td>
                <td>
                    <button class="copyRequestBtn" data-username="${escapeHtml(r.username)}" data-display="${escapeHtml(r.display_name)}" data-reqid="${r.id}">Копировать строку для users.txt</button>
                    <button class="deleteReqBtn" data-reqid="${r.id}">Отклонить</button>
                </td>
            </tr>`;
        }
        html += `</table><hr><h4>Все сообщения</h4><table><tr><th>От</th><th>Кому</th><th>Текст</th><th>Время</th></tr>`;
        for (let m of allMessages) {
            const fromUser = users.find(u => u.id === m.from_id);
            const toUser = users.find(u => u.id === m.to_id);
            html += `<tr>
                <td>${fromUser ? fromUser.username : '?'}</td>
                <td>${toUser ? toUser.username : '?'}</td>
                <td>${escapeHtml(m.content)}</td>
                <td>${new Date(m.timestamp*1000).toLocaleString()}</td>
            </tr>`;
        }
        html += `</table><br><button id="closeAdminBtn">Закрыть</button></div></div>`;
        document.body.insertAdjacentHTML('beforeend', html);

        // Обработчики
        document.getElementById('syncUsersBtn').onclick = async () => {
            await fetch('/api/admin/sync_users', {method:'POST'});
            showToast('Синхронизация выполнена');
            setTimeout(() => location.reload(), 1000);
        };
        document.querySelectorAll('.setAdminBtn').forEach(btn => {
            btn.onclick = async () => {
                const userId = btn.dataset.id;
                const isAdmin = btn.dataset.admin === 'true';
                await fetch('/api/admin/set_admin', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({user_id: parseInt(userId), is_admin: isAdmin})
                });
                showToast('Обновлено');
                location.reload();
            };
        });
        document.querySelectorAll('.banBtn').forEach(btn => {
            btn.onclick = async () => {
                const userId = btn.dataset.id;
                const ban = btn.dataset.ban === 'true';
                await fetch('/api/admin/ban', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({user_id: parseInt(userId), ban: ban})
                });
                showToast('Обновлено');
                location.reload();
            };
        });
        document.querySelectorAll('.copyRequestBtn').forEach(btn => {
            btn.onclick = async () => {
                const username = btn.dataset.username;
                const display = btn.dataset.display;
                const reqId = btn.dataset.reqid;
                const password = prompt('Введите пароль пользователя (оригинальный):');
                if (password) {
                    const line = `${username}:${display}:${password}`;
                    await navigator.clipboard.writeText(line);
                    showToast('Строка скопирована! Вставьте её в users.txt и сделайте git push, затем нажмите "Синхронизировать".');
                    // Удаляем заявку после копирования
                    await fetch('/api/admin/delete_request', {
                        method: 'POST',
                        headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({request_id: parseInt(reqId)})
                    });
                    // Перезагружаем админ-панель
                    document.querySelector('.admin-panel').remove();
                    openAdminPanel();
                }
            };
        });
        document.querySelectorAll('.deleteReqBtn').forEach(btn => {
            btn.onclick = async () => {
                const reqId = btn.dataset.reqid;
                await fetch('/api/admin/delete_request', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({request_id: parseInt(reqId)})
                });
                document.querySelector('.admin-panel').remove();
                openAdminPanel();
            };
        });
        document.getElementById('closeAdminBtn').onclick = () => document.querySelector('.admin-panel').remove();
    }

    async function afterLogin(user) {
        currentUser = user;
        sessionStorage.setItem('alex_user', JSON.stringify(user));
        authScreen.classList.add('hidden');
        mainScreen.classList.remove('hidden');
        logoutBtn.style.display = 'inline-block';
        menuToggle.style.display = 'inline-block';
        if (user.is_admin || user.username === '123') adminBtn.style.display = 'inline-block';
        await loadDialogs();
        if (dialogs.length > 0) openChat(dialogs[0]);
        menuToggle.onclick = () => document.getElementById('sidebar').classList.toggle('open');
        adminBtn.onclick = openAdminPanel;
        initSocket();
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
        if (!/^[a-zA-Z0-9_]{4,32}$/.test(username)) {
            showToast('Username 4-32 буквы/цифры/_');
            return;
        }
        const res = await fetch('/api/request_register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, display_name, password })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Заявка отправлена администратору');
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
        if (socket) socket.disconnect();
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
@app.route('/api/request_register', methods=['POST'])
def request_register():
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM registration_requests WHERE username = ?", (username,))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Request already pending'}), 409
    pwd_hash = generate_password_hash(password)
    add_registration_request(username, display_name, pwd_hash)
    return jsonify({'status': 'ok'})

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
    if user['is_banned']:
        return jsonify({'error': 'You are banned'}), 403
    session['user_id'] = user['id']
    return jsonify({'status': 'ok', 'user': {'id': user['id'], 'username': user['username'], 'display_name': user['display_name'], 'is_admin': user['is_admin']}})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'status': 'ok'})

@app.route('/api/search', methods=['GET'])
@login_required
def search(user):
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify({'user': None})
    target = get_user_by_username(q)
    if not target:
        return jsonify({'user': None})
    return jsonify({'user': {'id': target['id'], 'username': target['username'], 'display_name': target['display_name'], 'is_admin': target['is_admin']}})

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
    if to_user['is_banned']:
        return jsonify({'error': 'Recipient is banned'}), 403
    msg_id, ts = save_message(user['id'], to_user['id'], content)
    socketio.emit('new_message', {
        'from_id': user['id'],
        'to_id': to_user['id'],
        'content': content,
        'timestamp': ts
    }, room=f'user_{to_user["id"]}')
    socketio.emit('new_message', {
        'from_id': user['id'],
        'to_id': to_user['id'],
        'content': content,
        'timestamp': ts
    }, room=f'user_{user["id"]}')
    return jsonify({'status': 'ok', 'timestamp': ts})

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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT from_id, to_id FROM messages WHERE from_id = ? OR to_id = ?", (user['id'], user['id']))
    rows = c.fetchall()
    conn.close()
    other_ids = set()
    for row in rows:
        other_id = row[1] if row[0] == user['id'] else row[0]
        other_ids.add(other_id)
    dialogs_list = []
    for uid in other_ids:
        u = get_user_by_id(uid)
        if u:
            dialogs_list.append({'id': u['id'], 'username': u['username'], 'display_name': u['display_name'], 'is_admin': u['is_admin']})
    dialogs_list.sort(key=lambda d: max((msg['timestamp'] for msg in get_messages_between(user['id'], d['id'])), default=0), reverse=True)
    return jsonify({'dialogs': dialogs_list})

# ---------- Админские API ----------
@app.route('/api/admin/users', methods=['GET'])
@login_required
@admin_required
def admin_users(user):
    return jsonify(get_all_users())

@app.route('/api/admin/messages', methods=['GET'])
@login_required
@admin_required
def admin_messages(user):
    return jsonify(get_all_messages())

@app.route('/api/admin/requests', methods=['GET'])
@login_required
@admin_required
def admin_requests(user):
    return jsonify(get_registration_requests())

@app.route('/api/admin/delete_request', methods=['POST'])
@login_required
@admin_required
def admin_delete_request(user):
    data = request.json
    req_id = data.get('request_id')
    if not req_id:
        return jsonify({'error': 'Missing request_id'}), 400
    delete_registration_request(req_id)
    return jsonify({'status': 'ok'})

@app.route('/api/admin/set_admin', methods=['POST'])
@login_required
@admin_required
def admin_set_admin(user):
    data = request.json
    target_id = data.get('user_id')
    is_admin = data.get('is_admin', False)
    if not target_id:
        return jsonify({'error': 'Missing user_id'}), 400
    set_admin(target_id, is_admin)
    return jsonify({'status': 'ok'})

@app.route('/api/admin/ban', methods=['POST'])
@login_required
@admin_required
def admin_ban(user):
    data = request.json
    target_id = data.get('user_id')
    ban = data.get('ban', True)
    if not target_id:
        return jsonify({'error': 'Missing user_id'}), 400
    ban_user(target_id, ban)
    return jsonify({'status': 'ok'})

@app.route('/api/admin/sync_users', methods=['POST'])
@login_required
@admin_required
def admin_sync_users(user):
    sync_users_from_file()
    return jsonify({'status': 'ok'})

# ---------- WebSocket ----------
@socketio.on('register')
def handle_register():
    user_id = session.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)