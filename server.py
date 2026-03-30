#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ==================== ИМПОРТЫ МЕССЕНДЖЕРА ====================
import os
import json
import secrets
import time
import re
import sqlite3
import threading
import asyncio
import base64
from datetime import date
from functools import wraps
from typing import Dict, List, Optional, Tuple

from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

# ==================== ИМПОРТЫ БОТА ====================
import aiohttp
import aiofiles
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction

# Попытка импортировать markdown
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    def simple_markdown_to_html(text: str) -> str:
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
        text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
        text = re.sub(r'^# (.*?)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        return text

# ==================== КОНФИГУРАЦИЯ БОТА ====================
BOT_TOKEN = "8671297334:AAFbmN7sSd0rRUdq5djQE5sgbUXIoT3hmHE"
ADMIN_USERNAME = "sanya_play"

USERS_DB = "users.json"
STATS_FILE = "limits.txt"
SETTINGS_FILE = "settings.json"

API_KEYS = [
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
]

RANK_KEY_INDICES = {"admin": [0,1,2], "silver": [3,4,5,6], "gold": [7,8], "bronze": []}
RANK_DAILY_QUOTA = {"admin": 0, "gold": 100, "silver": 25, "bronze": 0}

AVAILABLE_MODELS = {
    "arcee-ai/trinity-large-preview:free": "🌟 Trinity-Large-Preview",
    "stepfun/step-3.5-flash:free": "⚡ Step 3.5 Flash",
    "z-ai/glm-4.5-air:free": "🔮 GLM-4.5-Air",
    "nvidia/nemotron-3-nano-30b-a3b:free": "💠 NVIDIA Nemotron 3",
    "nvidia/nemotron-3-super-120b-a12b:free": "🛡️ Nemotron 3 Super",
    "arcee-ai/trinity-mini:free": "🌀 Trinity Mini",
    "deepseek/deepseek-r1": "🧠 DeepSeek R1",
    "qwen/qwen-2.5-coder-32b-instruct": "👨‍💻 Qwen Coder 32B",
    "google/gemma-2-9b-it": "⚡ Gemma 2 9B",
    "meta-llama/llama-3-8b-instruct": "🦙 Llama 3 8B",
    "openrouter/hunter-alpha:free": "🔥 Hunter Alpha (1M контекст)❌",
    "openrouter/healer-alpha:free": "🌟 Healer Alpha (видео/аудио)❌",
    "openrouter/pony-alpha:free": "✨ Pony Alpha (кодинг)❌",
    "qwen/qwen3-vl-30b-a3b-thinking:free": "🖼️ Qwen3-VL 30B❌",
    "nvidia/nemotron-nano-2-vl:free": "🖼️ Nemotron Nano 2 VL❌",
    "nvidia/llama-3.1-nemotron-nano-8b-v1:free": "⚡ Nemotron Nano 8B❌",
    "qwen/qwen3-next-80b-a3b-instruct:free": "⚡ Qwen3 Next 80B❌",
    "liquid/lfm-1.2b-thinking:free": "💧 LFM 1.2B❌",
    "mistralai/mistral-7b-instruct": "❌🌪️ Mistral 7B ❌",
    "qwen/qwen3-vl-235b-a22b-thinking:free": "❌🖼️ Qwen3-VL Thinking❌",
    "openai/gpt-oss-120b:free": "❌🤖 GPT-OSS-120B❌",
    "meta-llama/llama-3.3-70b-instruct:free": "❌📚 Llama 3.3 70B❌",
    "qwen/qwen3-coder-480b-a35b:free": "❌👨‍💻 Qwen3 Coder 480B❌",
    "google/gemma-3-27b-it:free": "❌🔷 Gemma 3 27B❌",
    "google/gemini-2.0-flash-exp:free": "✨ Gemini 2.0 Flash Exp❌",
    "mistralai/mistral-nemo:free": "🌊 Mistral Nemo❌",
    "cohere/command-r-plus:free": "🎯 Command R+❌",
    "anthropic/claude-3.5-sonnet:free": "🎭 Claude 3.5 Sonnet (limited)❌",
    "perplexity/llama-3.1-sonar-small:free": "🔍 Sonar Small❌",
    "perplexity/llama-3.1-sonar-large:free": "🔍 Sonar Large❌",
    "microsoft/phi-3.5-mini:free": "📘 Phi-3.5 Mini❌",
    "microsoft/phi-3.5-vision:free": "🖼️📘 Phi-3.5 Vision❌",
}
DEFAULT_MODEL = "deepseek/deepseek-r1"

IMAGE_GEN_MODELS = {
    "google/nano-banana-pro": "🎨 Google Nano Banana Pro",
    "google/gemini-2.5-flash-image": "🎨 Gemini 2.5 Flash Image",
    "google/gemini-3.1-flash-image-preview": "🎨 Gemini 3.1 Flash Preview",
    "openai/gpt-5-image": "🎨 GPT-5 Image",
    "openai/gpt-5-image-mini": "🎨 GPT-5 Image Mini",
    "bytedance-seed/seedream-4.5": "🎨 Seedream 4.5",
    "black-forest-labs/flux-2-klein": "🎨 FLUX.2 Klein",
    "black-forest-labs/flux-2-pro": "🎨 FLUX.2 Pro",
    "sourceful/riverflow-v2-fast": "🎨 Riverflow V2 Fast",
    "stabilityai/stable-diffusion-3.5-large": "🎨 SD 3.5 Large",
    "stabilityai/stable-diffusion-3.5-medium": "🎨 SD 3.5 Medium",
    "luma/photon-1": "📸 Luma Photon",
    "luma/photon-flash": "📸 Luma Photon Flash",
}
VIDEO_GEN_MODELS = {
    "luma/ray-2": "🎥 Luma Ray 2",
    "minimax/video-01": "🎥 Minimax Video 01",
    "kling/kling-vision": "🎥 Kling Vision",
    "genmo/genmo-video": "🎥 Genmo Video",
    "google/nano-banana-pro": "🎥 Google Nano Banana Pro",
}
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

users_lock = asyncio.Lock()

# ==================== ФУНКЦИИ МЕССЕНДЖЕРА ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

DB_PATH = 'messenger.db'
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_messenger_db():
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
    cur.execute("SELECT COUNT(*) FROM gifts")
    if cur.fetchone()[0] == 0:
        gifts = [('🌹 Роза', 5, '🌹'), ('🎁 Подарок', 10, '🎁'), ('💎 Бриллиант', 50, '💎'), ('⭐ Звезда', 1, '⭐'), ('🏆 Трофей', 100, '🏆')]
        cur.executemany("INSERT INTO gifts (name, price, icon) VALUES (?, ?, ?)", gifts)
    conn.commit()
    conn.close()

init_messenger_db()

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
    return query_one("SELECT id, username, display_name, password_hash, stars, status, last_seen, is_admin, is_banned FROM users WHERE username = ?", (username,))
def get_user_by_phone(phone):
    return query_one("SELECT id, username, display_name, password_hash, stars, status, last_seen, is_admin, is_banned FROM users WHERE phone = ?", (phone,))
def get_user_by_id(uid):
    return query_one("SELECT id, username, display_name, stars, status, last_seen, is_admin, is_banned FROM users WHERE id = ?", (uid,))

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

# -------------------- HTML МЕССЕНДЖЕРА --------------------
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
        .btn-icon { background:var(--surface-light); border:none; color:var(--text); padding:8px 16px; border-radius:30px; cursor:pointer; }
        .auth-container { padding:30px 20px; max-width:400px; margin:auto; width:100%; }
        input, textarea { width:100%; padding:12px; background:var(--surface); border:1px solid var(--border); border-radius:12px; color:var(--text); margin-bottom:12px; outline:none; }
        button { background:var(--primary); color:white; border:none; padding:12px; border-radius:30px; font-weight:600; cursor:pointer; width:100%; margin-bottom:10px; }
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
        .tab { flex:1; text-align:center; padding:10px; background:none; color:#aaaabc; border-radius:0; cursor:pointer; }
        .tab.active { color:var(--primary); border-bottom:2px solid var(--primary); }
        .modal { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.9); display:flex; align-items:center; justify-content:center; z-index:1000; }
        .modal-content { background:var(--surface); border-radius:20px; padding:20px; width:90%; max-width:400px; max-height:80%; overflow-y:auto; }
        .stars-badge { background:rgba(255,215,0,0.2); padding:6px 12px; border-radius:20px; cursor:pointer; }
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

# -------------------- API МЕССЕНДЖЕРА --------------------
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
def get_user_profile(user, username):
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

@socketio.on('register')
def on_register():
    user_id = session.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')

# ==================== ФУНКЦИИ БОТА ====================
def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def split_long_message(text: str, max_length: int = 4096) -> List[str]:
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

def markdown_to_html(text: str) -> str:
    if MARKDOWN_AVAILABLE:
        return markdown.markdown(text, extensions=['extra', 'codehilite'])
    else:
        return simple_markdown_to_html(text)

def strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'`(.*?)`', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'~~(.*?)~~', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'^#+\s*(.*?)$', r'\1', text, flags=re.MULTILINE)
    text = re.sub(r'\\\((.*?)\\\)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'[*`#\[\]()\\{}|~^]', '', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

async def load_stats() -> Dict:
    stats = {"date": str(date.today()), "used": [0]*len(API_KEYS)}
    if os.path.exists(STATS_FILE):
        try:
            async with aiofiles.open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
                if data.get("date") == str(date.today()):
                    stats["used"] = data.get("used", [0]*len(API_KEYS))
        except: pass
    return stats

async def save_stats(used_list: List[int]) -> None:
    data = {"date": str(date.today()), "used": used_list}
    async with aiofiles.open(STATS_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, indent=2))

async def load_settings() -> Dict:
    default = {"use_keys_until_error": False, "reasoning_enabled": False, "reasoning_prompt": "Ты должен рассуждать шаг за шагом.", "reasoning_blocked": False, "constant_prompt_enabled": False, "constant_prompt_text": "", "markdown_formatting": False, "strip_formatting": False}
    if os.path.exists(SETTINGS_FILE):
        try:
            async with aiofiles.open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
                merged = default.copy(); merged.update(data); return merged
        except: pass
    return default

async def save_settings(settings: Dict) -> None:
    async with aiofiles.open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(settings, indent=2))

async def load_users() -> Dict[str, Dict]:
    if os.path.exists(USERS_DB):
        try:
            async with aiofiles.open(USERS_DB, "r", encoding="utf-8") as f:
                return json.loads(await f.read())
        except: pass
    return {}

async def save_users(users: Dict[str, Dict]) -> None:
    async with users_lock:
        async with aiofiles.open(USERS_DB, "w", encoding="utf-8") as f:
            await f.write(json.dumps(users, indent=2, ensure_ascii=False))

async def get_user(user_id: int, users: Dict) -> Dict:
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "username": "", "rank": "silver", "daily_used": 0, "last_reset": str(date.today()),
            "model": DEFAULT_MODEL, "is_admin": False, "total_quota": RANK_DAILY_QUOTA["silver"],
            "permanent_balance": 0, "image_balance": 0, "video_balance": 0,
            "selected_image_model": list(IMAGE_GEN_MODELS.keys())[0] if IMAGE_GEN_MODELS else None,
            "selected_video_model": list(VIDEO_GEN_MODELS.keys())[0] if VIDEO_GEN_MODELS else None,
        }
    return users[uid]

def reset_if_new_day(user_data: Dict) -> bool:
    last = user_data.get("last_reset", "")
    today = str(date.today())
    if last != today:
        user_data["daily_used"] = 0
        user_data["last_reset"] = today
        return True
    return False

def can_use_model(user_data: Dict) -> Tuple[bool, str, bool]:
    rank = user_data.get("rank", "silver")
    if rank == "bronze": return False, "❌ Бронзовый ранг пока в разработке.", False
    if rank not in RANK_DAILY_QUOTA: return False, "❌ Неизвестный ранг. Обратитесь к администратору.", False
    if rank == "admin": return True, "", False
    daily_quota = user_data.get("total_quota", RANK_DAILY_QUOTA[rank])
    daily_used = user_data["daily_used"]
    permanent = user_data.get("permanent_balance", 0)
    if daily_used < daily_quota: return True, "", False
    elif permanent > 0: return True, "", True
    else: return False, f"❌ Вы исчерпали дневной лимит ({daily_quota} запросов) и у вас нет постоянных баллов.", False

async def make_request(session: aiohttp.ClientSession, api_key: str, messages: List[Dict], model: str, images: List[str] = None) -> Tuple[Optional[Dict], Optional[str], Optional[int]]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "http://localhost", "X-Title": "Termux AI Bot"}
    data = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 2000}
    if images and messages and messages[-1]["role"] == "user":
        last_msg = messages.pop()
        content = []
        if last_msg.get("content"): content.append({"type": "text", "text": last_msg["content"]})
        for img_b64 in images:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
        messages.append({"role": "user", "content": content})
    try:
        async with session.post(OPENROUTER_URL, headers=headers, json=data, timeout=60) as resp:
            if resp.status == 200:
                try:
                    json_data = await resp.json()
                    return json_data, None, resp.status
                except Exception as e:
                    return None, f"Ошибка чтения JSON: {e}", resp.status
            else:
                error_text = await resp.text() if resp.content else "Нет текста ошибки"
                return None, f"HTTP {resp.status}: {error_text}", resp.status
    except asyncio.TimeoutError: return None, "Таймаут запроса", None
    except aiohttp.ClientError as e: return None, f"Ошибка соединения: {e}", None
    except Exception as e: return None, f"Неизвестная ошибка: {e}", None

def get_available_keys_for_rank(rank: str) -> List[int]:
    return RANK_KEY_INDICES.get(rank, [])

async def try_request_with_keys(context: ContextTypes.DEFAULT_TYPE, rank: str, messages: List[Dict], model: str, images: List[str] = None) -> Tuple[Optional[Dict], Optional[int], Optional[str]]:
    key_indices = get_available_keys_for_rank(rank)
    if not key_indices: return None, None, "❌ Для вашего ранга нет доступных блоков."
    settings = await load_settings()
    use_until_error = settings.get("use_keys_until_error", False)
    stats = await load_stats()
    session = context.application.bot_data.get("http_session")
    if not session: return None, None, "❌ Ошибка инициализации HTTP-сессии."
    for idx in key_indices:
        if not use_until_error and stats["used"][idx] >= 50: continue
        data, error, status = await make_request(session, API_KEYS[idx], messages, model, images)
        if error: continue
        if data: return data, idx, None
    return None, None, "❌ Все доступные блоки не сработали. Попробуйте позже."

async def generate_media(context: ContextTypes.DEFAULT_TYPE, api_key: str, prompt: str, model: str, endpoint: str = OPENROUTER_URL) -> Tuple[Optional[Dict], Optional[str]]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "http://localhost", "X-Title": "Termux AI Bot"}
    data = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"}
    session = context.application.bot_data.get("http_session")
    if not session: return None, "❌ Ошибка инициализации HTTP-сессии."
    try:
        async with session.post(endpoint, headers=headers, json=data, timeout=120) as resp:
            if resp.status == 200:
                return await resp.json(), None
            else:
                return None, f"HTTP {resp.status}"
    except Exception as e: return None, str(e)

def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💬 Чат", callback_data="menu_chat")],
        [InlineKeyboardButton("🖼️ Создать изображение", callback_data="menu_image")],
        [InlineKeyboardButton("🎥 Создать видео", callback_data="menu_video")],
        [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("🤖 Модели", callback_data="menu_models")],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu_help")],
    ]
    if is_admin: keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="menu_admin")])
    return InlineKeyboardMarkup(keyboard)

def back_to_menu_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu")]])

def model_selection_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for model_id, desc in AVAILABLE_MODELS.items():
        if "❌" in desc:
            keyboard.append([InlineKeyboardButton(desc, callback_data=f"model_blocked_{model_id}")])
        else:
            keyboard.append([InlineKeyboardButton(desc, callback_data=f"model_{model_id}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)

def image_model_selection_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for model_id, desc in IMAGE_GEN_MODELS.items():
        keyboard.append([InlineKeyboardButton(desc, callback_data=f"imgmodel_{model_id}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)

def video_model_selection_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for model_id, desc in VIDEO_GEN_MODELS.items():
        keyboard.append([InlineKeyboardButton(desc, callback_data=f"vidmodel_{model_id}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)

async def get_admin_keyboard() -> InlineKeyboardMarkup:
    settings = await load_settings()
    mode_text = "🔄 Режим ключей: упорный" if settings.get("use_keys_until_error") else "🔄 Режим ключей: обычный"
    reasoning_status = "🧠 Режим рассуждения: заблокирован" if settings.get("reasoning_blocked") else ("🧠 Режим рассуждения: вкл" if settings.get("reasoning_enabled") else "🧠 Режим рассуждения: выкл")
    constant_status = "📌 Постоянный промт: вкл" if settings.get("constant_prompt_enabled") else "📌 Постоянный промт: выкл"
    markdown_status = "📝 Markdown: вкл" if settings.get("markdown_formatting") else "📝 Markdown: выкл"
    strip_status = "🧹 Чистый текст: вкл" if settings.get("strip_formatting") else "🧹 Чистый текст: выкл"
    keyboard = [
        [InlineKeyboardButton("👥 Список пользователей", callback_data="admin_list")],
        [InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_find")],
        [InlineKeyboardButton("📊 Статистика ~", callback_data="admin_stats")],
        [InlineKeyboardButton("🎁 Выдать ранг", callback_data="admin_setrank")],
        [InlineKeyboardButton("🔑 Выдать админку", callback_data="admin_grant")],
        [InlineKeyboardButton("🚫 Забрать админку", callback_data="admin_revoke")],
        [InlineKeyboardButton("📈 Изменить лимит", callback_data="admin_setquota")],
        [InlineKeyboardButton("💰 Выдать постоянные баллы", callback_data="admin_give_permanent")],
        [InlineKeyboardButton("🖼️ Выдать баллы на картинки", callback_data="admin_give_image")],
        [InlineKeyboardButton("🎥 Выдать баллы на видео", callback_data="admin_give_video")],
        [InlineKeyboardButton(mode_text, callback_data="admin_toggle_keymode")],
        [InlineKeyboardButton(reasoning_status, callback_data="admin_reasoning_menu")],
        [InlineKeyboardButton(constant_status, callback_data="admin_constant_menu")],
        [InlineKeyboardButton(markdown_status, callback_data="admin_toggle_markdown")],
        [InlineKeyboardButton(strip_status, callback_data="admin_toggle_strip")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def get_reasoning_settings_keyboard() -> InlineKeyboardMarkup:
    settings = await load_settings()
    enabled = settings.get("reasoning_enabled", False)
    blocked = settings.get("reasoning_blocked", False)
    kb = [
        [InlineKeyboardButton(f"{'✅' if enabled else '❌'} Включить", callback_data="reasoning_toggle")],
        [InlineKeyboardButton(f"{'🔒' if blocked else '🔓'} Блокировать", callback_data="reasoning_block")],
        [InlineKeyboardButton("✏️ Изменить промт", callback_data="reasoning_edit")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(kb)

async def get_constant_prompt_keyboard() -> InlineKeyboardMarkup:
    settings = await load_settings()
    enabled = settings.get("constant_prompt_enabled", False)
    kb = [
        [InlineKeyboardButton(f"{'✅' if enabled else '❌'} Включить", callback_data="constant_toggle")],
        [InlineKeyboardButton("✏️ Изменить промт", callback_data="constant_edit")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(kb)

def chat_mode_keyboard(reasoning_allowed: bool, reasoning_on: bool) -> InlineKeyboardMarkup:
    if reasoning_allowed:
        text = "🧠 Рассуждение: ВКЛ" if reasoning_on else "🧠 Рассуждение: ВЫКЛ"
        return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data="toggle_reasoning")]])
    else:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Рассуждение недоступно", callback_data="noop")]])

# ================== ОБРАБОТЧИКИ БОТА ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    user = update.effective_user
    users = await load_users()
    user_data = await get_user(user.id, users)
    user_data["username"] = user.username or user.full_name
    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        user_data["is_admin"] = True
        user_data["rank"] = "admin"
    reset_if_new_day(user_data)
    await save_users(users)
    rank_display = user_data['rank'].capitalize()
    used = user_data['daily_used']
    quota = user_data.get('total_quota', RANK_DAILY_QUOTA[user_data['rank']]) if user_data['rank'] != 'admin' else '∞'
    permanent = user_data.get('permanent_balance', 0)
    image_bal = user_data.get('image_balance', 0)
    video_bal = user_data.get('video_balance', 0)
    text = (f"🌟 Добро пожаловать, {escape_html(user.full_name)}!\n"
            f"Твой ранг: <b>{rank_display}</b>\n"
            f"Использовано сегодня: {used}/{quota}\n"
            f"Постоянные баллы: {permanent}\n"
            f"Баллы на картинки: {image_bal}\n"
            f"Баллы на видео: {video_bal}\n\n"
            f"Используй кнопки ниже для навигации.")
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_data.get("is_admin", False)), parse_mode="HTML")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    user_id = update.effective_user.id
    users = await load_users()
    user_data = await get_user(user_id, users)
    await update.message.reply_text("🚪 Все режимы сброшены. Используй меню для навигации.", reply_markup=main_menu_keyboard(user_data.get("is_admin", False)))

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    user_id = update.effective_user.id
    users = await load_users()
    user_data = await get_user(user_id, users)
    await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard(user_data.get("is_admin", False)))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    users = await load_users()
    user_data = await get_user(user_id, users)
    if query.from_user.username and query.from_user.username.lower() == ADMIN_USERNAME.lower():
        user_data["is_admin"] = True
        user_data["rank"] = "admin"
        await save_users(users)

    if data == "back_to_menu":
        context.user_data.clear()
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard(user_data.get("is_admin", False)))
        return
    if data == "admin_back":
        kb = await get_admin_keyboard()
        await query.edit_message_text("⚙️ Админ-панель", reply_markup=kb)
        return
    if data == "noop":
        return

    if data == "menu_profile":
        rank = user_data["rank"]
        rank_emoji = {"admin": "👑", "gold": "🥇", "silver": "🥈", "bronze": "🥉"}.get(rank, "")
        model = user_data.get("model", DEFAULT_MODEL)
        model_name = AVAILABLE_MODELS.get(model, model)
        quota = user_data.get("total_quota", RANK_DAILY_QUOTA[rank]) if rank != "admin" else "∞"
        used = user_data["daily_used"]
        permanent = user_data.get("permanent_balance", 0)
        image_bal = user_data.get("image_balance", 0)
        video_bal = user_data.get("video_balance", 0)
        text = (f"<b>👤 Твой профиль</b>\n\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📛 Имя: {escape_html(query.from_user.full_name)}\n"
                f"🔰 Ранг: {rank_emoji} {rank.capitalize()}\n"
                f"🤖 Модель: {escape_html(model_name)}\n"
                f"📊 Использовано сегодня: {used}/{quota}\n"
                f"💰 Постоянные баллы: {permanent}\n"
                f"🖼️ Баллы на картинки: {image_bal}\n"
                f"🎥 Баллы на видео: {video_bal}\n"
                f"👑 Админ: {'Да' if user_data.get('is_admin') else 'Нет'}")
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "menu_models":
        await query.edit_message_text("Выбери модель:", reply_markup=model_selection_keyboard())
        return
    if data.startswith("model_blocked_"):
        await query.edit_message_text("❌ Эта модель заблокирована. Пожалуйста, выберите другую модель.", reply_markup=back_to_menu_button())
        return
    if data.startswith("model_"):
        model_id = data.replace("model_", "")
        if model_id in AVAILABLE_MODELS:
            if "❌" in AVAILABLE_MODELS[model_id]:
                await query.edit_message_text("❌ Эта модель заблокирована.", reply_markup=back_to_menu_button())
                return
            user_data["model"] = model_id
            await save_users(users)
            await query.edit_message_text(f"✅ Модель изменена на: {escape_html(AVAILABLE_MODELS[model_id])}", reply_markup=back_to_menu_button())
        else:
            await query.edit_message_text("❌ Модель не найдена.", reply_markup=back_to_menu_button())
        return

    if data == "menu_help":
        help_text = ("<b>❓ Помощь</b>\n\n"
                     "• Нажми «💬 Чат» и отправь сообщение — я отвечу с помощью выбранной модели.\n"
                     "• Бот помнит историю в чате для поддержания контекста.\n"
                     "• В «🤖 Модели» можно сменить нейросеть.\n"
                     "• «🖼️ Создать изображение» — выбери модель, затем отправь промпт. Тратит 1 балл на картинки.\n"
                     "• «🎥 Создать видео» — выбери модель, затем отправь промпт. Тратит 1 балл на видео.\n"
                     "• В «👤 Профиль» — твоя статистика и баллы.\n"
                     "• Если ты админ, появится «⚙️ Админ-панель».\n"
                     "• При выходе из чата история сообщений сбрасывается.\n\n"
                     "По всем вопросам: @sanya_play")
        await query.edit_message_text(help_text, parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "menu_chat":
        context.user_data["chat_mode"] = True
        context.user_data.pop("admin_action", None)
        context.user_data["chat_history"] = []
        context.user_data["reasoning_mode"] = False
        settings = await load_settings()
        reasoning_allowed = settings.get("reasoning_enabled", False) and not settings.get("reasoning_blocked", False)
        await query.edit_message_text("💬 Режим чата активирован. Просто напиши сообщение (можно с фото), и я пришлю ответ.\nБот помнит историю чата.\nЧтобы выйти, отправь /cancel",
                                      reply_markup=chat_mode_keyboard(reasoning_allowed, False))
        return

    if data == "toggle_reasoning":
        if context.user_data.get("chat_mode"):
            current = context.user_data.get("reasoning_mode", False)
            context.user_data["reasoning_mode"] = not current
            settings = await load_settings()
            reasoning_allowed = settings.get("reasoning_enabled", False) and not settings.get("reasoning_blocked", False)
            await query.edit_message_text(query.message.text, reply_markup=chat_mode_keyboard(reasoning_allowed, context.user_data["reasoning_mode"]))
        return

    if data == "menu_image":
        if user_data.get("image_balance", 0) <= 0:
            await query.edit_message_text("❌ У вас нет баллов на создание изображений.", reply_markup=back_to_menu_button())
            return
        await query.edit_message_text("Выберите модель для генерации изображения:", reply_markup=image_model_selection_keyboard())
        return

    if data.startswith("imgmodel_"):
        model_id = data.replace("imgmodel_", "")
        if model_id in IMAGE_GEN_MODELS:
            context.user_data["selected_image_model"] = model_id
            context.user_data["image_gen_mode"] = True
            await query.edit_message_text(f"✅ Выбрана модель: {IMAGE_GEN_MODELS[model_id]}\n\nОтправьте текстовое описание (промпт) для генерации изображения.\nС вас будет списан 1 балл на картинки.\nДля отмены отправьте /cancel",
                                          reply_markup=back_to_menu_button())
        else:
            await query.edit_message_text("❌ Модель не найдена.", reply_markup=back_to_menu_button())
        return

    if data == "menu_video":
        if user_data.get("video_balance", 0) <= 0:
            await query.edit_message_text("❌ У вас нет баллов на создание видео.", reply_markup=back_to_menu_button())
            return
        await query.edit_message_text("Выберите модель для генерации видео:", reply_markup=video_model_selection_keyboard())
        return

    if data.startswith("vidmodel_"):
        model_id = data.replace("vidmodel_", "")
        if model_id in VIDEO_GEN_MODELS:
            context.user_data["selected_video_model"] = model_id
            context.user_data["video_gen_mode"] = True
            await query.edit_message_text(f"✅ Выбрана модель: {VIDEO_GEN_MODELS[model_id]}\n\nОтправьте текстовое описание (промпт) для генерации видео.\nС вас будет списан 1 балл на видео.\nДля отмены отправьте /cancel",
                                          reply_markup=back_to_menu_button())
        else:
            await query.edit_message_text("❌ Модель не найдена.", reply_markup=back_to_menu_button())
        return

    if data == "menu_admin":
        if not user_data.get("is_admin"):
            await query.edit_message_text("⛔ Доступ запрещён.", reply_markup=back_to_menu_button())
            return
        kb = await get_admin_keyboard()
        await query.edit_message_text("⚙️ Админ-панель", reply_markup=kb)
        return

    if data == "admin_list":
        if not user_data.get("is_admin"): return
        lines = ["<b>Список пользователей:</b>\n"]
        for uid, udata in users.items():
            rank = udata.get("rank", "?")
            used = udata.get("daily_used", 0)
            quota = udata.get("total_quota", RANK_DAILY_QUOTA.get(rank, 0))
            permanent = udata.get("permanent_balance", 0)
            image_bal = udata.get("image_balance", 0)
            video_bal = udata.get("video_balance", 0)
            username = udata.get("username", "нет")
            lines.append(f"• <code>{uid}</code> @{escape_html(username)} | {rank} | {used}/{quota} | perm:{permanent} | img:{image_bal} | vid:{video_bal}")
        text = "\n".join(lines) if len(lines) > 1 else "Пользователей нет."
        if len(text) > 4000: text = text[:4000] + "..."
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "admin_stats":
        if not user_data.get("is_admin"): return
        stats = await load_stats()
        lines = ["<b>📊 Статистика ~ на сегодня:</b>"]
        for i, used in enumerate(stats["used"]):
            lines.append(f"~ {i+1}: использовано {used}/50")
        await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "admin_find":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "find_user"
        await query.edit_message_text("Введите username (без @) или ID пользователя для поиска:", reply_markup=back_to_menu_button())
        return

    if data == "admin_setrank":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "setrank"
        await query.edit_message_text("Введите ID пользователя и новый ранг (bronze/silver/gold/admin) через пробел.\nНапример: <code>123456789 gold</code>", parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "admin_grant":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "grant"
        await query.edit_message_text("Введите ID пользователя, которому нужно дать права администратора:", reply_markup=back_to_menu_button())
        return

    if data == "admin_revoke":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "revoke"
        await query.edit_message_text("Введите ID пользователя, у которого забрать админку:", reply_markup=back_to_menu_button())
        return

    if data == "admin_setquota":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "setquota"
        await query.edit_message_text("Введите ID пользователя и новый дневной лимит через пробел.\nНапример: <code>123456789 50</code>", reply_markup=back_to_menu_button())
        return

    if data == "admin_give_permanent":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "give_permanent"
        await query.edit_message_text("Введите ID пользователя и количество баллов через пробел.\nНапример: <code>123456789 10</code>", parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "admin_give_image":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "give_image"
        await query.edit_message_text("Введите ID пользователя и количество баллов на картинки через пробел.\nНапример: <code>123456789 5</code>", parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "admin_give_video":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "give_video"
        await query.edit_message_text("Введите ID пользователя и количество баллов на видео через пробел.\nНапример: <code>123456789 5</code>", parse_mode="HTML", reply_markup=back_to_menu_button())
        return

    if data == "admin_toggle_keymode":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        settings["use_keys_until_error"] = not settings.get("use_keys_until_error", False)
        await save_settings(settings)
        kb = await get_admin_keyboard()
        await query.edit_message_text("✅ Режим ключей изменён.", reply_markup=kb)
        return

    if data == "admin_toggle_markdown":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        current = settings.get("markdown_formatting", False)
        if not current: settings["strip_formatting"] = False
        settings["markdown_formatting"] = not current
        await save_settings(settings)
        kb = await get_admin_keyboard()
        await query.edit_message_text(f"✅ Режим Markdown-форматирования {'включён' if settings['markdown_formatting'] else 'выключён'}.", reply_markup=kb)
        return

    if data == "admin_toggle_strip":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        current = settings.get("strip_formatting", False)
        if not current: settings["markdown_formatting"] = False
        settings["strip_formatting"] = not current
        await save_settings(settings)
        kb = await get_admin_keyboard()
        await query.edit_message_text(f"✅ Режим чистого текста {'включён' if settings['strip_formatting'] else 'выключён'}.", reply_markup=kb)
        return

    if data == "admin_reasoning_menu":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        text = (f"<b>🧠 Режим рассуждения</b>\n\n"
                f"Включен: {'✅' if settings['reasoning_enabled'] else '❌'}\n"
                f"Заблокирован: {'🔒' if settings['reasoning_blocked'] else '🔓'}\n"
                f"Промт:\n<code>{escape_html(settings['reasoning_prompt'])}</code>")
        kb = await get_reasoning_settings_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "reasoning_toggle":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        settings["reasoning_enabled"] = not settings.get("reasoning_enabled", False)
        await save_settings(settings)
        text = (f"<b>🧠 Режим рассуждения</b>\n\n"
                f"Включен: {'✅' if settings['reasoning_enabled'] else '❌'}\n"
                f"Заблокирован: {'🔒' if settings['reasoning_blocked'] else '🔓'}\n"
                f"Промт:\n<code>{escape_html(settings['reasoning_prompt'])}</code>")
        kb = await get_reasoning_settings_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "reasoning_block":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        settings["reasoning_blocked"] = not settings.get("reasoning_blocked", False)
        await save_settings(settings)
        text = (f"<b>🧠 Режим рассуждения</b>\n\n"
                f"Включен: {'✅' if settings['reasoning_enabled'] else '❌'}\n"
                f"Заблокирован: {'🔒' if settings['reasoning_blocked'] else '🔓'}\n"
                f"Промт:\n<code>{escape_html(settings['reasoning_prompt'])}</code>")
        kb = await get_reasoning_settings_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "reasoning_edit":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "edit_reasoning_prompt"
        await query.edit_message_text("Отправьте новый текст промта для режима рассуждения:", reply_markup=back_to_menu_button())
        return

    if data == "admin_constant_menu":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        text = (f"<b>📌 Постоянный промт</b>\n\n"
                f"Включен: {'✅' if settings['constant_prompt_enabled'] else '❌'}\n"
                f"Промт:\n<code>{escape_html(settings['constant_prompt_text'])}</code>")
        kb = await get_constant_prompt_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "constant_toggle":
        if not user_data.get("is_admin"): return
        settings = await load_settings()
        settings["constant_prompt_enabled"] = not settings.get("constant_prompt_enabled", False)
        await save_settings(settings)
        text = (f"<b>📌 Постоянный промт</b>\n\n"
                f"Включен: {'✅' if settings['constant_prompt_enabled'] else '❌'}\n"
                f"Промт:\n<code>{escape_html(settings['constant_prompt_text'])}</code>")
        kb = await get_constant_prompt_keyboard()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "constant_edit":
        if not user_data.get("is_admin"): return
        context.user_data["admin_action"] = "edit_constant_prompt"
        await query.edit_message_text("Отправьте новый текст постоянного промта:", reply_markup=back_to_menu_button())
        return

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    action = context.user_data["admin_action"]
    text = update.message.text.strip()
    args = text.split()
    user_id = update.effective_user.id
    users = await load_users()
    admin_data = await get_user(user_id, users)
    if not admin_data.get("is_admin"):
        context.user_data.pop("admin_action", None)
        return

    if action == "find_user":
        if len(args) == 0:
            await update.message.reply_text("❌ Введите username или ID.")
            return
        query = args[0]
        found = None
        if query.isdigit():
            uid = query
            if uid in users: found = users[uid]
        else:
            for uid, udata in users.items():
                if udata.get("username", "").lower() == query.lower():
                    found = udata
                    break
        if found:
            rank = found.get("rank", "?")
            used = found.get("daily_used", 0)
            quota = found.get("total_quota", RANK_DAILY_QUOTA.get(rank, 0))
            permanent = found.get("permanent_balance", 0)
            image_bal = found.get("image_balance", 0)
            video_bal = found.get("video_balance", 0)
            model = found.get("model", DEFAULT_MODEL)
            await update.message.reply_text(
                f"<b>👤 Пользователь</b>\n"
                f"ID: <code>{uid}</code>\n"
                f"Username: @{escape_html(found.get('username', 'нет'))}\n"
                f"Ранг: {rank}\n"
                f"Модель: {escape_html(AVAILABLE_MODELS.get(model, model))}\n"
                f"Использовано: {used}/{quota}\n"
                f"Постоянные баллы: {permanent}\n"
                f"Баллы на картинки: {image_bal}\n"
                f"Баллы на видео: {video_bal}\n"
                f"Админ: {'да' if found.get('is_admin') else 'нет'}",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ Пользователь не найден.")
        context.user_data.pop("admin_action")
        return

    elif action == "setrank":
        if len(args) < 2:
            await update.message.reply_text("❌ Укажите ID и ранг.")
            return
        uid, new_rank = args[0], args[1].lower()
        if uid not in users:
            await update.message.reply_text("❌ Пользователь не найден.")
            return
        if new_rank not in ["bronze", "silver", "gold", "admin"]:
            await update.message.reply_text("❌ Ранг должен быть bronze/silver/gold/admin.")
            return
        users[uid]["rank"] = new_rank
        if new_rank == "admin": users[uid]["is_admin"] = True
        await save_users(users)
        await update.message.reply_text(f"✅ Ранг пользователя {uid} изменён на {new_rank}.")
        context.user_data.pop("admin_action")
        return

    elif action == "grant":
        if len(args) < 1:
            await update.message.reply_text("❌ Укажите ID пользователя.")
            return
        uid = args[0]
        if uid not in users:
            await update.message.reply_text("❌ Пользователь не найден.")
            return
        users[uid]["is_admin"] = True
        await save_users(users)
        await update.message.reply_text(f"✅ Пользователю {uid} выданы права администратора.")
        context.user_data.pop("admin_action")
        return

    elif action == "revoke":
        if len(args) < 1:
            await update.message.reply_text("❌ Укажите ID пользователя.")
            return
        uid = args[0]
        if uid not in users:
            await update.message.reply_text("❌ Пользователь не найден.")
            return
        users[uid]["is_admin"] = False
        await save_users(users)
        await update.message.reply_text(f"✅ У пользователя {uid} отозваны права администратора.")
        context.user_data.pop("admin_action")
        return

    elif action == "setquota":
        if len(args) < 2:
            await update.message.reply_text("❌ Укажите ID и новый лимит.")
            return
        uid, quota_str = args[0], args[1]
        if uid not in users:
            await update.message.reply_text("❌ Пользователь не найден.")
            return
        try:
            quota = int(quota_str)
        except:
            await update.message.reply_text("❌ Лимит должен быть числом.")
            return
        users[uid]["total_quota"] = quota
        await save_users(users)
        await update.message.reply_text(f"✅ Для пользователя {uid} установлен дневной лимит {quota}.")
        context.user_data.pop("admin_action")
        return

    elif action == "give_permanent":
        if len(args) < 2:
            await update.message.reply_text("❌ Укажите ID и количество баллов.")
            return
        uid, amount_str = args[0], args[1]
        if uid not in users:
            await update.message.reply_text("❌ Пользователь не найден.")
            return
        try:
            amount = int(amount_str)
        except:
            await update.message.reply_text("❌ Количество должно быть числом.")
            return
        users[uid]["permanent_balance"] = users[uid].get("permanent_balance", 0) + amount
        await save_users(users)
        await update.message.reply_text(f"✅ Пользователю {uid} добавлено {amount} постоянных баллов.")
        context.user_data.pop("admin_action")
        return

    elif action == "give_image":
        if len(args) < 2:
            await update.message.reply_text("❌ Укажите ID и количество баллов на картинки.")
            return
        uid, amount_str = args[0], args[1]
        if uid not in users:
            await update.message.reply_text("❌ Пользователь не найден.")
            return
        try:
            amount = int(amount_str)
        except:
            await update.message.reply_text("❌ Количество должно быть числом.")
            return
        users[uid]["image_balance"] = users[uid].get("image_balance", 0) + amount
        await save_users(users)
        await update.message.reply_text(f"✅ Пользователю {uid} добавлено {amount} баллов на картинки.")
        context.user_data.pop("admin_action")
        return

    elif action == "give_video":
        if len(args) < 2:
            await update.message.reply_text("❌ Укажите ID и количество баллов на видео.")
            return
        uid, amount_str = args[0], args[1]
        if uid not in users:
            await update.message.reply_text("❌ Пользователь не найден.")
            return
        try:
            amount = int(amount_str)
        except:
            await update.message.reply_text("❌ Количество должно быть числом.")
            return
        users[uid]["video_balance"] = users[uid].get("video_balance", 0) + amount
        await save_users(users)
        await update.message.reply_text(f"✅ Пользователю {uid} добавлено {amount} баллов на видео.")
        context.user_data.pop("admin_action")
        return

    elif action == "edit_reasoning_prompt":
        settings = await load_settings()
        settings["reasoning_prompt"] = text
        await save_settings(settings)
        await update.message.reply_text("✅ Промт режима рассуждения обновлён.")
        context.user_data.pop("admin_action")
        kb = await get_reasoning_settings_keyboard()
        await update.message.reply_text("Возврат в меню рассуждений.", reply_markup=kb)
        return

    elif action == "edit_constant_prompt":
        settings = await load_settings()
        settings["constant_prompt_text"] = text
        await save_settings(settings)
        await update.message.reply_text("✅ Постоянный промт обновлён.")
        context.user_data.pop("admin_action")
        kb = await get_constant_prompt_keyboard()
        await update.message.reply_text("Возврат в меню постоянного промта.", reply_markup=kb)
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "admin_action" in context.user_data:
        await handle_admin_input(update, context)
        return
    if context.user_data.get("image_gen_mode"):
        await handle_image_generation(update, context)
        return
    if context.user_data.get("video_gen_mode"):
        await handle_video_generation(update, context)
        return
    if not context.user_data.get("chat_mode"):
        await update.message.reply_text("ℹ️ Чтобы начать общение, нажми «💬 Чат» в меню.", reply_markup=main_menu_keyboard())
        return

    user = update.effective_user
    users = await load_users()
    user_data = await get_user(user.id, users)
    reset_if_new_day(user_data)
    allowed, msg, use_permanent = can_use_model(user_data)
    if not allowed:
        await update.message.reply_text(msg)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    images_b64 = []
    if update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        image_bytes = await file.download_as_bytearray()
        images_b64.append(base64.b64encode(image_bytes).decode('utf-8'))

    history = context.user_data.get("chat_history", [])
    system_messages = []
    settings = await load_settings()
    if settings.get("constant_prompt_enabled") and settings.get("constant_prompt_text"):
        system_messages.append({"role": "system", "content": settings["constant_prompt_text"]})
    if context.user_data.get("reasoning_mode") and settings.get("reasoning_enabled") and not settings.get("reasoning_blocked"):
        if settings.get("reasoning_prompt"):
            system_messages.append({"role": "system", "content": settings["reasoning_prompt"]})

    user_msg = {"role": "user", "content": update.message.text or ""}
    messages = system_messages + history + [user_msg]

    model = user_data.get("model", DEFAULT_MODEL)
    rank = user_data["rank"]
    resp_data, key_idx, error = await try_request_with_keys(context, rank, messages, model, images=images_b64 if images_b64 else None)

    if error or resp_data is None:
        await update.message.reply_text(error or "❌ Неизвестная ошибка при запросе.")
        return

    answer = resp_data["choices"][0]["message"]["content"]

    stats = await load_stats()
    stats["used"][key_idx] += 1
    await save_stats(stats["used"])

    if use_permanent:
        user_data["permanent_balance"] -= 1
    else:
        user_data["daily_used"] += 1
    await save_users(users)

    history.append({"role": "assistant", "content": answer})
    if len(history) > 50:
        history = history[-50:]
    context.user_data["chat_history"] = history

    if settings.get("strip_formatting"):
        clean_answer = strip_markdown(answer)
        full_response = f"<b>Я:</b>\n{escape_html(clean_answer)}"
        parse_mode = "HTML"
    elif settings.get("markdown_formatting"):
        answer_html = markdown_to_html(answer)
        answer_html = re.sub(r'^<p>(.*?)</p>$', r'\1', answer_html, flags=re.DOTALL)
        answer_html = re.sub(r'</p>\n<p>', '\n\n', answer_html)
        full_response = f"<b>Я:</b>\n{answer_html}"
        parse_mode = "HTML"
    else:
        safe_answer = escape_html(answer)
        full_response = f"<b>Я:</b>\n{safe_answer}"
        parse_mode = "HTML"

    parts = split_long_message(full_response, max_length=4000)
    for i, part in enumerate(parts):
        if i == 0:
            await update.message.reply_text(part, parse_mode=parse_mode)
        else:
            await update.message.reply_text(f"<b>Продолжение:</b>\n{part}", parse_mode=parse_mode)

async def handle_image_generation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("❌ Промпт не может быть пустым.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)

    user_id = update.effective_user.id
    users = await load_users()
    user_data = await get_user(user_id, users)
    if user_data.get("image_balance", 0) <= 0:
        await update.message.reply_text("❌ У вас нет баллов на создание изображений.")
        context.user_data.pop("image_gen_mode", None)
        return
    user_data["image_balance"] -= 1
    await save_users(users)

    rank = user_data["rank"]
    key_indices = get_available_keys_for_rank(rank)
    if not key_indices:
        await update.message.reply_text("❌ Для вашего ранга нет доступных ключей.")
        return
    image_model = context.user_data.get("selected_image_model")
    if not image_model or image_model not in IMAGE_GEN_MODELS:
        await update.message.reply_text("❌ Модель не выбрана. Начните заново.")
        context.user_data.pop("image_gen_mode", None)
        return

    success = False
    for idx in key_indices:
        data, error = await generate_media(context, API_KEYS[idx], prompt, image_model)
        if error: continue
        if data:
            image_data = None
            image_url = None
            if data.get("choices") and len(data["choices"]) > 0:
                choice = data["choices"][0]
                if "images" in choice and len(choice["images"]) > 0:
                    img_info = choice["images"][0]
                    if img_info.get("type") == "image_url":
                        url = img_info.get("image_url", {}).get("url")
                        if url and url.startswith("data:image"):
                            base64_data = url.split(",", 1)[-1]
                            image_data = base64.b64decode(base64_data)
                        elif url: image_url = url
                if not image_data and not image_url:
                    content = choice.get("message", {}).get("content")
                    if content:
                        urls = re.findall(r'(https?://[^\s]+)', content)
                        if urls: image_url = urls[0]
                        b64_match = re.search(r'data:image/[^;]+;base64,([^"\']+)', content)
                        if b64_match: image_data = base64.b64decode(b64_match.group(1))
            if not image_data and not image_url and data.get("data") and len(data["data"]) > 0:
                item = data["data"][0]
                image_url = item.get("url")
                if not image_url and item.get("b64_json"):
                    image_data = base64.b64decode(item["b64_json"])
            if image_data:
                await update.message.reply_photo(photo=image_data, caption="Ваше изображение:")
            elif image_url:
                session = context.application.bot_data.get("http_session")
                if session:
                    try:
                        async with session.get(image_url) as img_resp:
                            if img_resp.status == 200:
                                img_data = await img_resp.read()
                                await update.message.reply_photo(photo=img_data, caption="Ваше изображение:")
                            else:
                                await update.message.reply_text(f"✅ Изображение сгенерировано, но не удалось скачать. Ссылка: {image_url}")
                    except:
                        await update.message.reply_text(f"✅ Изображение сгенерировано, ошибка загрузки. Ссылка: {image_url}")
                else:
                    await update.message.reply_text(f"✅ Изображение сгенерировано. Ссылка: {image_url}")
            else:
                debug_info = json.dumps(data, indent=2, ensure_ascii=False)[:500]
                await update.message.reply_text(f"✅ Запрос выполнен, но не удалось извлечь изображение.\nОтвет API (первые 500 символов):\n<code>{escape_html(debug_info)}</code>", parse_mode="HTML")
            stats = await load_stats()
            stats["used"][idx] += 1
            await save_stats(stats["used"])
            success = True
            break
    if not success:
        await update.message.reply_text("❌ Не удалось сгенерировать изображение. Попробуйте позже.")
    context.user_data.pop("image_gen_mode", None)
    context.user_data.pop("selected_image_model", None)

async def handle_video_generation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("❌ Промпт не может быть пустым.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)

    user_id = update.effective_user.id
    users = await load_users()
    user_data = await get_user(user_id, users)
    if user_data.get("video_balance", 0) <= 0:
        await update.message.reply_text("❌ У вас нет баллов на создание видео.")
        context.user_data.pop("video_gen_mode", None)
        return
    user_data["video_balance"] -= 1
    await save_users(users)

    rank = user_data["rank"]
    key_indices = get_available_keys_for_rank(rank)
    if not key_indices:
        await update.message.reply_text("❌ Для вашего ранга нет доступных ключей.")
        return
    video_model = context.user_data.get("selected_video_model")
    if not video_model or video_model not in VIDEO_GEN_MODELS:
        await update.message.reply_text("❌ Модель не выбрана. Начните заново.")
        context.user_data.pop("video_gen_mode", None)
        return

    success = False
    for idx in key_indices:
        data, error = await generate_media(context, API_KEYS[idx], prompt, video_model)
        if error: continue
        if data:
            video_url = None
            if data.get("data") and len(data["data"]) > 0:
                video_url = data["data"][0].get("url")
            elif data.get("choices") and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content")
                if content:
                    urls = re.findall(r'(https?://[^\s]+)', content)
                    if urls: video_url = urls[0]
            if video_url:
                await update.message.reply_text(f"🎥 Ваше видео сгенерировано: {video_url}")
            else:
                debug_info = json.dumps(data, indent=2, ensure_ascii=False)[:500]
                await update.message.reply_text(f"✅ Запрос выполнен, но не удалось извлечь видео.\nОтвет API (первые 500 символов):\n<code>{escape_html(debug_info)}</code>", parse_mode="HTML")
            stats = await load_stats()
            stats["used"][idx] += 1
            await save_stats(stats["used"])
            success = True
            break
    if not success:
        await update.message.reply_text("❌ Не удалось сгенерировать видео. Попробуйте позже.")
    context.user_data.pop("video_gen_mode", None)
    context.user_data.pop("selected_video_model", None)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_message(update, context)

# ================== ЗАПУСК БОТА В ОТДЕЛЬНОМ ПОТОКЕ ==================
async def post_init(application: Application) -> None:
    application.bot_data["http_session"] = aiohttp.ClientSession()

async def shutdown_bot(application: Application) -> None:
    session = application.bot_data.get("http_session")
    if session: await session.close()

def run_bot():
    """Запускает Telegram-бота в отдельном потоке."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app_bot = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("menu", menu))
    app_bot.add_handler(CommandHandler("cancel", cancel))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    loop.run_until_complete(app_bot.initialize())
    loop.run_until_complete(app_bot.start())
    loop.run_until_complete(app_bot.updater.start_polling())
    loop.run_forever()

# ================== АВТО-ПИНГ ДЛЯ ПОДДЕРЖАНИЯ АКТИВНОСТИ ==================
def ping_self():
    """Каждые 10 секунд отправляет GET-запрос на себя, чтобы Render не усыплял."""
    import urllib.request
    import urllib.error
    while True:
        try:
            url = f"https://{os.environ.get('RENDER_EXTERNAL_URL', 'localhost')}"
            req = urllib.request.urlopen(url, timeout=5)
            req.read()
        except Exception as e:
            pass  # не критично
        time.sleep(10)

# ================== ЗАПУСК ВСЕГО ==================
if __name__ == '__main__':
    # Запускаем бота в фоне
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Бот запущен в фоновом потоке")

    # Запускаем пинг-сервис
    ping_thread = threading.Thread(target=ping_self, daemon=True)
    ping_thread.start()
    print("✅ Авто-пинг запущен")

    # Запускаем веб-сервер
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)