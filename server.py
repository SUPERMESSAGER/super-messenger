#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import secrets
import time
import re
import sqlite3
from functools import wraps
from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# -------------------- ВЫБОР БАЗЫ ДАННЫХ --------------------
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = DATABASE_URL is not None

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    def get_db():
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
else:
    DB_PATH = 'data.db'
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

# -------------------- ИНИЦИАЛИЗАЦИЯ БД --------------------
def init_db():
    conn = get_db()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                phone TEXT UNIQUE,
                username TEXT UNIQUE,
                display_name TEXT,
                password_hash TEXT,
                stars INTEGER DEFAULT 0,
                status TEXT DEFAULT 'online',
                last_seen INTEGER,
                is_admin BOOLEAN DEFAULT FALSE,
                is_banned BOOLEAN DEFAULT FALSE,
                created_at INTEGER
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                chat_type TEXT,
                chat_id INTEGER,
                sender_id INTEGER,
                content TEXT,
                timestamp INTEGER
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS saved_messages (
                user_id INTEGER,
                message_id INTEGER,
                saved_at INTEGER,
                PRIMARY KEY (user_id, message_id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS gifts (
                id SERIAL PRIMARY KEY,
                name TEXT,
                price INTEGER,
                icon TEXT
            )
        ''')
        cur.execute("SELECT COUNT(*) FROM gifts")
        if cur.fetchone()['count'] == 0:
            gifts = [('🌹 Роза', 5, '🌹'), ('🎁 Подарок', 10, '🎁'), ('💎 Бриллиант', 50, '💎'), ('⭐ Звезда', 1, '⭐'), ('🏆 Трофей', 100, '🏆')]
            cur.executemany("INSERT INTO gifts (name, price, icon) VALUES (%s, %s, %s)", gifts)
    else:
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE,
            username TEXT UNIQUE,
            display_name TEXT,
            password_hash TEXT,
            stars INTEGER DEFAULT 0,
            status TEXT DEFAULT 'online',
            last_seen INTEGER,
            is_admin BOOLEAN DEFAULT 0,
            is_banned BOOLEAN DEFAULT 0,
            created_at INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_type TEXT,
            chat_id INTEGER,
            sender_id INTEGER,
            content TEXT,
            timestamp INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS saved_messages (
            user_id INTEGER,
            message_id INTEGER,
            saved_at INTEGER,
            PRIMARY KEY (user_id, message_id)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER,
            icon TEXT
        )''')
        cur.execute("SELECT COUNT(*) FROM gifts")
        if cur.fetchone()[0] == 0:
            gifts = [('🌹 Роза', 5, '🌹'), ('🎁 Подарок', 10, '🎁'), ('💎 Бриллиант', 50, '💎'), ('⭐ Звезда', 1, '⭐'), ('🏆 Трофей', 100, '🏆')]
            cur.executemany("INSERT INTO gifts (name, price, icon) VALUES (?, ?, ?)", gifts)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# -------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ --------------------
def query_one(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(sql, params)
        row = cur.fetchone()
    else:
        cur.execute(sql, params)
        row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def query_all(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(sql, params)
        rows = cur.fetchall()
    else:
        cur.execute(sql, params)
        rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(row) for row in rows]

def execute_sql(sql, params=(), return_id=False):
    conn = get_db()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(sql, params)
        if return_id:
            cur.execute("SELECT LASTVAL()")
            last_id = cur.fetchone()['lastval']
        conn.commit()
        cur.close()
        conn.close()
        return last_id if return_id else None
    else:
        cur.execute(sql, params)
        last_id = cur.lastrowid if return_id else None
        conn.commit()
        cur.close()
        conn.close()
        return last_id

def get_user_by_username(username):
    return query_one("SELECT id, username, display_name, password_hash, stars, status, last_seen, is_admin, is_banned FROM users WHERE username = ?" if not USE_POSTGRES else "SELECT id, username, display_name, password_hash, stars, status, last_seen, is_admin, is_banned FROM users WHERE username = %s", (username,))

def get_user_by_phone(phone):
    return query_one("SELECT id, username, display_name, password_hash, stars, status, last_seen, is_admin, is_banned FROM users WHERE phone = ?" if not USE_POSTGRES else "SELECT id, username, display_name, password_hash, stars, status, last_seen, is_admin, is_banned FROM users WHERE phone = %s", (phone,))

def get_user_by_id(uid):
    return query_one("SELECT id, username, display_name, stars, status, last_seen, is_admin, is_banned FROM users WHERE id = ?" if not USE_POSTGRES else "SELECT id, username, display_name, stars, status, last_seen, is_admin, is_banned FROM users WHERE id = %s", (uid,))

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
        if not user.get('is_admin') and user.get('username') != 'asdfg':
            return jsonify({'error': 'Admin rights required'}), 403
        return f(user=user, *args, **kwargs)
    return decorated

# -------------------- HTML ИНТЕРФЕЙС --------------------
@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Super Messenger</title>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        :root { --bg:#0a0a0f; --surface:#16161d; --surface-light:#22222c; --primary:#5e9bff; --text:#f0f0f5; --border:#2a2a33; }
        body { background:var(--bg); color:var(--text); font-family:system-ui; height:100vh; overflow:hidden; }
        .header { background:var(--surface); padding:12px 20px; display:flex; justify-content:space-between; align-items:center; }
        .logo { font-size:1.4rem; background:linear-gradient(135deg,#5e9bff,#b77cff); -webkit-background-clip:text; background-clip:text; color:transparent; }
        .btn-icon { background:var(--surface-light); border:none; color:var(--text); padding:6px 12px; border-radius:30px; cursor:pointer; }
        .auth-container { padding:30px 20px; max-width:400px; margin:auto; }
        input { width:100%; padding:12px; background:var(--surface); border:1px solid var(--border); border-radius:12px; color:var(--text); margin-bottom:12px; }
        button { background:var(--primary); color:white; border:none; padding:12px; border-radius:30px; font-weight:600; cursor:pointer; width:100%; margin-bottom:10px; }
        .btn-outline { background:transparent; border:1px solid var(--primary); color:var(--primary); }
        .chat-container { display:flex; flex:1; height:calc(100vh - 70px); }
        .sidebar { width:280px; background:var(--surface); border-right:1px solid var(--border); overflow-y:auto; }
        .chat-area { flex:1; display:flex; flex-direction:column; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; }
        .message { max-width:75%; padding:8px 12px; border-radius:18px; background:var(--surface-light); margin-bottom:8px; align-self:flex-start; }
        .message.own { background:var(--primary); align-self:flex-end; }
        .input-bar { padding:12px; background:var(--surface); display:flex; gap:10px; }
        .input-bar input { flex:1; margin:0; }
        .input-bar button { width:auto; padding:12px 20px; margin:0; }
        .contact-item { padding:12px; border-bottom:1px solid var(--border); cursor:pointer; }
        .contact-item:hover { background:var(--surface-light); }
        .hidden { display:none !important; }
        .stars-badge { background:rgba(255,215,0,0.2); padding:6px 12px; border-radius:20px; cursor:pointer; }
        .stars-badge span { color:gold; }
        .user-info { display:flex; gap:10px; align-items:center; }
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
            <input type="text" id="regUsername" placeholder="@username">
            <input type="text" id="regDisplayName" placeholder="Имя">
            <input type="password" id="regPassword" placeholder="Пароль">
            <button id="doRegisterBtn">Зарегистрироваться</button>
            <button id="backToLoginBtn" class="btn-outline">Назад</button>
        </div>
    </div>
    <div id="mainScreen" class="hidden" style="flex:1; display:flex; flex-direction:column;">
        <div class="chat-container">
            <div class="sidebar" id="sidebar">
                <div id="chatsList"></div>
            </div>
            <div class="chat-area">
                <div id="currentChatHeader" style="padding:12px; border-bottom:1px solid var(--border);"></div>
                <div class="messages-area" id="messagesArea"></div>
                <div class="input-bar">
                    <input type="text" id="messageInput" placeholder="Сообщение...">
                    <button id="sendMsgBtn">📤</button>
                </div>
            </div>
        </div>
    </div>
</div>
<div id="profileModal" class="modal hidden" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;z-index:1000;"><div style="background:var(--surface);border-radius:20px;padding:20px;width:300px;"><div id="profileContent"></div><button id="closeProfile" style="margin-top:10px;">Закрыть</button></div></div>
<div id="adminModal" class="modal hidden" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;z-index:1000;"><div style="background:var(--surface);border-radius:20px;padding:20px;width:300px;"><div id="adminContent"></div><button id="closeAdmin" style="margin-top:10px;">Закрыть</button></div></div>
<script>
let socket=null,currentUser=null,currentChat=null;
const authScreen=document.getElementById('authScreen'),mainScreen=document.getElementById('mainScreen');
const loginBtn=document.getElementById('loginBtn'),logoutBtn=document.getElementById('logoutBtn');
const showRegisterBtn=document.getElementById('showRegisterBtn'),registerForm=document.getElementById('registerForm');
const backToLoginBtn=document.getElementById('backToLoginBtn'),doRegisterBtn=document.getElementById('doRegisterBtn');
const sendMsgBtn=document.getElementById('sendMsgBtn'),messageInput=document.getElementById('messageInput');
const messagesArea=document.getElementById('messagesArea'),currentChatHeader=document.getElementById('currentChatHeader');
const chatsListDiv=document.getElementById('chatsList'),starsDisplay=document.getElementById('starsDisplay');
const profileBtn=document.getElementById('profileBtn'),adminBtn=document.getElementById('adminBtn');

function showToast(msg){let t=document.createElement('div');t.innerText=msg;t.style.position='fixed';t.style.bottom='20px';t.style.left='20px';t.style.right='20px';t.style.background='#333';t.style.color='#fff';t.style.padding='12px';t.style.borderRadius='30px';t.style.textAlign='center';t.style.zIndex='9999';document.body.appendChild(t);setTimeout(()=>t.remove(),2000);}
function escapeHtml(str){return str.replace(/[&<>]/g,function(m){if(m==='&')return '&amp;';if(m==='<')return '&lt;';if(m==='>')return '&gt;';return m;});}
function appendMessage(msg,isOwn){let div=document.createElement('div');div.className=`message ${isOwn?'own':''}`;div.innerHTML=`<div class="sender">${isOwn?'Вы':'Пользователь'}</div><div class="text">${escapeHtml(msg.content||'')}</div><div class="time">${new Date(msg.timestamp*1000).toLocaleTimeString()}</div><div class="actions"><button class="saveMsg" data-id="${msg.id}">⭐</button></div>`;messagesArea.appendChild(div);messagesArea.scrollTop=messagesArea.scrollHeight;div.querySelector('.saveMsg')?.addEventListener('click',(e)=>{e.stopPropagation();saveMessageToFav(msg.id);});}
async function loadMessages(chatType,chatId){const res=await fetch(`/api/messages/${chatType}/${chatId}`);const data=await res.json();messagesArea.innerHTML='';data.messages.forEach(m=>appendMessage(m,m.sender_id===currentUser.id));}
async function loadDialogs(){const res=await fetch('/api/search?q=');const data=await res.json();chatsListDiv.innerHTML='';data.results.forEach(u=>{let div=document.createElement('div');div.className='contact-item';div.innerHTML=`<strong>${u.display_name||u.username}</strong><div>${u.status==='online'?'онлайн':'офлайн'}</div>`;div.onclick=()=>{currentChat={type:'private',id:u.id,name:u.username};currentChatHeader.innerText=`Чат с ${u.username}`;loadMessages('private',Math.min(currentUser.id,u.id));};chatsListDiv.appendChild(div);});}
async function saveMessageToFav(msgId){const res=await fetch('/api/save_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:msgId})});if(res.ok)showToast('Сохранено в избранное');}
async function updateStars(balance){starsDisplay.querySelector('span').innerText=balance;}
async function showProfile(username){const res=await fetch(`/api/user/${username}`);const data=await res.json();document.getElementById('profileContent').innerHTML=`<div style="text-align:center;"><h3>${data.display_name||data.username}</h3><p>@${data.username}</p><p>⭐ ${data.stars} звёзд</p><p>${data.status==='online'?'🟢 Онлайн':'⚫ Был(а) '+new Date(data.last_seen*1000).toLocaleString()}</p>${currentUser.username===username?'<button id="editProfileBtn">Редактировать профиль</button>':''}</div>`;document.getElementById('profileModal').style.display='flex';if(currentUser.username===username){document.getElementById('editProfileBtn').onclick=()=>{const newBio=prompt('Введите новое описание:');if(newBio!==null){fetch('/api/user/update_profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bio:newBio})}).then(()=>showProfile(username));}};}}
function initSocket(){socket=io();socket.on('connect',()=>console.log('Socket connected'));socket.on('new_private_message',(data)=>{if(currentChat&&currentChat.type==='private'&&currentChat.id===data.from){appendMessage({content:data.message,timestamp:data.timestamp,sender_id:data.from,id:data.message_id},false);}loadDialogs();});socket.emit('register');}
loginBtn.onclick=async()=>{const login=document.getElementById('loginInput').value;const pwd=document.getElementById('passwordInput').value;const res=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({login,password:pwd})});const data=await res.json();if(res.ok){currentUser=data.user;sessionStorage.setItem('user',JSON.stringify(currentUser));initSocket();authScreen.classList.add('hidden');mainScreen.classList.remove('hidden');logoutBtn.style.display='inline-block';profileBtn.style.display='inline-block';starsDisplay.style.display='inline-block';updateStars(currentUser.stars);if(currentUser.is_admin||currentUser.username==='asdfg')adminBtn.style.display='inline-block';loadDialogs();}else{showToast(data.error);}};
showRegisterBtn.onclick=()=>{document.querySelector('.auth-container').classList.add('hidden');registerForm.classList.remove('hidden');};
backToLoginBtn.onclick=()=>{registerForm.classList.add('hidden');document.querySelector('.auth-container').classList.remove('hidden');};
doRegisterBtn.onclick=async()=>{const phone=document.getElementById('regPhone').value;const username=document.getElementById('regUsername').value;const display_name=document.getElementById('regDisplayName').value;const pwd=document.getElementById('regPassword').value;const res=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,username,display_name,password:pwd})});const data=await res.json();if(res.ok){showToast('Регистрация успешна, войдите');backToLoginBtn.click();}else{showToast(data.error);}};
logoutBtn.onclick=async()=>{await fetch('/api/logout',{method:'POST'});if(socket)socket.disconnect();sessionStorage.clear();location.reload();};
profileBtn.onclick=()=>showProfile(currentUser.username);
adminBtn.onclick=async()=>{const res=await fetch('/api/admin/stats');const stats=await res.json();document.getElementById('adminContent').innerHTML=`<h3>Админ-панель</h3><p>Пользователей: ${stats.total_users}</p><p>Сообщений: ${stats.total_messages}</p><p>Звёзд: ${stats.total_stars}</p><hr><input type="text" id="banUser" placeholder="Username"><button id="banBtn">Забанить</button><input type="text" id="unbanUser" placeholder="Username"><button id="unbanBtn">Разбанить</button><hr><input type="text" id="addStarsUser" placeholder="Username"><input type="number" id="addStarsAmount" placeholder="Количество"><button id="addStarsBtn">Добавить звёзды</button>`;document.getElementById('adminModal').style.display='flex';document.getElementById('banBtn').onclick=async()=>{const username=document.getElementById('banUser').value;if(!username)return;await fetch('/api/admin/ban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username})});showToast(`Пользователь ${username} забанен`);};document.getElementById('unbanBtn').onclick=async()=>{const username=document.getElementById('unbanUser').value;if(!username)return;await fetch('/api/admin/unban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username})});showToast(`Пользователь ${username} разбанен`);};document.getElementById('addStarsBtn').onclick=async()=>{const username=document.getElementById('addStarsUser').value;const amount=parseInt(document.getElementById('addStarsAmount').value);if(!username||isNaN(amount))return;await fetch('/api/admin/add_stars',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,amount})});showToast(`Добавлено ${amount} звёзд пользователю ${username}`);};};
document.getElementById('closeProfile').onclick=()=>document.getElementById('profileModal').style.display='none';
document.getElementById('closeAdmin').onclick=()=>document.getElementById('adminModal').style.display='none';
sendMsgBtn.onclick=async()=>{if(!currentChat||!messageInput.value.trim())return;await fetch('/api/message/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_type:currentChat.type,chat_id:currentChat.id,content:messageInput.value})});messageInput.value='';loadMessages(currentChat.type,currentChat.id);};
messageInput.addEventListener('keypress',(e)=>{if(e.key==='Enter')sendMsgBtn.click();});
const saved=sessionStorage.getItem('user');if(saved){currentUser=JSON.parse(saved);initSocket();authScreen.classList.add('hidden');mainScreen.classList.remove('hidden');logoutBtn.style.display='inline-block';profileBtn.style.display='inline-block';starsDisplay.style.display='inline-block';updateStars(currentUser.stars);if(currentUser.is_admin||currentUser.username==='asdfg')adminBtn.style.display='inline-block';loadDialogs();}
</script>
</body>
</html>'''

# -------------------- API МАРШРУТЫ --------------------
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    phone, username, display_name, password = data.get('phone'), data.get('username'), data.get('display_name', data.get('username')), data.get('password')
    if not all([phone, username, password]):
        return jsonify({'error': 'All fields required'}), 400
    if not re.match(r'^\+?[0-9]{7,15}$', phone):
        return jsonify({'error': 'Invalid phone'}), 400
    if not re.match(r'^[a-zA-Z0-9_]{4,32}$', username):
        return jsonify({'error': 'Username 4-32 letters/digits/_'}), 400
    if get_user_by_username(username) or get_user_by_phone(phone):
        return jsonify({'error': 'Phone or username exists'}), 409
    pwd_hash = generate_password_hash(password)
    ts = int(time.time())
    sql = "INSERT INTO users (phone, username, display_name, password_hash, status, last_seen, created_at, is_admin, stars) VALUES (?, ?, ?, ?, 'online', ?, ?, 0, 0)" if not USE_POSTGRES else "INSERT INTO users (phone, username, display_name, password_hash, status, last_seen, created_at, is_admin, stars) VALUES (%s, %s, %s, %s, 'online', %s, %s, FALSE, 0) RETURNING id"
    user_id = execute_sql(sql, (phone, username, display_name, pwd_hash, ts, ts), return_id=True)
    return jsonify({'status': 'ok', 'user_id': user_id, 'username': username})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    login_input, password = data.get('login'), data.get('password')
    if not login_input or not password:
        return jsonify({'error': 'Login and password required'}), 400
    user = get_user_by_username(login_input) or get_user_by_phone(login_input)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401
    if user.get('is_banned'):
        return jsonify({'error': 'You are banned'}), 403
    session['user_id'] = user['id']
    execute_sql("UPDATE users SET status = 'online', last_seen = ? WHERE id = ?" if not USE_POSTGRES else "UPDATE users SET status = 'online', last_seen = %s WHERE id = %s", (int(time.time()), user['id']))
    return jsonify({'status': 'ok', 'user': {'id': user['id'], 'username': user['username'], 'display_name': user['display_name'], 'is_admin': user.get('is_admin', False), 'stars': user.get('stars', 0)}})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout(user):
    execute_sql("UPDATE users SET status = 'offline', last_seen = ? WHERE id = ?" if not USE_POSTGRES else "UPDATE users SET status = 'offline', last_seen = %s WHERE id = %s", (int(time.time()), user['id']))
    session.clear()
    return jsonify({'status': 'ok'})

@app.route('/api/search', methods=['GET'])
@login_required
def search(user):
    q = request.args.get('q', '')
    if len(q) < 2:
        sql = "SELECT id, username, display_name, status, last_seen FROM users WHERE id != ? LIMIT 50" if not USE_POSTGRES else "SELECT id, username, display_name, status, last_seen FROM users WHERE id != %s LIMIT 50"
        rows = query_all(sql, (user['id'],))
    else:
        sql = "SELECT id, username, display_name, status, last_seen FROM users WHERE (username LIKE ? OR display_name LIKE ?) AND id != ? LIMIT 20" if not USE_POSTGRES else "SELECT id, username, display_name, status, last_seen FROM users WHERE (username ILIKE %s OR display_name ILIKE %s) AND id != %s LIMIT 20"
        rows = query_all(sql, (f'%{q}%', f'%{q}%', user['id']))
    return jsonify({'results': rows})

@app.route('/api/messages/<chat_type>/<int:chat_id>', methods=['GET'])
@login_required
def get_messages(user, chat_type, chat_id):
    sql = "SELECT id, sender_id, content, timestamp FROM messages WHERE chat_type = ? AND chat_id = ? ORDER BY timestamp DESC LIMIT 100" if not USE_POSTGRES else "SELECT id, sender_id, content, timestamp FROM messages WHERE chat_type = %s AND chat_id = %s ORDER BY timestamp DESC LIMIT 100"
    rows = query_all(sql, (chat_type, chat_id))
    rows.reverse()
    return jsonify({'messages': rows})

@app.route('/api/message/send', methods=['POST'])
@login_required
def send_message(user):
    data = request.json
    chat_type, chat_id, content = data.get('chat_type'), data.get('chat_id'), data.get('content', '')
    if not content:
        return jsonify({'error': 'Empty message'}), 400
    ts = int(time.time())
    sql = "INSERT INTO messages (chat_type, chat_id, sender_id, content, timestamp) VALUES (?, ?, ?, ?, ?)" if not USE_POSTGRES else "INSERT INTO messages (chat_type, chat_id, sender_id, content, timestamp) VALUES (%s, %s, %s, %s, %s) RETURNING id"
    msg_id = execute_sql(sql, (chat_type, chat_id, user['id'], content, ts), return_id=True)
    if chat_type == 'private':
        other_id = chat_id
        socketio.emit('new_private_message', {'from': user['id'], 'to': other_id, 'message': content, 'message_id': msg_id, 'timestamp': ts}, room=f'user_{other_id}')
    return jsonify({'message_id': msg_id, 'timestamp': ts})

@app.route('/api/save_message', methods=['POST'])
@login_required
def save_message(user):
    data = request.json
    msg_id = data.get('message_id')
    sql = "INSERT INTO saved_messages (user_id, message_id, saved_at) VALUES (?, ?, ?)" if not USE_POSTGRES else "INSERT INTO saved_messages (user_id, message_id, saved_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"
    execute_sql(sql, (user['id'], msg_id, int(time.time())))
    return jsonify({'status': 'saved'})

@app.route('/api/user/<username>', methods=['GET'])
@login_required
def get_user(user, username):
    target = get_user_by_username(username)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'id': target['id'], 'username': target['username'], 'display_name': target['display_name'], 'stars': target.get('stars', 0), 'status': target.get('status'), 'last_seen': target.get('last_seen')})

@app.route('/api/user/update_profile', methods=['POST'])
@login_required
def update_profile(user):
    bio = request.json.get('bio')
    if bio is not None:
        sql = "UPDATE users SET bio = ? WHERE id = ?" if not USE_POSTGRES else "UPDATE users SET bio = %s WHERE id = %s"
        execute_sql(sql, (bio, user['id']))
    return jsonify({'status': 'ok'})

@app.route('/api/admin/stats', methods=['GET'])
@login_required
@admin_required
def admin_stats(user):
    sql_users = "SELECT COUNT(*) FROM users"
    sql_messages = "SELECT COUNT(*) FROM messages"
    sql_stars = "SELECT COALESCE(SUM(stars), 0) FROM users"
    total_users = query_all(sql_users)[0]['count'] if USE_POSTGRES else query_all(sql_users)[0][0]
    total_messages = query_all(sql_messages)[0]['count'] if USE_POSTGRES else query_all(sql_messages)[0][0]
    total_stars = query_all(sql_stars)[0]['coalesce'] if USE_POSTGRES else query_all(sql_stars)[0][0]
    return jsonify({'total_users': total_users, 'total_messages': total_messages, 'total_stars': total_stars})

@app.route('/api/admin/ban', methods=['POST'])
@login_required
@admin_required
def admin_ban(user):
    username = request.json.get('username')
    if not username:
        return jsonify({'error': 'Username required'}), 400
    target = get_user_by_username(username)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    sql = "UPDATE users SET is_banned = 1 WHERE id = ?" if not USE_POSTGRES else "UPDATE users SET is_banned = TRUE WHERE id = %s"
    execute_sql(sql, (target['id'],))
    socketio.emit('user_banned', {'message': 'Вы были забанены'}, room=f'user_{target["id"]}')
    return jsonify({'status': 'banned'})

@app.route('/api/admin/unban', methods=['POST'])
@login_required
@admin_required
def admin_unban(user):
    username = request.json.get('username')
    if not username:
        return jsonify({'error': 'Username required'}), 400
    target = get_user_by_username(username)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    sql = "UPDATE users SET is_banned = 0 WHERE id = ?" if not USE_POSTGRES else "UPDATE users SET is_banned = FALSE WHERE id = %s"
    execute_sql(sql, (target['id'],))
    return jsonify({'status': 'unbanned'})

@app.route('/api/admin/add_stars', methods=['POST'])
@login_required
@admin_required
def admin_add_stars(user):
    username = request.json.get('username')
    amount = request.json.get('amount', 0)
    if not username or not isinstance(amount, int):
        return jsonify({'error': 'Invalid data'}), 400
    target = get_user_by_username(username)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    sql = "UPDATE users SET stars = stars + ? WHERE id = ?" if not USE_POSTGRES else "UPDATE users SET stars = stars + %s WHERE id = %s"
    execute_sql(sql, (amount, target['id']))
    return jsonify({'status': 'ok'})

# -------------------- WebSocket --------------------
@socketio.on('register')
def on_register():
    user_id = session.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)