#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import secrets
import time
import re
from functools import wraps
from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# -------------------- ПОДКЛЮЧЕНИЕ К POSTGRESQL --------------------
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise Exception("DATABASE_URL not set")
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Пользователи
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            phone TEXT UNIQUE,
            username TEXT UNIQUE,
            display_name TEXT,
            password_hash TEXT,
            avatar TEXT,
            bio TEXT,
            stars INTEGER DEFAULT 0,
            status TEXT DEFAULT 'online',
            last_seen INTEGER,
            is_admin BOOLEAN DEFAULT FALSE,
            is_banned BOOLEAN DEFAULT FALSE,
            created_at INTEGER
        )
    ''')
    # Диалоги (личные чаты)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS dialogs (
            id SERIAL PRIMARY KEY,
            user1_id INTEGER,
            user2_id INTEGER,
            last_message TEXT,
            last_message_time INTEGER,
            UNIQUE(user1_id, user2_id)
        )
    ''')
    # Группы
    cur.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id SERIAL PRIMARY KEY,
            title TEXT,
            description TEXT,
            avatar TEXT,
            creator_id INTEGER,
            invite_link TEXT,
            created_at INTEGER
        )
    ''')
    # Участники групп
    cur.execute('''
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER,
            user_id INTEGER,
            role TEXT DEFAULT 'member',
            muted_until INTEGER DEFAULT 0,
            PRIMARY KEY (group_id, user_id)
        )
    ''')
    # Каналы
    cur.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id SERIAL PRIMARY KEY,
            title TEXT,
            description TEXT,
            avatar TEXT,
            creator_id INTEGER,
            subscribers INTEGER DEFAULT 0,
            created_at INTEGER
        )
    ''')
    # Подписчики каналов
    cur.execute('''
        CREATE TABLE IF NOT EXISTS channel_subs (
            channel_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (channel_id, user_id)
        )
    ''')
    # Сообщения
    cur.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            chat_type TEXT,
            chat_id INTEGER,
            sender_id INTEGER,
            content TEXT,
            edited BOOLEAN DEFAULT FALSE,
            reactions TEXT DEFAULT '{}',
            timestamp INTEGER
        )
    ''')
    # Сохранённые сообщения
    cur.execute('''
        CREATE TABLE IF NOT EXISTS saved_messages (
            user_id INTEGER,
            message_id INTEGER,
            saved_at INTEGER,
            PRIMARY KEY (user_id, message_id)
        )
    ''')
    # Подарки
    cur.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            id SERIAL PRIMARY KEY,
            name TEXT,
            price INTEGER,
            icon TEXT
        )
    ''')
    # Отправленные подарки
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_gifts (
            id SERIAL PRIMARY KEY,
            from_user INTEGER,
            to_user INTEGER,
            gift_id INTEGER,
            message TEXT,
            timestamp INTEGER
        )
    ''')
    # Стикеры (предустановленные)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS stickers (
            id SERIAL PRIMARY KEY,
            pack_name TEXT,
            emoji TEXT,
            image_url TEXT
        )
    ''')
    # Вставляем стандартные подарки, если пусто
    cur.execute("SELECT COUNT(*) FROM gifts")
    if cur.fetchone()['count'] == 0:
        gifts = [
            ('🌹 Роза', 5, '🌹'),
            ('🎁 Подарок', 10, '🎁'),
            ('💎 Бриллиант', 50, '💎'),
            ('⭐ Звезда', 1, '⭐'),
            ('🏆 Трофей', 100, '🏆')
        ]
        cur.executemany("INSERT INTO gifts (name, price, icon) VALUES (%s, %s, %s)", gifts)
    # Вставляем стартовый набор стикеров
    cur.execute("SELECT COUNT(*) FROM stickers")
    if cur.fetchone()['count'] == 0:
        stickers = [
            ('default', '😀', 'https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/1f600.png'),
            ('default', '😂', 'https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/1f602.png'),
            ('default', '❤️', 'https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/2764.png'),
            ('default', '👍', 'https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/1f44d.png'),
        ]
        cur.executemany("INSERT INTO stickers (pack_name, emoji, image_url) VALUES (%s, %s, %s)", stickers)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# -------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ --------------------
