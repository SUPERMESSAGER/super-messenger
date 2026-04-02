#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
import secrets
import time
import re
import random
import threading
import shutil
from functools import wraps
from flask import Flask, request, jsonify, session, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------- База данных ----------
DB_PATH = 'alex_users.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT,
        password_hash TEXT NOT NULL,
        plain_password TEXT,
        is_admin INTEGER DEFAULT 0,
        is_super_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        created_at INTEGER,
        show_crown INTEGER DEFAULT 1
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id INTEGER,
        to_id INTEGER,
        content TEXT,
        file_path TEXT,
        file_expires INTEGER,
        timestamp INTEGER,
        read INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS registration_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        display_name TEXT,
        plain_password TEXT,
        password_hash TEXT,
        created_at INTEGER
    )''')
    # Предустановленные пользователи
    users_to_add = [
        ('123', '123', '123', 1, 1),
        ('321', '321', '321', 0, 0),
        ('sanya_play', 'Александр Журба', '3590', 1, 1),
        ('test1', 'Тест 1', 'test1', 0, 0),
        ('test2', 'Тест 2', 'test2', 0, 0)
    ]
    for username, display_name, password, is_admin, is_super_admin in users_to_add:
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        if not c.fetchone():
            pwd_hash = generate_password_hash(password)
            c.execute("INSERT INTO users (username, display_name, password_hash, plain_password, is_admin, is_super_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (username, display_name, pwd_hash, password, is_admin, is_super_admin, int(time.time())))
    conn.commit()
    conn.close()

init_db()

# ---------- Функции БД ----------
def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, password_hash, plain_password, is_admin, is_super_admin, is_banned, show_crown FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2], 'password_hash': row[3], 'plain_password': row[4],
                'is_admin': bool(row[5]), 'is_super_admin': bool(row[6]), 'is_banned': bool(row[7]), 'show_crown': bool(row[8])}
    return None

def get_user_by_id(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, is_admin, is_super_admin, is_banned, show_crown FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2],
                'is_admin': bool(row[3]), 'is_super_admin': bool(row[4]), 'is_banned': bool(row[5]), 'show_crown': bool(row[6])}
    return None

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, is_admin, is_super_admin, is_banned, created_at FROM users")
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'username': r[1], 'display_name': r[2], 'is_admin': bool(r[3]), 'is_super_admin': bool(r[4]), 'is_banned': bool(r[5]), 'created_at': r[6]} for r in rows]

def save_message(from_id, to_id, content, file_path=None, file_expires=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = int(time.time())
    c.execute("INSERT INTO messages (from_id, to_id, content, file_path, file_expires, timestamp, read) VALUES (?, ?, ?, ?, ?, ?, 0)",
              (from_id, to_id, content, file_path, file_expires, ts))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id, ts

def get_messages_between(user1_id, user2_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, from_id, to_id, content, file_path, file_expires, timestamp, read FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?) ORDER BY timestamp ASC",
              (user1_id, user2_id, user2_id, user1_id))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'from_id': r[1], 'to_id': r[2], 'content': r[3], 'file_path': r[4], 'file_expires': r[5], 'timestamp': r[6], 'read': r[7]} for r in rows]

def mark_messages_read(user_id, other_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE messages SET read = 1 WHERE to_id = ? AND from_id = ?", (user_id, other_id))
    conn.commit()
    conn.close()

def get_unread_counts(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT from_id, COUNT(*) FROM messages WHERE to_id = ? AND read = 0 GROUP BY from_id", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def get_total_unread(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM messages WHERE to_id = ? AND read = 0", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_all_messages():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, from_id, to_id, content, timestamp FROM messages ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    # Фильтруем сообщения ботов test1 и test2, чтобы они не отображались в админке
    test_users = get_user_by_username('test1'), get_user_by_username('test2')
    test_ids = [u['id'] for u in test_users if u]
    return [{'id': r[0], 'from_id': r[1], 'to_id': r[2], 'content': r[3], 'timestamp': r[4]} for r in rows if r[1] not in test_ids and r[2] not in test_ids]

def add_registration_request(username, display_name, plain_password, password_hash):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO registration_requests (username, display_name, plain_password, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
              (username, display_name, plain_password, password_hash, int(time.time())))
    conn.commit()
    conn.close()

def get_registration_requests():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, display_name, plain_password, created_at FROM registration_requests ORDER BY created_at ASC")
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'username': r[1], 'display_name': r[2], 'plain_password': r[3], 'created_at': r[4]} for r in rows]

def delete_registration_request(req_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM registration_requests WHERE id = ?", (req_id,))
    conn.commit()
    conn.close()

def ban_user(user_id, ban=True, admin_user=None):
    target = get_user_by_id(user_id)
    if target and target.get('is_super_admin'):
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = ? WHERE id = ?", (1 if ban else 0, user_id))
    conn.commit()
    conn.close()
    return True

def set_admin(user_id, admin=True, admin_user=None):
    target = get_user_by_id(user_id)
    if target and target.get('is_super_admin'):
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if admin else 0, user_id))
    conn.commit()
    conn.close()
    return True

def set_show_crown(user_id, show=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET show_crown = ? WHERE id = ?", (1 if show else 0, user_id))
    conn.commit()
    conn.close()

def delete_expired_files():
    while True:
        time.sleep(30)
        now = int(time.time())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, file_path FROM messages WHERE file_path IS NOT NULL AND file_expires < ?", (now,))
        expired = c.fetchall()
        for msg_id, file_path in expired:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            c.execute("UPDATE messages SET file_path = NULL, file_expires = NULL WHERE id = ?", (msg_id,))
        conn.commit()
        conn.close()

threading.Thread(target=delete_expired_files, daemon=True).start()

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
        if not user.get('is_admin'):
            return jsonify({'error': 'Admin rights required'}), 403
        return f(user=user, *args, **kwargs)
    return decorated

# ---------- Фоновый поток ботов ----------
def bot_worker():
    while True:
        time.sleep(10)
        user1 = get_user_by_username('test1')
        user2 = get_user_by_username('test2')
        if user1 and user2 and not user1.get('is_banned') and not user2.get('is_banned'):
            messages = ['Привет!', 'Как дела?', 'Что нового?', 'Отличный день!', 'Пока!', 'Созвон?', '👍', '😀']
            msg = random.choice(messages)
            save_message(user1['id'], user2['id'], msg)
            save_message(user2['id'], user1['id'], random.choice(messages))

threading.Thread(target=bot_worker, daemon=True).start()

# ---------- HTML интерфейс ----------
@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>ALEX — мессенджер</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background:#0a0a0f; color:#f0f0f5; font-family:system-ui; height:100vh; overflow:hidden; }
        .app { display:flex; flex-direction:column; height:100vh; width:100vw; }
        .header { background:#16161d; padding:12px 20px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #2a2a33; flex-shrink:0; }
        .logo { font-size:1.5rem; font-weight:700; background:linear-gradient(135deg,#5e9bff,#b77cff); -webkit-background-clip:text; background-clip:text; color:transparent; }
        .btn-icon { background:#22222c; border:none; color:#f0f0f5; padding:8px 16px; border-radius:30px; cursor:pointer; font-size:0.9rem; position:relative; }
        .btn-icon .unread-dot { position:absolute; top:-2px; right:-2px; width:10px; height:10px; background:#5e9bff; border-radius:50%; }
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
        .dialog-item { padding:12px 16px; border-bottom:1px solid #2a2a33; cursor:pointer; display:flex; justify-content:space-between; align-items:center; }
        .dialog-item:hover { background:#22222c; }
        .dialog-name { font-weight:600; }
        .admin-badge { color:gold; margin-left:5px; font-size:0.8rem; }
        .unread-dot { width:10px; height:10px; background:#5e9bff; border-radius:50%; display:inline-block; margin-left:8px; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:75%; padding:8px 12px; border-radius:18px; background:#22222c; align-self:flex-start; word-wrap:break-word; }
        .message.own { background:#5e9bff; align-self:flex-end; }
        .message .text { font-size:0.95rem; }
        .message .time { font-size:0.6rem; text-align:right; margin-top:4px; opacity:0.6; }
        .message .file-image { max-width:200px; max-height:200px; border-radius:12px; cursor:pointer; margin-top:8px; }
        .message .timer { font-size:0.7rem; color:#aaa; margin-left:8px; }
        .input-bar { padding:12px; background:#16161d; border-top:1px solid #2a2a33; display:flex; gap:10px; flex-shrink:0; margin-bottom:10px; padding-bottom:calc(12px + env(safe-area-inset-bottom, 0px)); }
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
    <div id="authScreen"><div class="auth-container"><h2>Вход в ALEX</h2><input type="text" id="loginUsername" placeholder="Username"><input type="password" id="loginPassword" placeholder="Пароль"><button id="loginBtn">Войти</button><button id="showRegisterBtn" class="btn-outline">Регистрация</button></div><div id="registerForm" class="hidden auth-container"><h2>Регистрация (заявка)</h2><input type="text" id="regUsername" placeholder="Username (латиница, 4-32)"><input type="text" id="regDisplayName" placeholder="Как вас называть"><input type="password" id="regPassword" placeholder="Пароль"><button id="doRegisterBtn">Отправить заявку</button><button id="backToLoginBtn" class="btn-outline">Назад</button></div></div>
    <div id="mainScreen" class="hidden" style="flex:1; display:flex; flex-direction:column; min-height:0;"><div class="main-layout"><div class="sidebar" id="sidebar"><div class="search-bar"><input type="text" id="searchInput" placeholder="Поиск @username"><button id="searchBtn" style="margin-top:8px;">Найти</button></div><div id="dialogsList" style="flex:1; overflow-y:auto;"></div></div><div class="chat-area"><div id="chatHeader" class="contact-info hidden"></div><div class="messages-area" id="messagesArea"></div><div class="input-bar" id="inputBar" style="display:none;"><input type="text" id="messageInput" placeholder="Сообщение..."><button id="attachBtn" style="width:auto;">📎</button><button id="sendMsgBtn">Отправить</button></div></div></div></div>
</div>
<script>
let currentUser=null,currentChatUser=null,dialogs=[],pollingInterval=null,unreadTotal=0;
const authScreen=document.getElementById('authScreen'),mainScreen=document.getElementById('mainScreen');
const loginBtn=document.getElementById('loginBtn'),logoutBtn=document.getElementById('logoutBtn'),showRegisterBtn=document.getElementById('showRegisterBtn');
const registerForm=document.getElementById('registerForm'),backToLoginBtn=document.getElementById('backToLoginBtn'),doRegisterBtn=document.getElementById('doRegisterBtn');
const searchInput=document.getElementById('searchInput'),searchBtn=document.getElementById('searchBtn'),dialogsList=document.getElementById('dialogsList');
const chatHeader=document.getElementById('chatHeader'),messagesArea=document.getElementById('messagesArea'),inputBar=document.getElementById('inputBar');
const messageInput=document.getElementById('messageInput'),sendMsgBtn=document.getElementById('sendMsgBtn'),menuToggle=document.getElementById('menuToggle'),adminBtn=document.getElementById('adminBtn'),attachBtn=document.getElementById('attachBtn');
let unreadMap={};

function showToast(m){let t=document.createElement('div');t.innerText=m;t.style.position='fixed';t.style.bottom='20px';t.style.left='20px';t.style.right='20px';t.style.background='#333';t.style.color='#fff';t.style.padding='12px';t.style.borderRadius='30px';t.style.textAlign='center';t.style.zIndex='9999';document.body.appendChild(t);setTimeout(()=>t.remove(),2000);}
function escapeHtml(s){return s.replace(/[&<>]/g,function(m){if(m==='&')return '&amp;';if(m==='<')return '&lt;';if(m==='>')return '&gt;';return m;});}
function saveMessagesToCache(u,o,m){localStorage.setItem(`alex_msgs_${u}_${o}`,JSON.stringify(m));}
function loadMessagesFromCache(u,o){let raw=localStorage.getItem(`alex_msgs_${u}_${o}`);return raw?JSON.parse(raw):[];}
async function fetchMessagesFromServer(otherId){let r=await fetch(`/api/messages?with=${otherId}`);if(r.ok){let d=await r.json();return d.messages||[];}return[];}
function renderMessages(msgs){messagesArea.innerHTML='';msgs.forEach(msg=>{let isOwn=(msg.from_id===currentUser.id);let div=document.createElement('div');div.className=`message ${isOwn?'own':''}`;let contentHtml=`<div class="text">${escapeHtml(msg.content||'')}</div>`;if(msg.file_path){let timerText='';if(msg.file_expires){let remaining=Math.max(0,msg.file_expires-Math.floor(Date.now()/1000));timerText=` <span class="timer">(удалится через ${remaining}с)</span>`;setInterval(()=>{let newRemaining=Math.max(0,msg.file_expires-Math.floor(Date.now()/1000));if(newRemaining<=0)div.remove();else div.querySelector('.timer').innerText=`(удалится через ${newRemaining}с)`;},1000);}contentHtml=`<img src="/uploads/${msg.file_path}" class="file-image" onclick="window.open('/uploads/${msg.file_path}','_blank')"><div class="time">${new Date(msg.timestamp*1000).toLocaleTimeString()}${timerText}</div>`;}else{contentHtml+=`<div class="time">${new Date(msg.timestamp*1000).toLocaleTimeString()}</div>`;}div.innerHTML=contentHtml;messagesArea.appendChild(div);});messagesArea.scrollTop=messagesArea.scrollHeight;}
async function openChat(user){if(currentChatUser&&currentChatUser.id===user.id)return;currentChatUser=user;chatHeader.innerHTML=`<strong>${escapeHtml(user.display_name||user.username)}${(user.is_admin && currentUser.show_crown)?' 👑':''}</strong> <span>@${user.username}</span>`;chatHeader.classList.remove('hidden');inputBar.style.display='flex';let serverMsgs=await fetchMessagesFromServer(user.id);saveMessagesToCache(currentUser.id,user.id,serverMsgs);renderMessages(serverMsgs);startPolling(user.id);await fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({with_id:user.id})});await loadDialogs();}
async function sendMessage(content){if(!currentChatUser)return;let r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_username:currentChatUser.username,content:content})});if(r.ok){messageInput.value='';await loadDialogs();}else showToast('Ошибка');}
async function uploadFile(file){if(!currentChatUser)return;let formData=new FormData();formData.append('file',file);let xhr=new XMLHttpRequest();xhr.open('POST','/api/upload');xhr.onload=()=>{if(xhr.status===200){let data=JSON.parse(xhr.responseText);if(data.file_path){showToast('Файл загружен');loadMessages(currentChatUser.id);}}else showToast('Ошибка загрузки');};xhr.send(formData);}
function startPolling(otherId){if(pollingInterval)clearInterval(pollingInterval);pollingInterval=setInterval(async()=>{if(currentChatUser&&currentChatUser.id===otherId){let serverMsgs=await fetchMessagesFromServer(otherId);saveMessagesToCache(currentUser.id,otherId,serverMsgs);renderMessages(serverMsgs);}await loadDialogs();},5000);}
async function loadDialogs(){let r=await fetch('/api/dialogs');if(r.ok){let data=await r.json();dialogs=data.dialogs;let unread=await fetch('/api/unread').then(r=>r.json());unreadMap=unread;unreadTotal=await fetch('/api/unread_total').then(r=>r.json()).then(d=>d.total);renderDialogs();let chatsBtn=document.getElementById('menuToggle');if(unreadTotal>0)chatsBtn.style.position='relative';else chatsBtn.style.position='';}}
function renderDialogs(){if(!dialogs.length){dialogsList.innerHTML='<div style="padding:12px; color:#aaa;">Нет диалогов</div>';return;}dialogsList.innerHTML='';dialogs.forEach(d=>{let div=document.createElement('div');div.className='dialog-item';let unreadHtml=unreadMap[d.id]?`<span class="unread-dot"></span>`:'';let crownHtml=(d.is_admin && d.show_crown)?'<span class="admin-badge">👑</span>':'';div.innerHTML=`<div><span class="dialog-name">${escapeHtml(d.display_name||d.username)}</span>${crownHtml}<div style="font-size:0.7rem;">@${d.username}</div></div>${unreadHtml}`;div.onclick=()=>openChat(d);dialogsList.appendChild(div);});let chatsBtn=document.getElementById('menuToggle');if(unreadTotal>0){if(!chatsBtn.querySelector('.unread-dot')){let dot=document.createElement('span');dot.className='unread-dot';chatsBtn.appendChild(dot);}}else{let dot=chatsBtn.querySelector('.unread-dot');if(dot)dot.remove();}}
async function searchUser(username){if(!username.startsWith('@'))username='@'+username;let clean=username.substring(1);let r=await fetch(`/api/search?q=${encodeURIComponent(clean)}`);let data=await r.json();if(data.user){if(confirm(`Начать чат с ${data.user.display_name||data.user.username}?`)){if(!dialogs.some(d=>d.id===data.user.id)){dialogs.unshift(data.user);renderDialogs();}openChat(data.user);}}else showToast('Пользователь не найден');}
async function openAdminPanel(){let users=await(await fetch('/api/admin/users')).json();let allMessages=await(await fetch('/api/admin/messages')).json();let requests=await(await fetch('/api/admin/requests')).json();let html=`<div class="admin-panel"><div class="admin-panel-content"><h3>Админ-панель</h3><button id="selfCrownToggle">${currentUser.show_crown?'Скрыть корону':'Показать корону'}</button><hr><h4>Пользователи</h4><table><tr><th>ID</th><th>Username</th><th>Имя</th><th>Админ</th><th>Бан</th><th>Действия</th></tr>`;for(let u of users){html+=`<tr><td>${u.id}</td><td>${escapeHtml(u.username)}</td><td>${escapeHtml(u.display_name)}</td><td>${u.is_admin?'✅':'❌'}</td><td>${u.is_banned?'🔴':'🟢'}</td><td>${!u.is_super_admin?`<button class="setAdminBtn" data-id="${u.id}" data-admin="${!u.is_admin}">${u.is_admin?'Снять админа':'Назначить админа'}</button><button class="banBtn" data-id="${u.id}" data-ban="${!u.is_banned}">${u.is_banned?'Разбанить':'Забанить'}</button>`:'<i>Суперадмин</i>'}</td></tr>`;}html+=`</table><hr><h4>Заявки</h4><table><tr><th>Username</th><th>Имя</th><th>Дата</th><th>Действие</th></tr>`;for(let r of requests){html+=`<tr><td>${escapeHtml(r.username)}</td><td>${escapeHtml(r.display_name)}</td><td>${new Date(r.created_at*1000).toLocaleString()}</td><td><button class="approveReqBtn" data-username="${escapeHtml(r.username)}" data-display="${escapeHtml(r.display_name)}" data-password="${escapeHtml(r.plain_password)}">✅ Одобрить</button><button class="deleteReqBtn" data-reqid="${r.id}">❌ Отклонить</button></td></tr>`;}html+=`</table><hr><h4>Все сообщения</h4><table><tr><th>От</th><th>Кому</th><th>Текст</th><th>Время</th></tr>`;for(let m of allMessages){let fromUser=users.find(u=>u.id===m.from_id);let toUser=users.find(u=>u.id===m.to_id);html+=`<tr><td>${fromUser?fromUser.username:'?'}</td><td>${toUser?toUser.username:'?'}</td><td>${escapeHtml(m.content)}</td><td>${new Date(m.timestamp*1000).toLocaleString()}</td></tr>`;}html+=`</table><br><button id="closeAdminBtn">Закрыть</button></div></div>`;document.body.insertAdjacentHTML('beforeend',html);document.getElementById('selfCrownToggle').onclick=async()=>{let newShow=!currentUser.show_crown;await fetch('/api/admin/toggle_crown',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({show_crown:newShow})});location.reload();};document.querySelectorAll('.setAdminBtn').forEach(btn=>{btn.onclick=async()=>{let userId=btn.dataset.id,isAdmin=btn.dataset.admin==='true';await fetch('/api/admin/set_admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:parseInt(userId),is_admin:isAdmin})});location.reload();};});document.querySelectorAll('.banBtn').forEach(btn=>{btn.onclick=async()=>{let userId=btn.dataset.id,ban=btn.dataset.ban==='true';await fetch('/api/admin/ban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:parseInt(userId),ban:ban})});location.reload();};});document.querySelectorAll('.approveReqBtn').forEach(btn=>{btn.onclick=async()=>{let username=btn.dataset.username,display=btn.dataset.display,password=btn.dataset.password;await fetch('/api/admin/approve_request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,display_name:display,plain_password:password})});document.querySelector('.admin-panel').remove();openAdminPanel();};});document.querySelectorAll('.deleteReqBtn').forEach(btn=>{btn.onclick=async()=>{await fetch('/api/admin/delete_request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:parseInt(btn.dataset.reqid)})});document.querySelector('.admin-panel').remove();openAdminPanel();};});document.getElementById('closeAdminBtn').onclick=()=>document.querySelector('.admin-panel').remove();}
async function afterLogin(user){currentUser=user;sessionStorage.setItem('alex_user',JSON.stringify(user));authScreen.classList.add('hidden');mainScreen.classList.remove('hidden');logoutBtn.style.display='inline-block';menuToggle.style.display='inline-block';if(user.is_admin)adminBtn.style.display='inline-block';await loadDialogs();if(dialogs.length>0)openChat(dialogs[0]);menuToggle.onclick=()=>document.getElementById('sidebar').classList.toggle('open');adminBtn.onclick=openAdminPanel;}
doRegisterBtn.onclick=async()=>{let username=document.getElementById('regUsername').value.trim(),display_name=document.getElementById('regDisplayName').value.trim()||username,password=document.getElementById('regPassword').value;if(!username||!password){showToast('Заполните все поля');return;}if(!/^[a-zA-Z0-9_]{4,32}$/.test(username)){showToast('Username 4-32 буквы/цифры/_');return;}let r=await fetch('/api/request_register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,display_name,password})});let data=await r.json();if(r.ok){showToast('Заявка отправлена');backToLoginBtn.click();}else showToast(data.error);};
loginBtn.onclick=async()=>{let username=document.getElementById('loginUsername').value.trim(),password=document.getElementById('loginPassword').value;if(!username||!password){showToast('Введите username и пароль');return;}let r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});let data=await r.json();if(r.ok)await afterLogin(data.user);else showToast(data.error);};
logoutBtn.onclick=async()=>{await fetch('/api/logout',{method:'POST'});if(pollingInterval)clearInterval(pollingInterval);sessionStorage.clear();location.reload();};
showRegisterBtn.onclick=()=>{document.querySelector('.auth-container').classList.add('hidden');registerForm.classList.remove('hidden');};
backToLoginBtn.onclick=()=>{registerForm.classList.add('hidden');document.querySelector('.auth-container').classList.remove('hidden');};
searchBtn.onclick=()=>{let q=searchInput.value.trim();if(q)searchUser(q);};
searchInput.addEventListener('keypress',(e)=>{if(e.key==='Enter')searchBtn.click();});
sendMsgBtn.onclick=()=>{let content=messageInput.value.trim();if(content&&currentChatUser)sendMessage(content);};
messageInput.addEventListener('keypress',(e)=>{if(e.key==='Enter')sendMsgBtn.click();});
attachBtn.onclick=()=>{let input=document.createElement('input');input.type='file';input.accept='image/*';input.onchange=e=>{if(e.target.files[0])uploadFile(e.target.files[0]);};input.click();};
let saved=sessionStorage.getItem('alex_user');if(saved){let user=JSON.parse(saved);afterLogin(user);}
</script>
</body>
</html>'''

