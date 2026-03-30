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

# -------------------- БАЗА ДАННЫХ (SQLite с постоянным хранением) --------------------
DB_PATH = 'messenger.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE,
        username TEXT UNIQUE,
        display_name TEXT,
        password_hash TEXT,
        avatar TEXT,
        bio TEXT,
        stars INTEGER DEFAULT 0,
        status TEXT DEFAULT 'online',
        last_seen INTEGER,
        is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
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
    cur.execute('''CREATE TABLE IF NOT EXISTS user_gifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        gift_id INTEGER,
        message TEXT,
        timestamp INTEGER
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY,
        banned_by INTEGER,
        reason TEXT,
        banned_at INTEGER
    )''')
    cur.execute("SELECT COUNT(*) FROM gifts")
    if cur.fetchone()[0] == 0:
        gifts = [('🌹 Роза', 5, '🌹'), ('🎁 Подарок', 10, '🎁'), ('💎 Бриллиант', 50, '💎'), ('⭐ Звезда', 1, '⭐'), ('🏆 Трофей', 100, '🏆')]
        cur.executemany("INSERT INTO gifts (name, price, icon) VALUES (?, ?, ?)", gifts)
    conn.commit()
    conn.close()

init_db()

# -------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ --------------------
def query_one(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def query_all(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(row) for row in rows]

def execute_sql(sql, params=(), return_id=False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    last_id = cur.lastrowid if return_id else None
    conn.commit()
    cur.close()
    conn.close()
    return last_id

def get_user_by_username(username):
    return query_one("SELECT id, username, display_name, password_hash, avatar, bio, stars, status, last_seen, is_admin, is_banned FROM users WHERE username = ?", (username,))

def get_user_by_phone(phone):
    return query_one("SELECT id, username, display_name, password_hash, avatar, bio, stars, status, last_seen, is_admin, is_banned FROM users WHERE phone = ?", (phone,))

def get_user_by_id(uid):
    return query_one("SELECT id, username, display_name, avatar, bio, stars, status, last_seen, is_admin, is_banned FROM users WHERE id = ?", (uid,))

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
        :root { --bg:#0a0a0f; --surface:#16161d; --surface-light:#22222c; --primary:#5e9bff; --text:#f0f0f5; --border:#2a2a33; --success:#4cd964; }
        body { background:var(--bg); color:var(--text); font-family:system-ui; height:100vh; overflow:hidden; }
        .app { display:flex; flex-direction:column; height:100vh; width:100vw; }
        .header { background:var(--surface); padding:12px 20px; display:flex; justify-content:space-between; align-items:center; flex-shrink:0; }
        .logo { font-size:1.4rem; background:linear-gradient(135deg,#5e9bff,#b77cff); -webkit-background-clip:text; background-clip:text; color:transparent; }
        .btn-icon { background:var(--surface-light); border:none; color:var(--text); padding:8px 16px; border-radius:30px; cursor:pointer; font-size:0.9rem; }
        .auth-container { padding:30px 20px; max-width:400px; margin:auto; width:100%; }
        input, textarea { width:100%; padding:12px; background:var(--surface); border:1px solid var(--border); border-radius:12px; color:var(--text); margin-bottom:12px; outline:none; font-size:1rem; }
        button { background:var(--primary); color:white; border:none; padding:12px; border-radius:30px; font-weight:600; cursor:pointer; width:100%; margin-bottom:10px; font-size:1rem; }
        button:active { transform:scale(0.97); }
        .btn-outline { background:transparent; border:1px solid var(--primary); color:var(--primary); }
        .chat-container { display:flex; flex:1; overflow:hidden; min-height:0; }
        .sidebar { width:300px; background:var(--surface); border-right:1px solid var(--border); display:flex; flex-direction:column; overflow-y:auto; }
        .chat-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:75%; padding:10px 14px; border-radius:18px; background:var(--surface-light); align-self:flex-start; word-wrap:break-word; position:relative; }
        .message.own { background:var(--primary); align-self:flex-end; }
        .message .sender { font-size:0.7rem; opacity:0.7; margin-bottom:4px; }
        .message .text { font-size:0.95rem; }
        .message .time { font-size:0.6rem; text-align:right; margin-top:4px; opacity:0.6; }
        .message .actions { position:absolute; top:5px; right:5px; display:none; gap:5px; background:var(--surface); padding:2px 5px; border-radius:12px; }
        .message:hover .actions { display:flex; }
        .message .actions button { background:none; border:none; color:var(--text); font-size:0.8rem; padding:2px 5px; width:auto; margin:0; cursor:pointer; }
        .input-bar { padding:12px; background:var(--surface); border-top:1px solid var(--border); display:flex; gap:10px; flex-shrink:0; }
        .input-bar input { flex:1; margin:0; }
        .input-bar button { width:auto; padding:12px 20px; margin:0; }
        .contact-item, .gift-item { padding:12px 16px; border-bottom:1px solid var(--border); cursor:pointer; display:flex; align-items:center; gap:12px; }
        .contact-item:hover, .gift-item:hover { background:var(--surface-light); }
        .avatar { width:40px; height:40px; border-radius:50%; background:var(--primary); display:flex; align-items:center; justify-content:center; font-size:1.2rem; flex-shrink:0; }
        .hidden { display:none !important; }
        .tab-bar { background:var(--surface); display:flex; justify-content:space-around; padding:8px 0; border-bottom:1px solid var(--border); flex-shrink:0; }
        .tab { flex:1; text-align:center; padding:10px; background:none; color:#aaaabc; border-radius:0; cursor:pointer; font-size:0.9rem; }
        .tab.active { color:var(--primary); border-bottom:2px solid var(--primary); }
        .modal { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.9); display:flex; align-items:center; justify-content:center; z-index:1000; }
        .modal-content { background:var(--surface); border-radius:20px; padding:20px; width:90%; max-width:400px; max-height:80%; overflow-y:auto; }
        .stars-badge { background:rgba(255,215,0,0.2); padding:6px 12px; border-radius:20px; cursor:pointer; font-size:0.9rem; }
        .stars-badge span { color:gold; }
        .user-info { display:flex; gap:10px; align-items:center; }
        .search-bar { padding:10px; background:var(--surface); border-bottom:1px solid var(--border); }
        .search-bar input { margin:0; background:var(--surface-light); }
        @media (max-width:768px) {
            .sidebar { position:absolute; z-index:10; height:100%; transform:translateX(-100%); width:280px; transition:0.3s; }
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
            <button class="btn-icon" id="profileBtn" style="display:none;">👤 Профиль</button>
            <button class="btn-icon" id="adminBtn" style="display:none;">⚙️ Админ</button>
            <button class="btn-icon" id="logoutBtn" style="display:none;">🚪 Выход</button>
        </div>
    </div>
    <div id="authScreen">
        <div class="auth-container">
            <h2 style="margin-bottom:20px;">Вход в мессенджер</h2>
            <input type="text" id="loginInput" placeholder="Телефон или @username">
            <input type="password" id="passwordInput" placeholder="Пароль">
            <button id="loginBtn">Войти</button>
            <button id="showRegisterBtn" class="btn-outline">Регистрация</button>
        </div>
        <div id="registerForm" class="hidden auth-container">
            <h2 style="margin-bottom:20px;">Регистрация</h2>
            <input type="text" id="regPhone" placeholder="Телефон +7...">
            <input type="text" id="regUsername" placeholder="@username (латиница)">
            <input type="text" id="regDisplayName" placeholder="Ваше имя">
            <input type="password" id="regPassword" placeholder="Пароль">
            <button id="doRegisterBtn">Зарегистрироваться</button>
            <button id="backToLoginBtn" class="btn-outline">Назад</button>
        </div>
    </div>
    <div id="mainScreen" class="hidden" style="flex:1; display:flex; flex-direction:column; min-height:0;">
        <div class="tab-bar">
            <button class="tab active" data-tab="chats">💬 Чаты</button>
            <button class="tab" data-tab="gifts">🎁 Подарки</button>
            <button class="tab" data-tab="saved">⭐ Избранное</button>
        </div>
        <div class="chat-container">
            <div class="sidebar" id="sidebar">
                <div class="search-bar"><input type="text" id="searchUsers" placeholder="Поиск пользователей..."></div>
                <div id="chatsList" style="flex:1; overflow-y:auto;"></div>
                <div id="giftsList" class="hidden" style="flex:1; overflow-y:auto;"></div>
                <div id="savedList" class="hidden" style="flex:1; overflow-y:auto;"></div>
            </div>
            <div class="chat-area">
                <div id="currentChatHeader" style="padding:12px; border-bottom:1px solid var(--border); font-weight:bold;"></div>
                <div class="messages-area" id="messagesArea"></div>
                <div class="input-bar">
                    <input type="text" id="messageInput" placeholder="Сообщение...">
                    <button id="sendMsgBtn">📤 Отправить</button>
                </div>
            </div>
        </div>
    </div>
</div>
<div id="profileModal" class="modal hidden"><div class="modal-content"><div id="profileContent"></div><button id="closeProfile" style="margin-top:15px;">Закрыть</button></div></div>
<div id="adminModal" class="modal hidden"><div class="modal-content"><div id="adminContent"></div><button id="closeAdmin" style="margin-top:15px;">Закрыть</button></div></div>
<script>
let socket=null,currentUser=null,currentChat=null;
const authScreen=document.getElementById('authScreen'),mainScreen=document.getElementById('mainScreen');
const loginBtn=document.getElementById('loginBtn'),logoutBtn=document.getElementById('logoutBtn');
const showRegisterBtn=document.getElementById('showRegisterBtn'),registerForm=document.getElementById('registerForm');
const backToLoginBtn=document.getElementById('backToLoginBtn'),doRegisterBtn=document.getElementById('doRegisterBtn');
const sendMsgBtn=document.getElementById('sendMsgBtn'),messageInput=document.getElementById('messageInput');
const messagesArea=document.getElementById('messagesArea'),currentChatHeader=document.getElementById('currentChatHeader');
const chatsListDiv=document.getElementById('chatsList'),giftsListDiv=document.getElementById('giftsList'),savedListDiv=document.getElementById('savedList');
const starsDisplay=document.getElementById('starsDisplay'),profileBtn=document.getElementById('profileBtn'),adminBtn=document.getElementById('adminBtn');
const searchInput=document.getElementById('searchUsers'),tabs=document.querySelectorAll('.tab');
let searchTimeout=null;

function showToast(msg){let t=document.createElement('div');t.innerText=msg;t.style.position='fixed';t.style.bottom='20px';t.style.left='20px';t.style.right='20px';t.style.background='#333';t.style.color='#fff';t.style.padding='12px';t.style.borderRadius='30px';t.style.textAlign='center';t.style.zIndex='9999';document.body.appendChild(t);setTimeout(()=>t.remove(),2000);}
function escapeHtml(str){return str.replace(/[&<>]/g,function(m){if(m==='&')return '&amp;';if(m==='<')return '&lt;';if(m==='>')return '&gt;';return m;});}
function appendMessage(msg,isOwn){let div=document.createElement('div');div.className=`message ${isOwn?'own':''}`;div.innerHTML=`<div class="sender">${isOwn?'Вы':(msg.sender_name||'Пользователь')}</div><div class="text">${escapeHtml(msg.content||'')}</div><div class="time">${new Date(msg.timestamp*1000).toLocaleTimeString()}</div><div class="actions"><button class="saveMsg" data-id="${msg.id}">⭐</button></div>`;messagesArea.appendChild(div);messagesArea.scrollTop=messagesArea.scrollHeight;div.querySelector('.saveMsg')?.addEventListener('click',(e)=>{e.stopPropagation();saveMessageToFav(msg.id);});}
async function loadMessages(chatType,chatId){const res=await fetch(`/api/messages/${chatType}/${chatId}`);const data=await res.json();messagesArea.innerHTML='';data.messages.forEach(m=>appendMessage(m,m.sender_id===currentUser.id));}
async function loadDialogs(){const res=await fetch('/api/search?q=');const data=await res.json();chatsListDiv.innerHTML='';data.results.forEach(u=>{let div=document.createElement('div');div.className='contact-item';div.innerHTML=`<div class="avatar">${(u.display_name||u.username)[0].toUpperCase()}</div><div><strong>${u.display_name||u.username}</strong><div>@${u.username}</div><div>${u.status==='online'?'🟢 онлайн':'⚫ офлайн'}</div></div>`;div.onclick=()=>{currentChat={type:'private',id:u.id,name:u.username};currentChatHeader.innerText=`Чат с ${u.username}`;loadMessages('private',Math.min(currentUser.id,u.id));};chatsListDiv.appendChild(div);});}
async function loadGifts(){const res=await fetch('/api/gifts');const data=await res.json();giftsListDiv.innerHTML='';data.gifts.forEach(g=>{let div=document.createElement('div');div.className='gift-item';div.innerHTML=`<div style="font-size:2rem;">${g.icon}</div><div><strong>${g.name}</strong><div>${g.price} ⭐</div></div>`;div.onclick=()=>sendGift(g.id);giftsListDiv.appendChild(div);});}
async function loadSaved(){const res=await fetch('/api/saved_messages');const data=await res.json();savedListDiv.innerHTML='';data.saved.forEach(s=>{let div=document.createElement('div');div.className='contact-item';div.innerHTML=`<div><strong>${escapeHtml(s.content.substring(0,50))}</strong><div class="time">${new Date(s.timestamp*1000).toLocaleString()}</div></div>`;savedListDiv.appendChild(div);});}
async function sendGift(giftId){const username=prompt('Введите username получателя:');if(!username)return;const msg=prompt('Сообщение к подарку:');const res=await fetch('/api/gift/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_username:username,gift_id:giftId,message:msg||''})});const data=await res.json();if(res.ok){showToast(`Подарок отправлен! У вас осталось ${data.stars_balance} ⭐`);updateStars(data.stars_balance);}else{showToast(data.error);}}
async function saveMessageToFav(msgId){const res=await fetch('/api/save_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:msgId})});if(res.ok)showToast('Сохранено в избранное');}
async function updateStars(balance){starsDisplay.querySelector('span').innerText=balance;}
async function showProfile(username){const res=await fetch(`/api/user/${username}`);const data=await res.json();document.getElementById('profileContent').innerHTML=`<div style="text-align:center;"><div class="avatar" style="width:80px;height:80px;font-size:3rem;margin:0 auto;">${(data.display_name||data.username)[0].toUpperCase()}</div><h3>${data.display_name||data.username}</h3><p>@${data.username}</p><p>${data.bio||'Нет описания'}</p><p>⭐ ${data.stars} звёзд</p><p>${data.status==='online'?'🟢 Онлайн':'⚫ Был(а) '+new Date(data.last_seen*1000).toLocaleString()}</p>${currentUser.username===username?'<button id="editProfileBtn" style="margin-top:10px;">Редактировать профиль</button>':''}</div>`;document.getElementById('profileModal').style.display='flex';if(currentUser.username===username){document.getElementById('editProfileBtn').onclick=()=>{const newBio=prompt('Введите новое описание:',data.bio||'');if(newBio!==null){fetch('/api/user/update_profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bio:newBio})}).then(()=>showProfile(username));}};}}
function initSocket(){socket=io();socket.on('connect',()=>console.log('Socket connected'));socket.on('new_private_message',(data)=>{if(currentChat&&currentChat.type==='private'&&currentChat.id===data.from){appendMessage({content:data.message,timestamp:data.timestamp,sender_id:data.from,id:data.message_id},false);}loadDialogs();});socket.emit('register');}
searchInput.addEventListener('input',()=>{clearTimeout(searchTimeout);const q=searchInput.value.trim();if(q.length<2)return;searchTimeout=setTimeout(async()=>{const res=await fetch(`/api/search?q=${encodeURIComponent(q)}`);const data=await res.json();chatsListDiv.innerHTML='';data.results.forEach(u=>{let div=document.createElement('div');div.className='contact-item';div.innerHTML=`<div class="avatar">${(u.display_name||u.username)[0].toUpperCase()}</div><div><strong>${u.display_name||u.username}</strong><div>@${u.username}</div></div>`;div.onclick=()=>{currentChat={type:'private',id:u.id,name:u.username};currentChatHeader.innerText=`Чат с ${u.username}`;loadMessages('private',Math.min(currentUser.id,u.id));};chatsListDiv.appendChild(div);});},300);});
loginBtn.onclick=async()=>{const login=document.getElementById('loginInput').value;const pwd=document.getElementById('passwordInput').value;const res=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({login,password:pwd})});const data=await res.json();if(res.ok){currentUser=data.user;sessionStorage.setItem('user',JSON.stringify(currentUser));initSocket();authScreen.classList.add('hidden');mainScreen.classList.remove('hidden');logoutBtn.style.display='inline-block';profileBtn.style.display='inline-block';starsDisplay.style.display='inline-block';updateStars(currentUser.stars);if(currentUser.is_admin||currentUser.username==='asdfg')adminBtn.style.display='inline-block';loadDialogs();loadGifts();loadSaved();}else{showToast(data.error);}};
showRegisterBtn.onclick=()=>{document.querySelector('.auth-container').classList.add('hidden');registerForm.classList.remove('hidden');};
backToLoginBtn.onclick=()=>{registerForm.classList.add('hidden');document.querySelector('.auth-container').classList.remove('hidden');};
doRegisterBtn.onclick=async()=>{const phone=document.getElementById('regPhone').value;const username=document.getElementById('regUsername').value;const display_name=document.getElementById('regDisplayName').value;const pwd=document.getElementById('regPassword').value;const res=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,username,display_name,password:pwd})});const data=await res.json();if(res.ok){showToast('Регистрация успешна, войдите');backToLoginBtn.click();}else{showToast(data.error);}};
logoutBtn.onclick=async()=>{await fetch('/api/logout',{method:'POST'});if(socket)socket.disconnect();sessionStorage.clear();location.reload();};
profileBtn.onclick=()=>showProfile(currentUser.username);
adminBtn.onclick=async()=>{const res=await fetch('/api/admin/stats');const stats=await res.json();document.getElementById('adminContent').innerHTML=`<h3>Админ-панель</h3><p>👥 Пользователей: ${stats.total_users}</p><p>💬 Сообщений: ${stats.total_messages}</p><p>⭐ Звёзд в системе: ${stats.total_stars}</p><hr><h4>Управление пользователями</h4><input type="text" id="banUser" placeholder="Username для бана"><button id="banBtn">Забанить</button><input type="text" id="unbanUser" placeholder="Username для разбана"><button id="unbanBtn">Разбанить</button><hr><h4>Выдача звёзд</h4><input type="text" id="addStarsUser" placeholder="Username"><input type="number" id="addStarsAmount" placeholder="Количество"><button id="addStarsBtn">Добавить звёзды</button><hr><h4>Создать админа</h4><input type="text" id="makeAdminUser" placeholder="Username"><button id="makeAdminBtn">Сделать админом</button>`;document.getElementById('adminModal').style.display='flex';document.getElementById('banBtn').onclick=async()=>{const username=document.getElementById('banUser').value;if(!username)return;await fetch('/api/admin/ban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username})});showToast(`✅ ${username} забанен`);};document.getElementById('unbanBtn').onclick=async()=>{const username=document.getElementById('unbanUser').value;if(!username)return;await fetch('/api/admin/unban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username})});showToast(`✅ ${username} разбанен`);};document.getElementById('addStarsBtn').onclick=async()=>{const username=document.getElementById('addStarsUser').value;const amount=parseInt(document.getElementById('addStarsAmount').value);if(!username||isNaN(amount))return;await fetch('/api/admin/add_stars',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,amount})});showToast(`✨ Добавлено ${amount} звёзд пользователю ${username}`);};document.getElementById('makeAdminBtn').onclick=async()=>{const username=document.getElementById('makeAdminUser').value;if(!username)return;await fetch('/api/admin/make_admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username})});showToast(`👑 ${username} теперь администратор`);};};
document.getElementById('closeProfile').onclick=()=>document.getElementById('profileModal').style.display='none';
document.getElementById('closeAdmin').onclick=()=>document.getElementById('adminModal').style.display='none';
sendMsgBtn.onclick=async()=>{if(!currentChat||!messageInput.value.trim())return;await fetch('/api/message/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_type:currentChat.type,chat_id:currentChat.id,content:messageInput.value})});messageInput.value='';loadMessages(currentChat.type,currentChat.id);};
messageInput.addEventListener('keypress',(e)=>{if(e.key==='Enter')sendMsgBtn.click();});
tabs.forEach(tab=>{tab.addEventListener('click',()=>{tabs.forEach(t=>t.classList.remove('active'));tab.classList.add('active');const target=tab.dataset.tab;chatsListDiv.classList.add('hidden');giftsListDiv.classList.add('hidden');savedListDiv.classList.add('hidden');if(target==='chats')chatsListDiv.classList.remove('hidden');if(target==='gifts'){giftsListDiv.classList.remove('hidden');loadGifts();}if(target==='saved'){savedListDiv.classList.remove('hidden');loadSaved();}});});
const saved=sessionStorage.getItem('user');if(saved){currentUser=JSON.parse(saved);initSocket();authScreen.classList.add('hidden');mainScreen.classList.remove('hidden');logoutBtn.style.display='inline-block';profileBtn.style.display='inline-block';starsDisplay.style.display='inline-block';updateStars(currentUser.stars);if(currentUser.is_admin||currentUser.username==='asdfg')adminBtn.style.display='inline-block';loadDialogs();loadGifts();loadSaved();}
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
    user_id = execute_sql("INSERT INTO users (phone, username, display_name, password_hash, status, last_seen, created_at, is_admin, stars) VALUES (?, ?, ?, ?, 'online', ?, ?, 0, 0)", (phone, username, display_name, pwd_hash, ts, ts), return_id=True)
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
    execute_sql("UPDATE users SET status = 'online', last_seen = ? WHERE id = ?", (int(time.time()), user['id']))
    return jsonify({'status': 'ok', 'user': {'id': user['id'], 'username': user['username'], 'display_name': user['display_name'], 'is_admin': user.get('is_admin', 0), 'stars': user.get('stars', 0)}})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout(user):
    execute_sql("UPDATE users SET status = 'offline', last_seen = ? WHERE id = ?", (int(time.time()), user['id']))
    session.clear()
    return jsonify({'status': 'ok'})

@app.route('/api/search', methods=['GET'])
@login_required
def search(user):
    q = request.args.get('q', '')
    if len(q) < 2:
        rows = query_all("SELECT id, username, display_name, status, last_seen FROM users WHERE id != ? LIMIT 50", (user['id'],))
    else:
        rows = query_all("SELECT id, username, display_name, status, last_seen FROM users WHERE (username LIKE ? OR display_name LIKE ?) AND id != ? LIMIT 20", (f'%{q}%', f'%{q}%', user['id']))
    return jsonify({'results': rows})

@app.route('/api/messages/<chat_type>/<int:chat_id>', methods=['GET'])
@login_required
def get_messages(user, chat_type, chat_id):
    rows = query_all("SELECT id, sender_id, content, timestamp FROM messages WHERE chat_type = ? AND chat_id = ? ORDER BY timestamp DESC LIMIT 100", (chat_type, chat_id))
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
    msg_id = execute_sql("INSERT INTO messages (chat_type, chat_id, sender_id, content, timestamp) VALUES (?, ?, ?, ?, ?)", (chat_type, chat_id, user['id'], content, ts), return_id=True)
    if chat_type == 'private':
        socketio.emit('new_private_message', {'from': user['id'], 'to': chat_id, 'message': content, 'message_id': msg_id, 'timestamp': ts}, room=f'user_{chat_id}')
    return jsonify({'message_id': msg_id, 'timestamp': ts})

@app.route('/api/save_message', methods=['POST'])
@login_required
def save_message(user):
    msg_id = request.json.get('message_id')
    execute_sql("INSERT OR IGNORE INTO saved_messages (user_id, message_id, saved_at) VALUES (?, ?, ?)", (user['id'], msg_id, int(time.time())))
    return jsonify({'status': 'saved'})

@app.route('/api/saved_messages', methods=['GET'])
@login_required
def get_saved_messages(user):
    rows = query_all("SELECT m.id, m.content, m.timestamp FROM messages m JOIN saved_messages s ON m.id = s.message_id WHERE s.user_id = ? ORDER BY s.saved_at DESC LIMIT 100", (user['id'],))
    return jsonify({'saved': rows})

@app.route('/api/gifts', methods=['GET'])
@login_required
def get_gifts(user):
    rows = query_all("SELECT id, name, price, icon FROM gifts")
    return jsonify({'gifts': rows})

@app.route('/api/gift/send', methods=['POST'])
@login_required
def send_gift(user):
    data = request.json
    to_username, gift_id, msg = data.get('to_username'), data.get('gift_id'), data.get('message', '')
    if not to_username or not gift_id:
        return jsonify({'error': 'Missing parameters'}), 400
    target = get_user_by_username(to_username)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    gift = query_one("SELECT price FROM gifts WHERE id = ?", (gift_id,))
    if not gift:
        return jsonify({'error': 'Gift not found'}), 404
    price = gift['price']
    if user['stars'] < price:
        return jsonify({'error': 'Not enough stars'}), 400
    execute_sql("UPDATE users SET stars = stars - ? WHERE id = ?", (price, user['id']))
    execute_sql("UPDATE users SET stars = stars + ? WHERE id = ?", (price, target['id']))
    execute_sql("INSERT INTO user_gifts (from_user, to_user, gift_id, message, timestamp) VALUES (?, ?, ?, ?, ?)", (user['id'], target['id'], gift_id, msg, int(time.time())))
    new_balance = query_one("SELECT stars FROM users WHERE id = ?", (user['id'],))['stars']
    return jsonify({'status': 'ok', 'stars_balance': new_balance})

@app.route('/api/user/<username>', methods=['GET'])
@login_required
def get_user(user, username):
    target = get_user_by_username(username)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'id': target['id'], 'username': target['username'], 'display_name': target['display_name'], 'bio': target.get('bio'), 'stars': target.get('stars', 0), 'status': target.get('status'), 'last_seen': target.get('last_seen')})

@app.route('/api/user/update_profile', methods=['POST'])
@login_required
def update_profile(user):
    bio = request.json.get('bio')
    if bio is not None:
        execute_sql("UPDATE users SET bio = ? WHERE id = ?", (bio, user['id']))
    return jsonify({'status': 'ok'})

@app.route('/api/admin/stats', methods=['GET'])
@login_required
@admin_required
def admin_stats(user):
    total_users = query_one("SELECT COUNT(*) as count FROM users")['count']
    total_messages = query_one("SELECT COUNT(*) as count FROM messages")['count']
    total_stars = query_one("SELECT COALESCE(SUM(stars), 0) as sum FROM users")['sum']
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
    execute_sql("UPDATE users SET is_banned = 1 WHERE id = ?", (target['id'],))
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
    execute_sql("UPDATE users SET is_banned = 0 WHERE id = ?", (target['id'],))
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
    execute_sql("UPDATE users SET stars = stars + ? WHERE id = ?", (amount, target['id']))
    return jsonify({'status': 'ok'})

@app.route('/api/admin/make_admin', methods=['POST'])
@login_required
@admin_required
def make_admin(user):
    username = request.json.get('username')
    if not username:
        return jsonify({'error': 'Username required'}), 400
    target = get_user_by_username(username)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    execute_sql("UPDATE users SET is_admin = 1 WHERE id = ?", (target['id'],))
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