def get_user_by_username(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, password_hash, avatar, bio, stars, status, last_seen, is_admin, is_banned FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def get_user_by_phone(phone):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, password_hash, avatar, bio, stars, status, last_seen, is_admin, is_banned FROM users WHERE phone = %s", (phone,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, avatar, bio, stars, status, last_seen, is_admin, is_banned FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def create_dialog(u1, u2):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO dialogs (user1_id, user2_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (min(u1,u2), max(u1,u2)))
    conn.commit()
    cur.close()
    conn.close()

def save_message(chat_type, chat_id, sender_id, content, reactions=None):
    conn = get_db_connection()
    cur = conn.cursor()
    ts = int(time.time())
    reactions_json = json.dumps(reactions or {})
    cur.execute("""
        INSERT INTO messages (chat_type, chat_id, sender_id, content, reactions, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (chat_type, chat_id, sender_id, content, reactions_json, ts))
    msg_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
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

def admin_required(f):
    @wraps(f)
    def decorated(user, *args, **kwargs):
        if not user['is_admin'] and user['username'] != 'asdfg':
            return jsonify({'error': 'Admin rights required'}), 403
        return f(user=user, *args, **kwargs)
    return decorated

# -------------------- HTML ИНТЕРФЕЙС (встроен) --------------------
@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Super Messenger — звёзды, подарки, админка</title>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        :root { --bg:#0a0a0f; --surface:#16161d; --surface-light:#22222c; --primary:#5e9bff; --text:#f0f0f5; --text-secondary:#aaaabc; --border:#2a2a33; --success:#4cd964; --danger:#ff5e5e; }
        body { background:var(--bg); color:var(--text); font-family:system-ui; height:100vh; overflow:hidden; }
        .app { display:flex; flex-direction:column; height:100%; }
        .header { background:var(--surface); padding:12px 20px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }
        .logo { font-weight:700; font-size:1.4rem; background:linear-gradient(135deg,#5e9bff,#b77cff); -webkit-background-clip:text; background-clip:text; color:transparent; }
        .user-info { display:flex; gap:15px; align-items:center; }
        .stars-badge { background:rgba(255,215,0,0.2); padding:6px 12px; border-radius:20px; font-size:0.9rem; cursor:pointer; }
        .stars-badge span { color:gold; }
        .btn-icon { background:var(--surface-light); border:none; color:var(--text); padding:6px 12px; border-radius:30px; cursor:pointer; font-size:1.2rem; }
        .auth-container { padding:30px 20px; max-width:400px; margin:auto; }
        input, textarea, select { width:100%; padding:12px; background:var(--surface); border:1px solid var(--border); border-radius:12px; color:var(--text); margin-bottom:12px; outline:none; }
        button { background:var(--primary); color:white; border:none; padding:12px; border-radius:30px; font-weight:600; cursor:pointer; width:100%; margin-bottom:10px; transition:0.2s; }
        button:active { transform:scale(0.97); }
        .btn-outline { background:transparent; border:1px solid var(--primary); color:var(--primary); }
        .chat-container { display:flex; flex:1; overflow:hidden; }
        .sidebar { width:280px; background:var(--surface); border-right:1px solid var(--border); display:flex; flex-direction:column; overflow-y:auto; }
        .chat-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:75%; padding:8px 12px; border-radius:18px; background:var(--surface-light); align-self:flex-start; word-wrap:break-word; position:relative; }
        .message.own { background:var(--primary); align-self:flex-end; }
        .message .sender { font-size:0.7rem; opacity:0.7; margin-bottom:4px; }
        .message .text { font-size:0.95rem; }
        .message .time { font-size:0.6rem; text-align:right; margin-top:4px; opacity:0.6; }
        .message .actions { position:absolute; top:5px; right:5px; display:none; gap:5px; background:var(--surface); padding:2px 5px; border-radius:12px; }
        .message:hover .actions { display:flex; }
        .message .actions button { background:none; border:none; color:var(--text); font-size:0.8rem; padding:2px 5px; width:auto; margin:0; cursor:pointer; }
        .input-bar { padding:12px; background:var(--surface); border-top:1px solid var(--border); display:flex; gap:10px; }
        .input-bar input { flex:1; margin:0; }
        .input-bar button { width:auto; padding:12px 20px; margin:0; }
        .contact-item, .group-item, .channel-item, .gift-item { padding:10px 12px; border-bottom:1px solid var(--border); cursor:pointer; display:flex; align-items:center; gap:10px; }
        .contact-item:hover, .group-item:hover, .channel-item:hover, .gift-item:hover { background:var(--surface-light); }
        .avatar { width:40px; height:40px; border-radius:50%; background:var(--primary); display:flex; align-items:center; justify-content:center; font-size:1.2rem; }
        .hidden { display:none !important; }
        .tab-bar { background:var(--surface); display:flex; justify-content:space-around; padding:8px 0; border-bottom:1px solid var(--border); }
        .tab { flex:1; text-align:center; padding:10px; background:none; color:var(--text-secondary); border-radius:0; cursor:pointer; }
        .tab.active { color:var(--primary); border-bottom:2px solid var(--primary); }
        .modal { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.8); display:flex; align-items:center; justify-content:center; z-index:1000; }
        .modal-content { background:var(--surface); border-radius:20px; padding:20px; max-width:90%; width:400px; max-height:80%; overflow-y:auto; }
        .search-bar { padding:10px; background:var(--surface); border-bottom:1px solid var(--border); }
        .search-bar input { margin:0; background:var(--surface-light); }
        .reactions { display:flex; gap:4px; margin-top:4px; }
        .reaction { cursor:pointer; font-size:0.8rem; background:var(--surface); border-radius:12px; padding:2px 6px; }
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
        <div class="user-info">
            <div id="starsDisplay" class="stars-badge hidden">⭐ <span>0</span></div>
            <button class="btn-icon" id="profileBtn" style="display:none;">👤</button>
            <button class="btn-icon" id="adminBtn" style="display:none;">⚙️</button>
            <button class="btn-icon" id="logoutBtn" style="display:none;">🚪</button>
        </div>
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
            <button class="tab" data-tab="gifts">🎁 Подарки</button>
            <button class="tab" data-tab="saved">⭐ Избранное</button>
        </div>
        <div class="chat-container">
            <div class="sidebar" id="sidebar">
                <div class="search-bar"><input type="text" id="searchUsers" placeholder="Поиск по username..."></div>
                <div id="chatsList" style="flex:1; overflow-y:auto;"></div>
                <div id="contactsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
                <div id="groupsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
                <div id="channelsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
                <div id="giftsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
                <div id="savedList" class="hidden" style="flex:1; overflow-y:auto;"></div>
            </div>
            <div class="chat-area">
                <div id="currentChatHeader" style="padding:12px; border-bottom:1px solid var(--border); font-weight:bold;"></div>
                <div class="messages-area" id="messagesArea"></div>
                <div class="input-bar">
                    <input type="text" id="messageInput" placeholder="Сообщение...">
                    <button id="sendMsgBtn">📤</button>
                    <button id="stickerBtn" class="btn-outline" style="width:auto;">😀</button>
                </div>
                <div id="stickerPanel" class="hidden" style="display:flex; gap:8px; padding:8px; overflow-x:auto; background:var(--surface);"></div>
            </div>
        </div>
    </div>
</div>
<div id="profileModal" class="modal hidden"><div class="modal-content"><div id="profileContent"></div><button id="closeProfile">Закрыть</button></div></div>
<div id="adminModal" class="modal hidden"><div class="modal-content"><div id="adminContent"></div><button id="closeAdmin">Закрыть</button></div></div>
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
    const stickerBtn = document.getElementById('stickerBtn');
    const stickerPanel = document.getElementById('stickerPanel');
    const messageInput = document.getElementById('messageInput');
    const messagesArea = document.getElementById('messagesArea');
    const currentChatHeader = document.getElementById('currentChatHeader');
    const sidebar = document.getElementById('sidebar');
    const chatsListDiv = document.getElementById('chatsList');
    const contactsListDiv = document.getElementById('contactsList');
    const groupsListDiv = document.getElementById('groupsList');
    const channelsListDiv = document.getElementById('channelsList');
    const giftsListDiv = document.getElementById('giftsList');
    const savedListDiv = document.getElementById('savedList');
    const tabs = document.querySelectorAll('.tab');
    const starsDisplay = document.getElementById('starsDisplay');
    const profileBtn = document.getElementById('profileBtn');
    const adminBtn = document.getElementById('adminBtn');
    const searchInput = document.getElementById('searchUsers');
    let searchTimeout = null;

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
        let reactionsHtml = '';
        if (msg.reactions && Object.keys(msg.reactions).length) {
            reactionsHtml = '<div class="reactions">' + Object.entries(msg.reactions).map(([uid, emoji]) => `<span class="reaction" data-msg="${msg.id}" data-emoji="${emoji}">${emoji}</span>`).join('') + '</div>';
        }
        div.innerHTML = `<div class="sender">${isOwn ? 'Вы' : (msg.sender_name || 'Пользователь')}</div>
                         <div class="text">${escapeHtml(msg.content || '')}</div>
                         <div class="time">${new Date(msg.timestamp * 1000).toLocaleTimeString()}</div>
                         <div class="actions">
                            <button class="saveMsg" data-id="${msg.id}">⭐</button>
                            <button class="editMsg" data-id="${msg.id}">✏️</button>
                            ${currentUser && (currentUser.is_admin || currentUser.username === 'asdfg') ? `<button class="deleteMsg" data-id="${msg.id}">🗑️</button>` : ''}
                         </div>
                         ${reactionsHtml}`;
        messagesArea.appendChild(div);
        messagesArea.scrollTop = messagesArea.scrollHeight;
        div.querySelector('.saveMsg')?.addEventListener('click', (e) => {
            e.stopPropagation();
            saveMessageToFav(msg.id);
        });
        div.querySelector('.editMsg')?.addEventListener('click', (e) => {
            e.stopPropagation();
            editMessage(msg.id);
        });
        if (currentUser && (currentUser.is_admin || currentUser.username === 'asdfg')) {
            div.querySelector('.deleteMsg')?.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteMessage(msg.id);
            });
        }
        div.querySelectorAll('.reaction').forEach(r => {
            r.addEventListener('click', () => addReaction(msg.id, r.dataset.emoji));
        });
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
            div.innerHTML = `<div class="avatar">${(u.display_name || u.username)[0].toUpperCase()}</div><div><strong>${u.display_name || u.username}</strong><div class="online">${u.status === 'online' ? 'онлайн' : 'был(а) ' + new Date(u.last_seen * 1000).toLocaleString()}</div></div>`;
            div.onclick = () => {
                currentChat = { type: 'private', id: u.id, name: u.username };
                currentChatHeader.innerText = `Чат с ${u.username}`;
                loadMessages('private', Math.min(currentUser.id, u.id));
            };
            chatsListDiv.appendChild(div);
        });
    }

    async function loadGroups() {
        const res = await fetch('/api/groups');
        const data = await res.json();
        groupsListDiv.innerHTML = '';
        data.groups.forEach(g => {
            let div = document.createElement('div');
            div.className = 'group-item';
            div.innerHTML = `<div class="avatar">${(g.title[0] || 'G').toUpperCase()}</div><div><strong>${g.title}</strong><div>${g.description || ''}</div></div>`;
            div.onclick = () => {
                currentChat = { type: 'group', id: g.id, name: g.title };
                currentChatHeader.innerText = `Группа ${g.title}`;
                loadMessages('group', g.id);
            };
            groupsListDiv.appendChild(div);
        });
    }

    async function loadChannels() {
        const res = await fetch('/api/channels');
        const data = await res.json();
        channelsListDiv.innerHTML = '';
        data.channels.forEach(c => {
            let div = document.createElement('div');
            div.className = 'channel-item';
            div.innerHTML = `<div class="avatar">📢</div><div><strong>${c.title}</strong><div>Подписчиков: ${c.subscribers}</div></div>`;
            div.onclick = () => {
                currentChat = { type: 'channel', id: c.id, name: c.title };
                currentChatHeader.innerText = `Канал ${c.title}`;
                loadMessages('channel', c.id);
            };
            channelsListDiv.appendChild(div);
        });
    }

    async function loadGifts() {
        const res = await fetch('/api/gifts');
        const data = await res.json();
        giftsListDiv.innerHTML = '';
        data.gifts.forEach(g => {
            let div = document.createElement('div');
            div.className = 'gift-item';
            div.innerHTML = `<div style="font-size:2rem;">${g.icon}</div><div><strong>${g.name}</strong><div>${g.price} ⭐</div></div>`;
            div.onclick = () => sendGift(g.id);
            giftsListDiv.appendChild(div);
        });
    }

    async function loadSaved() {
        const res = await fetch('/api/saved_messages');
        const data = await res.json();
        savedListDiv.innerHTML = '';
        data.saved.forEach(s => {
            let div = document.createElement('div');
            div.className = 'contact-item';
            div.innerHTML = `<div><strong>${escapeHtml(s.content.substring(0, 50))}</strong><div class="time">${new Date(s.timestamp * 1000).toLocaleString()}</div></div>`;
            savedListDiv.appendChild(div);
        });
    }

    async function loadStickers() {
        const res = await fetch('/api/stickers');
        const data = await res.json();
        stickerPanel.innerHTML = '';
        data.stickers.forEach(s => {
            let img = document.createElement('img');
            img.src = s.image_url;
            img.style.width = '40px';
            img.style.cursor = 'pointer';
            img.onclick = () => {
                messageInput.value += s.emoji;
                stickerPanel.classList.add('hidden');
            };
            stickerPanel.appendChild(img);
        });
    }

    async function sendGift(giftId) {
        const username = prompt('Введите username получателя:');
        if (!username) return;
        const msg = prompt('Сообщение к подарку (необязательно):');
        const res = await fetch('/api/gift/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_username: username, gift_id: giftId, message: msg || '' })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Подарок отправлен! У вас осталось ${data.stars_balance} ⭐`);
            updateStars(data.stars_balance);
        } else {
            showToast(data.error);
        }
    }

    async function saveMessageToFav(msgId) {
        const res = await fetch('/api/save_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message_id: msgId })
        });
        if (res.ok) showToast('Сохранено в избранное');
        else showToast('Ошибка');
    }

    async function editMessage(msgId) {
        const newText = prompt('Введите новый текст сообщения:');
        if (!newText) return;
        const res = await fetch('/api/message/edit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message_id: msgId, content: newText })
        });
        if (res.ok) {
            showToast('Сообщение отредактировано');
            if (currentChat) loadMessages(currentChat.type, currentChat.id);
        } else {
            showToast('Ошибка');
        }
    }

    async function deleteMessage(msgId) {
        if (!confirm('Удалить сообщение?')) return;
        const res = await fetch('/api/message/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message_id: msgId })
        });
        if (res.ok) {
            showToast('Сообщение удалено');
            if (currentChat) loadMessages(currentChat.type, currentChat.id);
        } else {
            showToast('Ошибка');
        }
    }

    async function addReaction(msgId, emoji) {
        const res = await fetch('/api/message/react', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message_id: msgId, emoji: emoji })
        });
        if (res.ok) {
            if (currentChat) loadMessages(currentChat.type, currentChat.id);
        }
    }

    async function updateStars(balance) {
        starsDisplay.querySelector('span').innerText = balance;
    }

    async function showProfile(username) {
        const res = await fetch(`/api/user/profile/${username}`);
        const data = await res.json();
        document.getElementById('profileContent').innerHTML = `
            <div style="text-align:center;">
                <div class="avatar" style="width:80px;height:80px;font-size:3rem;margin:0 auto;">${(data.display_name || data.username)[0].toUpperCase()}</div>
                <h3>${data.display_name || data.username}</h3>
                <p>@${data.username}</p>
                <p>${data.bio || 'Нет описания'}</p>
                <p>⭐ ${data.stars} звёзд</p>
                <p>${data.status === 'online' ? '🟢 Онлайн' : '⚫ Был(а) ' + new Date(data.last_seen * 1000).toLocaleString()}</p>
                ${currentUser.username === username ? `<button id="editProfileBtn">Редактировать профиль</button>` : ''}
                ${currentUser.username !== username ? `<button id="sendGiftToProfile">Отправить подарок</button>` : ''}
            </div>
        `;
        document.getElementById('profileModal').classList.remove('hidden');
        if (currentUser.username === username) {
            document.getElementById('editProfileBtn').onclick = () => {
                const newBio = prompt('Введите новое описание:', data.bio || '');
                if (newBio !== null) {
                    fetch('/api/user/update_profile', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ bio: newBio })
                    }).then(() => showProfile(username));
                }
            };
        }
        if (currentUser.username !== username) {
            document.getElementById('sendGiftToProfile')?.addEventListener('click', () => {
                // Открыть выбор подарка (упрощённо)
                sendGiftToUser(username);
            });
        }
    }

    async function sendGiftToUser(username) {
        const resGifts = await fetch('/api/gifts');
        const gifts = await resGifts.json();
        const giftOptions = gifts.gifts.map(g => `${g.id}: ${g.name} (${g.price}⭐)`).join('\n');
        const giftId = prompt(`Выберите подарок:\n${giftOptions}\nВведите ID подарка:`);
        if (!giftId) return;
        const msg = prompt('Сообщение к подарку:');
        const res = await fetch('/api/gift/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to_username: username, gift_id: giftId, message: msg || '' })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Подарок отправлен! У вас осталось ${data.stars_balance} ⭐`);
            updateStars(data.stars_balance);
        } else {
            showToast(data.error);
        }
    }

    function initSocket() {
        socket = io();
        socket.on('connect', () => console.log('Socket connected'));
        socket.on('new_private_message', (data) => {
            if (currentChat && currentChat.type === 'private' && currentChat.id === data.from) {
                appendMessage({ content: data.message, timestamp: data.timestamp, sender_id: data.from, id: data.message_id, reactions: {} }, false);
            }
            loadDialogs();
        });
        socket.on('new_group_message', (data) => {
            if (currentChat && currentChat.type === 'group' && currentChat.id === data.group_id) {
                appendMessage({ content: data.message, timestamp: data.timestamp, sender_id: data.from, id: data.message_id, reactions: {} }, false);
            }
        });
        socket.on('new_channel_post', (data) => {
            if (currentChat && currentChat.type === 'channel' && currentChat.id === data.channel_id) {
                appendMessage({ content: data.message, timestamp: data.timestamp, sender_id: data.from, id: data.message_id, reactions: {} }, false);
            }
        });
        socket.emit('register');
    }

    // Поиск пользователей
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        const q = searchInput.value.trim();
        if (q.length < 2) return;
        searchTimeout = setTimeout(async () => {
            const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
            const data = await res.json();
            chatsListDiv.innerHTML = '';
            data.results.forEach(u => {
                let div = document.createElement('div');
                div.className = 'contact-item';
                div.innerHTML = `<div class="avatar">${(u.display_name || u.username)[0].toUpperCase()}</div><div><strong>${u.display_name || u.username}</strong><div>@${u.username}</div></div>`;
                div.onclick = () => {
                    currentChat = { type: 'private', id: u.id, name: u.username };
                    currentChatHeader.innerText = `Чат с ${u.username}`;
                    loadMessages('private', Math.min(currentUser.id, u.id));
                };
                chatsListDiv.appendChild(div);
            });
        }, 300);
    });

    // Авторизация
    loginBtn.onclick = async () => {
        const login = document.getElementById('loginInput').value;
        const pwd = document.getElementById('passwordInput').value;
        const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login, password: pwd }) });
        const data = await res.json();
        if (res.ok) {
            currentUser = data.user;
            sessionStorage.setItem('user', JSON.stringify(currentUser));
            initSocket();
            authScreen.classList.add('hidden');
            mainScreen.classList.remove('hidden');
            logoutBtn.style.display = 'inline-block';
            profileBtn.style.display = 'inline-block';
            starsDisplay.style.display = 'inline-block';
            updateStars(currentUser.stars);
            if (currentUser.is_admin || currentUser.username === 'asdfg') adminBtn.style.display = 'inline-block';
            loadDialogs();
            loadGroups();
            loadChannels();
            loadGifts();
            loadSaved();
            loadStickers();
        } else {
            showToast(data.error);
        }
    };

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
        const res = await fetch('/api/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ phone, username, display_name, password: pwd }) });
        const data = await res.json();
        if (res.ok) {
            showToast('Регистрация успешна, войдите');
            backToLoginBtn.click();
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

    profileBtn.onclick = () => showProfile(currentUser.username);
    adminBtn.onclick = async () => {
        const res = await fetch('/api/admin/stats');
        const stats = await res.json();
        document.getElementById('adminContent').innerHTML = `
            <h3>Админ-панель</h3>
            <p>Всего пользователей: ${stats.total_users}</p>
            <p>Всего сообщений: ${stats.total_messages}</p>
            <p>Звёзд в системе: ${stats.total_stars}</p>
            <hr>
            <input type="text" id="banUser" placeholder="Username для бана">
            <button id="banBtn">Забанить</button>
            <input type="text" id="unbanUser" placeholder="Username для разбана">
            <button id="unbanBtn">Разбанить</button>
            <hr>
            <h4>Добавить звёзды пользователю</h4>
            <input type="text" id="addStarsUser" placeholder="Username">
            <input type="number" id="addStarsAmount" placeholder="Количество">
            <button id="addStarsBtn">Добавить звёзды</button>
        `;
        document.getElementById('adminModal').classList.remove('hidden');
        document.getElementById('banBtn').onclick = async () => {
            const username = document.getElementById('banUser').value;
            if (!username) return;
            await fetch('/api/admin/ban', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }) });
            showToast(`Пользователь ${username} забанен`);
        };
        document.getElementById('unbanBtn').onclick = async () => {
            const username = document.getElementById('unbanUser').value;
            if (!username) return;
            await fetch('/api/admin/unban', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }) });
            showToast(`Пользователь ${username} разбанен`);
        };
        document.getElementById('addStarsBtn').onclick = async () => {
            const username = document.getElementById('addStarsUser').value;
            const amount = parseInt(document.getElementById('addStarsAmount').value);
            if (!username || isNaN(amount)) return;
            await fetch('/api/admin/add_stars', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, amount }) });
            showToast(`Добавлено ${amount} звёзд пользователю ${username}`);
        };
    };
    document.getElementById('closeProfile').onclick = () => document.getElementById('profileModal').classList.add('hidden');
    document.getElementById('closeAdmin').onclick = () => document.getElementById('adminModal').classList.add('hidden');

    sendMsgBtn.onclick = async () => {
        if (!currentChat || !messageInput.value.trim()) return;
        const content = messageInput.value;
        await fetch('/api/message/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_type: currentChat.type, chat_id: currentChat.id, content: content })
        });
        messageInput.value = '';
        loadMessages(currentChat.type, currentChat.id);
    };
    messageInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMsgBtn.click(); });
    stickerBtn.onclick = () => stickerPanel.classList.toggle('hidden');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            chatsListDiv.classList.add('hidden');
            contactsListDiv.classList.add('hidden');
            groupsListDiv.classList.add('hidden');
            channelsListDiv.classList.add('hidden');
            giftsListDiv.classList.add('hidden');
            savedListDiv.classList.add('hidden');
            if (target === 'chats') chatsListDiv.classList.remove('hidden');
            if (target === 'contacts') contactsListDiv.classList.remove('hidden');
            if (target === 'groups') groupsListDiv.classList.remove('hidden');
            if (target === 'channels') channelsListDiv.classList.remove('hidden');
            if (target === 'gifts') { giftsListDiv.classList.remove('hidden'); loadGifts(); }
            if (target === 'saved') { savedListDiv.classList.remove('hidden'); loadSaved(); }
        });
    });

    const saved = sessionStorage.getItem('user');
    if (saved) {
        currentUser = JSON.parse(saved);
        initSocket();
        authScreen.classList.add('hidden');
        mainScreen.classList.remove('hidden');
        logoutBtn.style.display = 'inline-block';
        profileBtn.style.display = 'inline-block';
        starsDisplay.style.display = 'inline-block';
        updateStars(currentUser.stars);
        if (currentUser.is_admin || currentUser.username === 'asdfg') adminBtn.style.display = 'inline-block';
        loadDialogs();
        loadGroups();
        loadChannels();
        loadGifts();
        loadSaved();
        loadStickers();
    }
</script>
</body>
</html>
    '''

# -------------------- API: ГРУППЫ --------------------
@app.route('/api/groups', methods=['GET'])
@login_required
def get_groups(user):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT g.id, g.title, g.description, g.avatar
        FROM groups g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = %s
    """, (user['id'],))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({'groups': rows})

@app.route('/api/group/create', methods=['POST'])
@login_required
def create_group(user):
    data = request.json
    title = data.get('title', 'Новая группа')
    description = data.get('description', '')
    conn = get_db_connection()
    cur = conn.cursor()
    ts = int(time.time())
    cur.execute("INSERT INTO groups (title, description, creator_id, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
                (title, description, user['id'], ts))
    group_id = cur.fetchone()['id']
    cur.execute("INSERT INTO group_members (group_id, user_id, role) VALUES (%s, %s, 'admin')", (group_id, user['id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'group_id': group_id, 'status': 'ok'})

@app.route('/api/group/join', methods=['POST'])
@login_required
def join_group(user):
    data = request.json
    group_id = data.get('group_id')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO group_members (group_id, user_id, role) VALUES (%s, %s, 'member') ON CONFLICT DO NOTHING",
                (group_id, user['id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'status': 'joined'})

# -------------------- API: КАНАЛЫ --------------------
@app.route('/api/channels', methods=['GET'])
@login_required
def get_channels(user):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.title, c.description, c.avatar, c.subscribers
        FROM channels c
        JOIN channel_subs cs ON c.id = cs.channel_id
        WHERE cs.user_id = %s
    """, (user['id'],))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({'channels': rows})

@app.route('/api/channel/create', methods=['POST'])
@login_required
def create_channel(user):
    data = request.json
    title = data.get('title')
    description = data.get('description', '')
    if not title:
        return jsonify({'error': 'Title required'}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    ts = int(time.time())
    cur.execute("INSERT INTO channels (title, description, creator_id, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
                (title, description, user['id'], ts))
    channel_id = cur.fetchone()['id']
    cur.execute("INSERT INTO channel_subs (channel_id, user_id) VALUES (%s, %s)", (channel_id, user['id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'channel_id': channel_id, 'status': 'ok'})

@app.route('/api/channel/subscribe', methods=['POST'])
@login_required
def subscribe_channel(user):
    data = request.json
    channel_id = data.get('channel_id')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO channel_subs (channel_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (channel_id, user['id']))
    cur.execute("UPDATE channels SET subscribers = (SELECT COUNT(*) FROM channel_subs WHERE channel_id = %s) WHERE id = %s", (channel_id, channel_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'status': 'subscribed'})

# -------------------- API: СООБЩЕНИЯ (расширенные) --------------------
@app.route('/api/message/edit', methods=['POST'])
@login_required
def edit_message(user):
    data = request.json
    msg_id = data.get('message_id')
    new_content = data.get('content')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT sender_id FROM messages WHERE id = %s", (msg_id,))
    row = cur.fetchone()
    if not row or row['sender_id'] != user['id']:
        cur.close()
        conn.close()
        return jsonify({'error': 'Not allowed'}), 403
    cur.execute("UPDATE messages SET content = %s, edited = TRUE WHERE id = %s", (new_content, msg_id))
    conn.commit()
    cur.close()
    conn.close()
    socketio.emit('message_edited', {'message_id': msg_id, 'new_content': new_content})
    return jsonify({'status': 'edited'})

@app.route('/api/message/react', methods=['POST'])
@login_required
def add_reaction(user):
    data = request.json
    msg_id = data.get('message_id')
    emoji = data.get('emoji')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT reactions FROM messages WHERE id = %s", (msg_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({'error': 'Message not found'}), 404
    reactions = json.loads(row['reactions'] or '{}')
    reactions[str(user['id'])] = emoji
    cur.execute("UPDATE messages SET reactions = %s WHERE id = %s", (json.dumps(reactions), msg_id))
    conn.commit()
    cur.close()
    conn.close()
    socketio.emit('reaction_updated', {'message_id': msg_id, 'reactions': reactions})
    return jsonify({'status': 'reacted'})

# -------------------- API: СТИКЕРЫ --------------------
@app.route('/api/stickers', methods=['GET'])
@login_required
def get_stickers(user):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, pack_name, emoji, image_url FROM stickers")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({'stickers': rows})

# -------------------- ОСТАЛЬНЫЕ API (регистрация, логин, поиск, сообщения и т.д.) --------------------
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone = %s OR username = %s", (phone, username))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'error': 'Phone or username exists'}), 409
    pwd_hash = generate_password_hash(password)
    ts = int(time.time())
    cur.execute("""
        INSERT INTO users (phone, username, display_name, password_hash, status, last_seen, created_at, is_admin, stars)
        VALUES (%s, %s, %s, %s, 'online', %s, %s, FALSE, 0) RETURNING id
    """, (phone, username, display_name, pwd_hash, ts, ts))
    user_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET status = 'online', last_seen = %s WHERE id = %s", (int(time.time()), user['id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({
        'status': 'ok',
        'user': {
            'id': user['id'],
            'username': user['username'],
            'display_name': user['display_name'],
            'is_admin': user['is_admin'],
            'stars': user['stars']
        }
    })

@app.route('/api/logout', methods=['POST'])
@login_required
def logout(user):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET status = 'offline', last_seen = %s WHERE id = %s", (int(time.time()), user['id']))
    conn.commit()
    cur.close()
    conn.close()
    session.clear()
    return jsonify({'status': 'ok'})

@app.route('/api/search', methods=['GET'])
@login_required
def search(user):
    q = request.args.get('q', '')
    conn = get_db_connection()
    cur = conn.cursor()
    if len(q) < 2:
        cur.execute("SELECT id, username, display_name, status, last_seen FROM users WHERE id != %s LIMIT 50", (user['id'],))
    else:
        cur.execute("SELECT id, username, display_name, status, last_seen FROM users WHERE (username ILIKE %s OR display_name ILIKE %s) AND id != %s LIMIT 20",
                    (f'%{q}%', f'%{q}%', user['id']))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    results = [dict(r) for r in rows]
    return jsonify({'results': results})

@app.route('/api/messages/<chat_type>/<int:chat_id>', methods=['GET'])
@login_required
def get_messages(user, chat_type, chat_id):
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, sender_id, content, edited, reactions, timestamp
        FROM messages
        WHERE chat_type = %s AND chat_id = %s
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
    """, (chat_type, chat_id, limit, offset))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    messages = []
    for r in rows:
        msg = dict(r)
        msg['reactions'] = json.loads(msg.get('reactions', '{}'))
        messages.append(msg)
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
    elif chat_type == 'group':
        socketio.emit('new_group_message', {
            'group_id': chat_id,
            'from': user['id'],
            'message': content,
            'message_id': msg_id,
            'timestamp': ts
        }, room=f'group_{chat_id}')
    elif chat_type == 'channel':
        # Проверка, что пользователь – создатель канала (упрощённо)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT creator_id FROM channels WHERE id = %s", (chat_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row['creator_id'] == user['id']:
            socketio.emit('new_channel_post', {
                'channel_id': chat_id,
                'from': user['id'],
                'message': content,
                'message_id': msg_id,
                'timestamp': ts
            }, room=f'channel_{chat_id}')
        else:
            return jsonify({'error': 'Not allowed'}), 403
    return jsonify({'message_id': msg_id, 'timestamp': ts})

# -------------------- WebSocket --------------------
@socketio.on('register')
def on_register():
    user_id = session.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')

@socketio.on('join_group')
def on_join_group(data):
    user_id = session.get('user_id')
    if user_id:
        join_room(f'group_{data["group_id"]}')

@socketio.on('join_channel')
def on_join_channel(data):
    user_id = session.get('user_id')
    if user_id:
        join_room(f'channel_{data["channel_id"]}')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)