# ---------- API маршруты ----------
@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file(user):
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    filename = secure_filename(f"{int(time.time())}_{secrets.token_hex(8)}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    expires = int(time.time()) + 300  # 5 минут
    # Сохраняем в БД как сообщение
    if not currentChatUser:
        return jsonify({'error': 'No chat selected'}), 400
    save_message(user['id'], currentChatUser['id'], '', file_path=filename, file_expires=expires)
    return jsonify({'file_path': filename, 'expires': expires})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/api/request_register', methods=['POST'])
def request_register():
    data = request.json
    username, display_name, password = data.get('username'), data.get('display_name', username), data.get('password')
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
    add_registration_request(username, display_name, password, pwd_hash)
    return jsonify({'status': 'ok'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username, password = data.get('username'), data.get('password')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    user = get_user_by_username(username)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401
    if user['is_banned']:
        return jsonify({'error': 'You are banned'}), 403
    session['user_id'] = user['id']
    return jsonify({'status': 'ok', 'user': {'id': user['id'], 'username': user['username'], 'display_name': user['display_name'], 'is_admin': user['is_admin'], 'show_crown': user['show_crown']}})

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
    to_username, content = data.get('to_username'), data.get('content')
    if not to_username or not content:
        return jsonify({'error': 'Missing parameters'}), 400
    to_user = get_user_by_username(to_username)
    if not to_user:
        return jsonify({'error': 'Recipient not found'}), 404
    if to_user['is_banned']:
        return jsonify({'error': 'Recipient is banned'}), 403
    save_message(user['id'], to_user['id'], content)
    return jsonify({'status': 'ok', 'timestamp': int(time.time())})

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
            dialogs_list.append({'id': u['id'], 'username': u['username'], 'display_name': u['display_name'], 'is_admin': u['is_admin'], 'show_crown': u['show_crown']})
    dialogs_list.sort(key=lambda d: max((msg['timestamp'] for msg in get_messages_between(user['id'], d['id'])), default=0), reverse=True)
    return jsonify({'dialogs': dialogs_list})

@app.route('/api/unread', methods=['GET'])
@login_required
def unread(user):
    return jsonify(get_unread_counts(user['id']))

@app.route('/api/unread_total', methods=['GET'])
@login_required
def unread_total(user):
    return jsonify({'total': get_total_unread(user['id'])})

@app.route('/api/mark_read', methods=['POST'])
@login_required
def mark_read(user):
    data = request.json
    with_id = data.get('with_id')
    if with_id:
        mark_messages_read(user['id'], with_id)
    return jsonify({'status': 'ok'})

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

@app.route('/api/admin/approve_request', methods=['POST'])
@login_required
@admin_required
def admin_approve_request(user):
    data = request.json
    username = data.get('username')
    display_name = data.get('display_name', username)
    plain_password = data.get('plain_password')
    if not username or not plain_password:
        return jsonify({'error': 'Missing data'}), 400
    if get_user_by_username(username):
        return jsonify({'error': 'User already exists'}), 409
    pwd_hash = generate_password_hash(plain_password)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO users (username, display_name, password_hash, plain_password, created_at) VALUES (?, ?, ?, ?, ?)",
              (username, display_name, pwd_hash, plain_password, int(time.time())))
    c.execute("DELETE FROM registration_requests WHERE username = ?", (username,))
    conn.commit()
    conn.close()
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
    if set_admin(target_id, is_admin, admin_user=user):
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Cannot change superadmin'}), 403

@app.route('/api/admin/ban', methods=['POST'])
@login_required
@admin_required
def admin_ban(user):
    data = request.json
    target_id = data.get('user_id')
    ban = data.get('ban', True)
    if not target_id:
        return jsonify({'error': 'Missing user_id'}), 400
    if ban_user(target_id, ban, admin_user=user):
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Cannot ban superadmin'}), 403

@app.route('/api/admin/toggle_crown', methods=['POST'])
@login_required
def toggle_crown(user):
    if not user['is_admin']:
        return jsonify({'error': 'Only admin can toggle crown'}), 403
    data = request.json
    show_crown = data.get('show_crown', True)
    set_show_crown(user['id'], show_crown)
    session['user_id'] = user['id']
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    from flask import send_from_directory
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)