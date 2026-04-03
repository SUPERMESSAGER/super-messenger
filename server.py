#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import secrets
import time
import re
import random
import threading
import shutil
from functools import wraps
from flask import Flask, request, jsonify, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import Json
from urllib.parse import urlparse

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# ---------- База данных (Neon PostgreSQL) ----------
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable not set")

def get_db_connection():
    conn_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    conn = psycopg2.connect(conn_url, sslmode='require')
    return conn

TEMP_IMAGES_DIR = 'temp_images'
os.makedirs(TEMP_IMAGES_DIR, exist_ok=True)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            plain_password TEXT,
            is_admin INTEGER DEFAULT 0,
            is_super_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            created_at INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            from_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            to_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            content TEXT,
            timestamp INTEGER,
            read INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS temp_images (
            id SERIAL PRIMARY KEY,
            file_name TEXT UNIQUE NOT NULL,
            expiry INTEGER NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            type TEXT CHECK(type IN ('group', 'channel')) NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            created_at INTEGER,
            is_active INTEGER DEFAULT 1
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS room_members (
            room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            role TEXT DEFAULT 'member',
            joined_at INTEGER,
            PRIMARY KEY (room_id, user_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS room_messages (
            id SERIAL PRIMARY KEY,
            room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
            from_id INTEGER REFERENCES users(id),
            content TEXT,
            timestamp INTEGER,
            read_by INTEGER[] DEFAULT '{}'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS room_requests (
            id SERIAL PRIMARY KEY,
            requester_id INTEGER REFERENCES users(id),
            room_id INTEGER REFERENCES rooms(id),
            type TEXT CHECK(type IN ('join', 'create')) NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at INTEGER
        )
    ''')
    
    # Предустановленные пользователи
    users_to_add = [
        ('123', '123', '123', 1, 1),
        ('321', '321', '321', 0, 0),
        ('sanya_play', 'Александр Журба', '3590', 1, 1),
        ('test1', 'Тест 1', 'test1', 0, 0),
        ('test2', 'Тест 2', 'test2', 0, 0)
    ]
    for username, display_name, password, is_admin, is_super_admin in users_to_add:
        c.execute("SELECT id FROM users WHERE username = %s", (username,))
        if not c.fetchone():
            pwd_hash = generate_password_hash(password)
            c.execute('''
                INSERT INTO users (username, display_name, password_hash, plain_password, is_admin, is_super_admin, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (username, display_name, pwd_hash, password, is_admin, is_super_admin, int(time.time())))
    conn.commit()
    conn.close()

init_db()

# ---------- Функции БД ----------
def get_user_by_username(username):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT id, username, display_name, password_hash, plain_password, is_admin, is_super_admin, is_banned
        FROM users WHERE username = %s
    ''', (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'id': row[0], 'username': row[1], 'display_name': row[2],
            'password_hash': row[3], 'plain_password': row[4],
            'is_admin': bool(row[5]), 'is_super_admin': bool(row[6]), 'is_banned': bool(row[7])
        }
    return None

def get_user_by_id(uid):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT id, username, display_name, is_admin, is_super_admin, is_banned
        FROM users WHERE id = %s
    ''', (uid,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'id': row[0], 'username': row[1], 'display_name': row[2],
            'is_admin': bool(row[3]), 'is_super_admin': bool(row[4]), 'is_banned': bool(row[5])
        }
    return None

def get_all_users():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT id, username, display_name, is_admin, is_super_admin, is_banned, created_at
        FROM users
    ''')
    rows = c.fetchall()
    conn.close()
    return [{
        'id': r[0], 'username': r[1], 'display_name': r[2],
        'is_admin': bool(r[3]), 'is_super_admin': bool(r[4]), 'is_banned': bool(r[5]), 'created_at': r[6]
    } for r in rows]

def save_message(from_id, to_id, content):
    conn = get_db_connection()
    c = conn.cursor()
    ts = int(time.time())
    c.execute('''
        INSERT INTO messages (from_id, to_id, content, timestamp, read)
        VALUES (%s, %s, %s, %s, 0)
    ''', (from_id, to_id, content, ts))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id, ts

def get_messages_between(user1_id, user2_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT id, from_id, to_id, content, timestamp, read
        FROM messages
        WHERE (from_id = %s AND to_id = %s) OR (from_id = %s AND to_id = %s)
        ORDER BY timestamp ASC
    ''', (user1_id, user2_id, user2_id, user1_id))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'from_id': r[1], 'to_id': r[2], 'content': r[3], 'timestamp': r[4], 'read': r[5]} for r in rows]

def mark_messages_read(user_id, other_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE messages SET read = 1
        WHERE to_id = %s AND from_id = %s
    ''', (user_id, other_id))
    conn.commit()
    conn.close()

def get_unread_counts(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT from_id, COUNT(*)
        FROM messages
        WHERE to_id = %s AND read = 0
        GROUP BY from_id
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def get_all_messages_exclude_bots():
    bot1 = get_user_by_username('test1')
    bot2 = get_user_by_username('test2')
    bot_ids = []
    if bot1:
        bot_ids.append(bot1['id'])
    if bot2:
        bot_ids.append(bot2['id'])
    
    conn = get_db_connection()
    c = conn.cursor()
    if bot_ids:
        c.execute('''
            SELECT id, from_id, to_id, content, timestamp
            FROM messages
            WHERE from_id NOT IN %s AND to_id NOT IN %s
            ORDER BY timestamp ASC
        ''', (tuple(bot_ids), tuple(bot_ids)))
    else:
        c.execute('SELECT id, from_id, to_id, content, timestamp FROM messages ORDER BY timestamp ASC')
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'from_id': r[1], 'to_id': r[2], 'content': r[3], 'timestamp': r[4]} for r in rows]

def ban_user(user_id, ban=True, admin_user=None):
    target = get_user_by_id(user_id)
    if target and target.get('is_super_admin'):
        return False
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = %s WHERE id = %s', (1 if ban else 0, user_id))
    conn.commit()
    conn.close()
    return True

def set_admin(user_id, admin=True, admin_user=None):
    target = get_user_by_id(user_id)
    if target and target.get('is_super_admin'):
        return False
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET is_admin = %s WHERE id = %s', (1 if admin else 0, user_id))
    conn.commit()
    conn.close()
    return True

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

# ---------- Функции для временных изображений ----------
def save_temp_image(file_data, original_filename):
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        return None
    filename = secrets.token_hex(16) + ext
    filepath = os.path.join(TEMP_IMAGES_DIR, filename)
    with open(filepath, 'wb') as f:
        f.write(file_data)
    expiry = int(time.time()) + 300
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT INTO temp_images (file_name, expiry) VALUES (%s, %s)', (filename, expiry))
    conn.commit()
    conn.close()
    return filename, expiry

def get_temp_image_info(filename):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT expiry FROM temp_images WHERE file_name = %s', (filename,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'expiry': row[0]}
    return None

def delete_temp_image(filename):
    filepath = os.path.join(TEMP_IMAGES_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('DELETE FROM temp_images WHERE file_name = %s', (filename,))
    conn.commit()
    conn.close()

def clean_expired_images():
    while True:
        time.sleep(60)
        now = int(time.time())
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT file_name FROM temp_images WHERE expiry <= %s', (now,))
        expired = c.fetchall()
        for (filename,) in expired:
            delete_temp_image(filename)
        conn.close()

threading.Thread(target=clean_expired_images, daemon=True).start()

# ---------- Функции для групп и каналов ----------
def create_room(name, room_type, owner_id=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO rooms (name, type, owner_id, created_at, is_active)
        VALUES (%s, %s, %s, %s, 1)
    ''', (name, room_type, owner_id, int(time.time())))
    room_id = c.lastrowid
    if owner_id is not None:
        c.execute('''
            INSERT INTO room_members (room_id, user_id, role, joined_at)
            VALUES (%s, %s, 'owner', %s)
        ''', (room_id, owner_id, int(time.time())))
    conn.commit()
    conn.close()
    return room_id

def add_member_to_room(room_id, user_id, role='member'):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO room_members (room_id, user_id, role, joined_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    ''', (room_id, user_id, role, int(time.time())))
    conn.commit()
    conn.close()

def get_room_by_name(name):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id, name, type, owner_id FROM rooms WHERE name = %s', (name,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'name': row[1], 'type': row[2], 'owner_id': row[3]}
    return None

def get_user_rooms(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT r.id, r.name, r.type, r.owner_id, u.username as owner_name
        FROM rooms r
        JOIN room_members rm ON r.id = rm.room_id
        LEFT JOIN users u ON r.owner_id = u.id
        WHERE rm.user_id = %s
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'name': r[1], 'type': r[2], 'owner_id': r[3], 'owner_name': r[4]} for r in rows]

def get_room_messages(room_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT rm.id, rm.from_id, rm.content, rm.timestamp, u.username, u.display_name
        FROM room_messages rm
        JOIN users u ON rm.from_id = u.id
        WHERE rm.room_id = %s
        ORDER BY rm.timestamp ASC
    ''', (room_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'from_id': r[1], 'content': r[2], 'timestamp': r[3], 'username': r[4], 'display_name': r[5]} for r in rows]

def save_room_message(room_id, from_id, content):
    conn = get_db_connection()
    c = conn.cursor()
    ts = int(time.time())
    c.execute('''
        INSERT INTO room_messages (room_id, from_id, content, timestamp, read_by)
        VALUES (%s, %s, %s, %s, '{}')
    ''', (room_id, from_id, content, ts))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id, ts

def get_room_unread_count(room_id, user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT COUNT(*)
        FROM room_messages
        WHERE room_id = %s AND NOT %s = ANY(read_by)
    ''', (room_id, user_id))
    count = c.fetchone()[0]
    conn.close()
    return count

def mark_room_messages_read(room_id, user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE room_messages
        SET read_by = array_append(read_by, %s)
        WHERE room_id = %s AND NOT %s = ANY(read_by)
    ''', (user_id, room_id, user_id))
    conn.commit()
    conn.close()

def add_room_request(requester_id, room_id, req_type):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO room_requests (requester_id, room_id, type, created_at)
        VALUES (%s, %s, %s, %s)
    ''', (requester_id, room_id, req_type, int(time.time())))
    conn.commit()
    conn.close()

def get_pending_room_requests():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT rr.id, rr.requester_id, u.username as requester_name,
               rr.room_id, r.name as room_name, rr.type, rr.created_at
        FROM room_requests rr
        JOIN users u ON rr.requester_id = u.id
        JOIN rooms r ON rr.room_id = r.id
        WHERE rr.status = 'pending'
    ''')
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'requester_id': r[1], 'requester_name': r[2], 'room_id': r[3],
             'room_name': r[4], 'type': r[5], 'created_at': r[6]} for r in rows]

def approve_room_request(request_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT requester_id, room_id FROM room_requests WHERE id = %s', (request_id,))
    row = c.fetchone()
    if row:
        add_member_to_room(row[1], row[0])
        c.execute('UPDATE room_requests SET status = %s WHERE id = %s', ('approved', request_id))
    conn.commit()
    conn.close()

def reject_room_request(request_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE room_requests SET status = %s WHERE id = %s', ('rejected', request_id))
    conn.commit()
    conn.close()

# ---------- Синхронизация из users.txt (каждую секунду) ----------
def sync_users_from_txt():
    txt_path = 'users.txt'
    if not os.path.exists(txt_path):
        return
    with open(txt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(':')
        if len(parts) < 5:
            continue
        username = parts[0].strip()
        display_name = parts[1].strip() if parts[1] else username
        plain_password = parts[2].strip()
        is_admin = int(parts[3]) if parts[3].isdigit() else 0
        is_super_admin = int(parts[4]) if parts[4].isdigit() else 0
        room_type = parts[5].strip() if len(parts) > 5 and parts[5] else None
        room_name = parts[6].strip() if len(parts) > 6 and parts[6] else None
        
        existing = get_user_by_username(username)
        if not existing:
            pwd_hash = generate_password_hash(plain_password)
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''
                INSERT INTO users (username, display_name, password_hash, plain_password, is_admin, is_super_admin, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (username, display_name, pwd_hash, plain_password, is_admin, is_super_admin, int(time.time())))
            user_id = c.lastrowid
            conn.commit()
            conn.close()
        else:
            user_id = existing['id']
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''
                UPDATE users SET display_name = %s, is_admin = %s, is_super_admin = %s
                WHERE id = %s
            ''', (display_name, is_admin, is_super_admin, user_id))
            conn.commit()
            conn.close()
        
        if room_type and room_name and room_type in ('group', 'channel'):
            room = get_room_by_name(room_name)
            if not room:
                create_room(room_name, room_type, user_id)
            else:
                add_member_to_room(room['id'], user_id, role='member' if room['owner_id'] != user_id else 'owner')

def sync_loop():
    while True:
        time.sleep(1)  # каждую секунду
        sync_users_from_txt()

threading.Thread(target=sync_loop, daemon=True).start()

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
        .btn-icon .unread-dot { position:absolute; top:-2px; right:-2px; width:12px; height:12px; background:#5e9bff; border-radius:50%; border:2px solid #16161d; display:none; }
        .auth-container { padding:30px 20px; max-width:400px; margin:auto; width:100%; }
        input { width:100%; padding:12px; background:#16161d; border:1px solid #2a2a33; border-radius:12px; color:#f0f0f5; margin-bottom:12px; outline:none; font-size:1rem; }
        button { background:#5e9bff; color:white; border:none; padding:12px; border-radius:30px; font-weight:600; cursor:pointer; width:100%; margin-bottom:10px; font-size:1rem; }
        button:active { transform:scale(0.97); }
        .btn-outline { background:transparent; border:1px solid #5e9bff; color:#5e9bff; }
        .main-layout { display:flex; flex:1; overflow:hidden; min-height:0; }
        .sidebar { width:280px; background:#16161d; border-right:1px solid #2a2a33; display:flex; flex-direction:column; overflow-y:auto; flex-shrink:0; transition:transform 0.3s; }
        .sidebar-header { padding:12px; border-bottom:1px solid #2a2a33; display:flex; justify-content:space-between; align-items:center; }
        .settings-btn { background:#22222c; border:none; color:#fff; padding:6px 12px; border-radius:20px; cursor:pointer; font-size:0.8rem; }
        .chat-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
        .search-bar { padding:12px; border-bottom:1px solid #2a2a33; }
        .search-bar input { margin:0; }
        .dialog-item { padding:12px 16px; border-bottom:1px solid #2a2a33; cursor:pointer; display:flex; justify-content:space-between; align-items:center; }
        .dialog-item:hover { background:#22222c; }
        .dialog-checkbox { margin-right:12px; width:20px; height:20px; cursor:pointer; }
        .dialog-name { font-weight:600; flex:1; }
        .admin-badge { color:gold; margin-left:5px; font-size:0.8rem; }
        .unread-dot { width:10px; height:10px; background:#5e9bff; border-radius:50%; display:inline-block; margin-left:8px; }
        .messages-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:75%; padding:8px 12px; border-radius:18px; background:#22222c; align-self:flex-start; word-wrap:break-word; }
        .message.own { background:#5e9bff; align-self:flex-end; }
        .message .text { font-size:0.95rem; }
        .message .time { font-size:0.6rem; text-align:right; margin-top:4px; opacity:0.7; color:#ccc; }
        .message .image-container { max-width:100%; margin-top:4px; position:relative; display:inline-block; }
        .message .image-container img { max-width:200px; max-height:200px; border-radius:12px; cursor:pointer; }
        .message .download-btn { background:#2a2a33; border:none; color:#5e9bff; padding:4px 8px; border-radius:12px; font-size:0.7rem; margin-top:4px; cursor:pointer; width:auto; display:inline-block; margin-right:8px; }
        .message .expiry-timer { font-size:0.6rem; color:#000; background:#fff; padding:2px 6px; border-radius:12px; display:inline-block; }
        .input-bar { padding:12px; background:#16161d; border-top:1px solid #2a2a33; display:flex; gap:10px; flex-shrink:0; margin-bottom:10px; padding-bottom:calc(12px + env(safe-area-inset-bottom, 0px)); }
        .input-bar input { flex:1; margin:0; }
        .input-bar button { width:auto; padding:12px 20px; margin:0; }
        .contact-info { padding:12px; border-bottom:1px solid #2a2a33; font-weight:bold; background:#1a1a22; display:flex; justify-content:space-between; align-items:center; }
        .open-btn { background:#5e9bff; color:white; border:none; padding:8px 16px; border-radius:30px; cursor:pointer; font-size:0.9rem; margin-left:12px; }
        .hidden { display:none !important; }
        .admin-panel { position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.9); z-index:1000; display:flex; justify-content:center; align-items:center; }
        .admin-panel-content { background:#16161d; width:90%; max-width:800px; max-height:80%; overflow:auto; border-radius:20px; padding:20px; }
        .admin-panel-content table { width:100%; border-collapse:collapse; }
        .admin-panel-content th, .admin-panel-content td { border:1px solid #2a2a33; padding:8px; text-align:left; }
        .admin-panel-content button { width:auto; margin:2px; padding:4px 8px; }
        .progress-container { width:100%; background:#2a2a33; border-radius:10px; margin:5px 0; }
        .progress-bar { width:0%; height:8px; background:#5e9bff; border-radius:10px; transition:width 0.3s; }
        @media (max-width:640px) {
            .sidebar { position:absolute; z-index:10; height:100%; transform:translateX(-100%); width:260px; }
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
            <button class="btn-icon" id="menuToggle" style="display:none;">☰ Чаты<span id="menuUnreadDot" class="unread-dot"></span></button>
            <button class="btn-icon" id="adminBtn" style="display:none;">⚙️ Админ</button>
            <button class="btn-icon" id="logoutBtn" style="display:none;">🚪 Выход</button>
        </div>
    </div>
    <div id="authScreen"><div class="auth-container"><h2>Вход в ALEX</h2><p style="color:#aaa; font-size:0.8rem; margin-bottom:12px;">Временный аккаунт: логин <strong>321</strong>, пароль <strong>321</strong></p><input type="text" id="loginUsername" placeholder="Username"><input type="password" id="loginPassword" placeholder="Пароль"><button id="loginBtn">Войти</button><button id="showRegisterBtn" class="btn-outline">Регистрация</button></div><div id="registerForm" class="hidden auth-container"><h2>Регистрация</h2><input type="text" id="regUsername" placeholder="Username (латиница, 4-32)"><input type="text" id="regDisplayName" placeholder="Как вас называть"><input type="password" id="regPassword" placeholder="Пароль"><button id="doRegisterBtn">Зарегистрироваться</button><button id="backToLoginBtn" class="btn-outline">Назад</button></div></div>
    <div id="mainScreen" class="hidden" style="flex:1; display:flex; flex-direction:column; min-height:0;"><div class="main-layout"><div class="sidebar" id="sidebar"><div class="sidebar-header"><span id="sidebarTitle">Диалоги</span><button class="open-btn" id="openBtn">Открыть</button><button class="settings-btn" id="settingsBtn">⚙️</button></div><div class="search-bar"><input type="text" id="searchInput" placeholder="Поиск @username или #канал"><button id="searchBtn" style="margin-top:8px;">Найти</button></div><div id="dialogsList" style="flex:1; overflow-y:auto;"></div></div><div class="chat-area"><div id="chatHeader" class="contact-info hidden"></div><div class="messages-area" id="messagesArea"></div><div class="input-bar" id="inputBar" style="display:none;"><input type="text" id="messageInput" placeholder="Сообщение..."><button id="attachBtn" style="width:auto; padding:12px;">📎</button><button id="sendMsgBtn">Отправить</button></div><div id="uploadProgress" class="progress-container hidden"><div class="progress-bar" id="uploadProgressBar"></div></div></div></div></div>
</div>
<script>
let currentUser=null, currentChatUser=null, currentRoom=null, currentTab='chats', dialogs=[], rooms=[], pollingIntervalChat=null, pollingIntervalRoom=null;
let showCrown = localStorage.getItem('showCrown') !== 'false';
let imageTimers = {};
let selectedId = null;  // id выбранного диалога или комнаты
let selectedType = null; // 'user' или 'room'
const authScreen=document.getElementById('authScreen'), mainScreen=document.getElementById('mainScreen');
const loginBtn=document.getElementById('loginBtn'), logoutBtn=document.getElementById('logoutBtn'), showRegisterBtn=document.getElementById('showRegisterBtn');
const registerForm=document.getElementById('registerForm'), backToLoginBtn=document.getElementById('backToLoginBtn'), doRegisterBtn=document.getElementById('doRegisterBtn');
const searchInput=document.getElementById('searchInput'), searchBtn=document.getElementById('searchBtn'), dialogsList=document.getElementById('dialogsList');
const chatHeader=document.getElementById('chatHeader'), messagesArea=document.getElementById('messagesArea'), inputBar=document.getElementById('inputBar');
const messageInput=document.getElementById('messageInput'), sendMsgBtn=document.getElementById('sendMsgBtn'), menuToggle=document.getElementById('menuToggle'), adminBtn=document.getElementById('adminBtn');
const attachBtn=document.getElementById('attachBtn'), settingsBtn=document.getElementById('settingsBtn'), openBtn=document.getElementById('openBtn');
const uploadProgressDiv=document.getElementById('uploadProgress'), uploadProgressBar=document.getElementById('uploadProgressBar');
let unreadMap={}, roomUnreadMap={};

function showToast(m){let t=document.createElement('div');t.innerText=m;t.style.position='fixed';t.style.bottom='20px';t.style.left='20px';t.style.right='20px';t.style.background='#333';t.style.color='#fff';t.style.padding='12px';t.style.borderRadius='30px';t.style.textAlign='center';t.style.zIndex='9999';document.body.appendChild(t);setTimeout(()=>t.remove(),2000);}
function escapeHtml(s){return s.replace(/[&<>]/g,function(m){if(m==='&')return '&amp;';if(m==='<')return '&lt;';if(m==='>')return '&gt;';return m;});}
function saveMessagesToCache(u,o,m){localStorage.setItem(`alex_msgs_${u}_${o}`,JSON.stringify(m));}
function loadMessagesFromCache(u,o){let raw=localStorage.getItem(`alex_msgs_${u}_${o}`);return raw?JSON.parse(raw):[];}
async function fetchMessagesFromServer(otherId){let r=await fetch(`/api/messages?with=${otherId}`);if(r.ok){let d=await r.json();return d.messages||[];}return[];}
async function fetchRoomMessages(roomId){let r=await fetch(`/api/room_messages?room_id=${roomId}`);if(r.ok){let d=await r.json();return d.messages||[];}return[];}

function renderMessage(msg, isOwn){
    let div=document.createElement('div');
    div.className=`message ${isOwn?'own':''}`;
    let timeStr=new Date(msg.timestamp*1000).toLocaleTimeString();
    let contentHtml='';
    let imgMatch=msg.content.match(/^\[img:(.+)\]$/);
    if(imgMatch){
        let fileId=imgMatch[1];
        contentHtml=`<div class="image-container" data-file-id="${fileId}" data-msg-id="${msg.id}"><img src="/api/image/${fileId}" onerror="this.onerror=null;this.parentElement.innerHTML='<span style=\\"color:#f55\\">Изображение удалено</span>'"><br><button class="download-btn" data-file-id="${fileId}">📥 Скачать</button><span class="expiry-timer" id="timer-${msg.id}"></span></div>`;
        div.innerHTML=`<div class="text">${contentHtml}</div><div class="time">${timeStr}</div>`;
        setTimeout(()=>startImageTimer(msg.id, fileId), 0);
    } else {
        contentHtml=escapeHtml(msg.content);
        div.innerHTML=`<div class="text">${contentHtml}</div><div class="time">${timeStr}</div>`;
    }
    return div;
}
function renderRoomMessage(msg){
    let div=document.createElement('div');
    let isOwn=(msg.from_id===currentUser.id);
    div.className=`message ${isOwn?'own':''}`;
    let timeStr=new Date(msg.timestamp*1000).toLocaleTimeString();
    let senderName=msg.display_name||msg.username;
    let contentHtml='';
    let imgMatch=msg.content.match(/^\[img:(.+)\]$/);
    if(imgMatch){
        let fileId=imgMatch[1];
        contentHtml=`<div class="image-container" data-file-id="${fileId}" data-msg-id="${msg.id}"><img src="/api/image/${fileId}" onerror="this.onerror=null;this.parentElement.innerHTML='<span style=\\"color:#f55\\">Изображение удалено</span>'"><br><button class="download-btn" data-file-id="${fileId}">📥 Скачать</button><span class="expiry-timer" id="timer-${msg.id}"></span></div>`;
        div.innerHTML=`<div><strong>${escapeHtml(senderName)}</strong></div><div class="text">${contentHtml}</div><div class="time">${timeStr}</div>`;
        setTimeout(()=>startImageTimer(msg.id, fileId), 0);
    } else {
        contentHtml=escapeHtml(msg.content);
        div.innerHTML=`<div><strong>${escapeHtml(senderName)}</strong></div><div class="text">${contentHtml}</div><div class="time">${timeStr}</div>`;
    }
    return div;
}
async function startImageTimer(msgId, fileId){
    if(imageTimers[msgId]) clearInterval(imageTimers[msgId]);
    async function updateTimer(){
        let r=await fetch(`/api/image_info/${fileId}`);
        if(r.ok){
            let data=await r.json();
            let now=Math.floor(Date.now()/1000);
            let remaining=data.expiry-now;
            let timerSpan=document.getElementById(`timer-${msgId}`);
            if(timerSpan){
                if(remaining<=0){
                    timerSpan.innerText=' (изображение удалено)';
                    clearInterval(imageTimers[msgId]);
                    let container=document.querySelector(`.image-container[data-msg-id="${msgId}"]`);
                    if(container) container.innerHTML='<span style="color:#f55">Изображение удалено по истечении 5 минут</span>';
                } else {
                    let minutes=Math.floor(remaining/60);
                    let seconds=remaining%60;
                    timerSpan.innerText=` удаление через ${minutes}:${seconds<10?'0'+seconds:seconds}`;
                }
            } else {
                clearInterval(imageTimers[msgId]);
            }
        } else {
            let timerSpan=document.getElementById(`timer-${msgId}`);
            if(timerSpan) timerSpan.innerText=' (изображение недоступно)';
            clearInterval(imageTimers[msgId]);
        }
    }
    await updateTimer();
    imageTimers[msgId]=setInterval(updateTimer, 1000);
}
function renderMessages(msgs){
    messagesArea.innerHTML='';
    msgs.forEach(msg=>{
        let isOwn=(msg.from_id===currentUser.id);
        let msgDiv=renderMessage(msg, isOwn);
        messagesArea.appendChild(msgDiv);
    });
    document.querySelectorAll('.download-btn').forEach(btn=>{
        btn.onclick=async (e)=>{
            e.stopPropagation();
            let fileId=btn.dataset.fileId;
            let a=document.createElement('a');
            a.href=`/api/image/${fileId}?download=1`;
            a.download='image.jpg';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        };
    });
    messagesArea.scrollTop=messagesArea.scrollHeight;
}
function renderRoomMessages(msgs){
    messagesArea.innerHTML='';
    msgs.forEach(msg=>{
        let msgDiv=renderRoomMessage(msg);
        messagesArea.appendChild(msgDiv);
    });
    document.querySelectorAll('.download-btn').forEach(btn=>{
        btn.onclick=async (e)=>{
            e.stopPropagation();
            let fileId=btn.dataset.fileId;
            let a=document.createElement('a');
            a.href=`/api/image/${fileId}?download=1`;
            a.download='image.jpg';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        };
    });
    messagesArea.scrollTop=messagesArea.scrollHeight;
}
async function openChat(user){
    if(currentRoom) currentRoom=null;
    currentChatUser=user;
    currentRoom=null;
    chatHeader.innerHTML=`<strong>${escapeHtml(user.display_name||user.username)}${user.is_admin && showCrown ? ' 👑' : ''}</strong> <span>@${user.username}</span>`;
    chatHeader.classList.remove('hidden');
    inputBar.style.display='flex';
    let serverMsgs=await fetchMessagesFromServer(user.id);
    saveMessagesToCache(currentUser.id,user.id,serverMsgs);
    renderMessages(serverMsgs);
    if(pollingIntervalRoom) clearInterval(pollingIntervalRoom);
    pollingIntervalChat=setInterval(async()=>{
        if(currentChatUser && currentChatUser.id===user.id){
            let newMsgs=await fetchMessagesFromServer(user.id);
            saveMessagesToCache(currentUser.id,user.id,newMsgs);
            renderMessages(newMsgs);
        }
    },5000);
    await fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({with_id:user.id})});
    await loadDialogs();
}
async function openRoom(room){
    if(currentChatUser) currentChatUser=null;
    currentRoom=room;
    chatHeader.innerHTML=`<strong>${escapeHtml(room.name)} (${room.type==='group'?'Группа':'Канал'})</strong> <span>${room.owner_name ? 'Владелец: '+escapeHtml(room.owner_name) : ''}</span>`;
    chatHeader.classList.remove('hidden');
    inputBar.style.display='flex';
    let serverMsgs=await fetchRoomMessages(room.id);
    renderRoomMessages(serverMsgs);
    if(pollingIntervalChat) clearInterval(pollingIntervalChat);
    pollingIntervalRoom=setInterval(async()=>{
        if(currentRoom && currentRoom.id===room.id){
            let newMsgs=await fetchRoomMessages(room.id);
            renderRoomMessages(newMsgs);
        }
    },5000);
    await fetch('/api/mark_room_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:room.id})});
    await loadRooms();
}
async function sendMessage(content){
    if(currentChatUser){
        let r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_username:currentChatUser.username,content:content})});
        if(r.ok){messageInput.value='';await loadDialogs();}
        else showToast('Ошибка');
    } else if(currentRoom){
        let r=await fetch('/api/send_room_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:currentRoom.id,content:content})});
        if(r.ok){messageInput.value='';await loadRooms();}
        else showToast('Ошибка');
    }
}
async function uploadAndSendImage(file){
    if(!currentChatUser && !currentRoom) return;
    let formData=new FormData();
    formData.append('image', file);
    uploadProgressDiv.classList.remove('hidden');
    let xhr=new XMLHttpRequest();
    xhr.open('POST', '/api/upload_image', true);
    xhr.upload.onprogress=function(e){
        if(e.lengthComputable){
            let percent=(e.loaded/e.total)*100;
            uploadProgressBar.style.width=percent+'%';
        }
    };
    xhr.onload=async function(){
        uploadProgressDiv.classList.add('hidden');
        uploadProgressBar.style.width='0%';
        if(xhr.status===200){
            let data=JSON.parse(xhr.responseText);
            await sendMessage(`[img:${data.file_id}]`);
        } else {
            showToast('Ошибка загрузки изображения');
        }
    };
    xhr.onerror=function(){uploadProgressDiv.classList.add('hidden');showToast('Ошибка сети');};
    xhr.send(formData);
}
attachBtn.onclick=()=>{
    let input=document.createElement('input');
    input.type='file';
    input.accept='image/*';
    input.onchange=async (e)=>{
        if(e.target.files.length) await uploadAndSendImage(e.target.files[0]);
    };
    input.click();
};
function updateMenuUnreadDot() {
    let totalUnread = Object.values(unreadMap).reduce((sum, count) => sum + count, 0);
    let dot = document.getElementById('menuUnreadDot');
    if (dot) dot.style.display = totalUnread > 0 ? 'block' : 'none';
}
async function loadDialogs(){
    let r=await fetch('/api/dialogs');
    if(r.ok){
        let data=await r.json();
        dialogs=data.dialogs;
        let unread=await fetch('/api/unread').then(r=>r.json());
        unreadMap=unread;
        renderDialogs();
        updateMenuUnreadDot();
    }
}
function renderDialogs(){
    if(!dialogs.length){dialogsList.innerHTML='<div style="padding:12px; color:#aaa;">Нет диалогов</div>';return;}
    dialogsList.innerHTML='';
    dialogs.forEach(d=>{
        let div=document.createElement('div');
        div.className='dialog-item';
        let isChecked = (selectedType==='user' && selectedId===d.id);
        let unreadHtml=unreadMap[d.id]?`<span class="unread-dot"></span>`:'';
        let crownHtml = (d.is_admin && showCrown) ? '<span class="admin-badge">👑</span>' : '';
        div.innerHTML = `
            <input type="checkbox" class="dialog-checkbox" data-type="user" data-id="${d.id}" ${isChecked ? 'checked' : ''}>
            <div class="dialog-name">${escapeHtml(d.display_name||d.username)}${crownHtml}<div style="font-size:0.7rem;">@${d.username}</div></div>
            ${unreadHtml}
        `;
        div.querySelector('.dialog-checkbox').addEventListener('change', (e) => {
            if(e.target.checked){
                selectedId = d.id;
                selectedType = 'user';
                document.querySelectorAll('.dialog-checkbox').forEach(cb => cb.checked = false);
                e.target.checked = true;
            } else {
                if(selectedId===d.id && selectedType==='user') { selectedId=null; selectedType=null; }
            }
        });
        dialogsList.appendChild(div);
    });
}
async function loadRooms(){
    let r=await fetch('/api/user_rooms');
    if(r.ok){
        let data=await r.json();
        rooms=data.rooms;
        let unreadPromises=rooms.map(async room=>{
            let ur=await fetch(`/api/room_unread?room_id=${room.id}`);
            let json=await ur.json();
            return {id:room.id, count:json.count};
        });
        let unreadCounts=await Promise.all(unreadPromises);
        roomUnreadMap={};
        unreadCounts.forEach(uc=>{roomUnreadMap[uc.id]=uc.count;});
        if(currentTab==='channels') renderChannels();
        else if(currentTab==='groups') renderGroups();
        updateRoomUnreadDot();
    }
}
function renderChannels(){
    let channels=rooms.filter(r=>r.type==='channel');
    if(!channels.length){dialogsList.innerHTML='<div style="padding:12px; color:#aaa;">Нет каналов</div>';return;}
    dialogsList.innerHTML='';
    channels.forEach(ch=>{
        let div=document.createElement('div');
        div.className='dialog-item';
        let isChecked = (selectedType==='room' && selectedId===ch.id);
        let unreadHtml=roomUnreadMap[ch.id]?`<span class="unread-dot"></span>`:'';
        div.innerHTML = `
            <input type="checkbox" class="dialog-checkbox" data-type="room" data-id="${ch.id}" ${isChecked ? 'checked' : ''}>
            <div class="dialog-name">${escapeHtml(ch.name)}<div style="font-size:0.7rem;">канал</div></div>
            ${unreadHtml}
        `;
        div.querySelector('.dialog-checkbox').addEventListener('change', (e) => {
            if(e.target.checked){
                selectedId = ch.id;
                selectedType = 'room';
                document.querySelectorAll('.dialog-checkbox').forEach(cb => cb.checked = false);
                e.target.checked = true;
            } else {
                if(selectedId===ch.id && selectedType==='room') { selectedId=null; selectedType=null; }
            }
        });
        dialogsList.appendChild(div);
    });
}
function renderGroups(){
    let groups=rooms.filter(r=>r.type==='group');
    if(!groups.length){dialogsList.innerHTML='<div style="padding:12px; color:#aaa;">Нет групп</div>';return;}
    dialogsList.innerHTML='';
    groups.forEach(gr=>{
        let div=document.createElement('div');
        div.className='dialog-item';
        let isChecked = (selectedType==='room' && selectedId===gr.id);
        let unreadHtml=roomUnreadMap[gr.id]?`<span class="unread-dot"></span>`:'';
        div.innerHTML = `
            <input type="checkbox" class="dialog-checkbox" data-type="room" data-id="${gr.id}" ${isChecked ? 'checked' : ''}>
            <div class="dialog-name">${escapeHtml(gr.name)}<div style="font-size:0.7rem;">группа</div></div>
            ${unreadHtml}
        `;
        div.querySelector('.dialog-checkbox').addEventListener('change', (e) => {
            if(e.target.checked){
                selectedId = gr.id;
                selectedType = 'room';
                document.querySelectorAll('.dialog-checkbox').forEach(cb => cb.checked = false);
                e.target.checked = true;
            } else {
                if(selectedId===gr.id && selectedType==='room') { selectedId=null; selectedType=null; }
            }
        });
        dialogsList.appendChild(div);
    });
}
function updateRoomUnreadDot(){
    let totalUnread = 0;
    if(currentTab==='channels') totalUnread = rooms.filter(r=>r.type==='channel').reduce((s,ch)=>s+(roomUnreadMap[ch.id]||0),0);
    else if(currentTab==='groups') totalUnread = rooms.filter(r=>r.type==='group').reduce((s,gr)=>s+(roomUnreadMap[gr.id]||0),0);
    let dot = document.getElementById('menuUnreadDot');
    if(dot) dot.style.display = totalUnread>0 ? 'block' : 'none';
}
async function searchUserOrRoom(query){
    if(query.startsWith('#')){
        let roomName = query.substring(1);
        let r=await fetch(`/api/search_room?name=${encodeURIComponent(roomName)}`);
        let data=await r.json();
        if(data.room){
            if(confirm(`Перейти в ${data.room.name} (${data.room.type})?`)){
                // Добавляем комнату в список, если её там нет
                if(!rooms.some(r=>r.id===data.room.id)){
                    rooms.push(data.room);
                    if(currentTab==='channels' && data.room.type==='channel') renderChannels();
                    else if(currentTab==='groups' && data.room.type==='group') renderGroups();
                }
                openRoom(data.room);
            }
        } else showToast('Комната не найдена');
    } else {
        let username=query;
        if(!username.startsWith('@')) username='@'+username;
        let clean=username.substring(1);
        let r=await fetch(`/api/search?q=${encodeURIComponent(clean)}`);
        let data=await r.json();
        if(data.user){
            if(confirm(`Начать чат с ${data.user.display_name||data.user.username}?`)){
                if(!dialogs.some(d=>d.id===data.user.id)){
                    dialogs.unshift(data.user);
                    if(currentTab==='chats') renderDialogs();
                }
                openChat(data.user);
            }
        } else showToast('Пользователь не найден');
    }
}
openBtn.onclick=()=>{
    if(!selectedId || !selectedType) { showToast('Выберите чат/канал/группу'); return; }
    if(selectedType==='user'){
        let user = dialogs.find(d=>d.id===selectedId);
        if(user) openChat(user);
    } else if(selectedType==='room'){
        let room = rooms.find(r=>r.id===selectedId);
        if(room) openRoom(room);
    }
};
async function openAdminPanel(){
    let users=await(await fetch('/api/admin/users')).json();
    let allMessages=await(await fetch('/api/admin/messages')).json();
    let requests=await(await fetch('/api/admin/requests')).json();  // нет заявок, но оставим для совместимости
    let roomRequests=await(await fetch('/api/admin/room_requests')).json();
    let html=`<div class="admin-panel"><div class="admin-panel-content"><h3>Админ-панель</h3><button id="syncUsersBtn">🔄 Синхронизировать users.txt</button><button id="toggleCrownBtn">${showCrown ? 'Скрыть мою коронку' : 'Показать мою коронку'}</button><hr><h4>Пользователи</h4>表胖<th>ID</th><th>Username</th><th>Имя</th><th>Админ</th><th>Бан</th><th>Действия</th></tr>`;
    for(let u of users){
        html+=`<tr> <td>${u.id}</td> <td>${escapeHtml(u.username)}</td> <td>${escapeHtml(u.display_name)}</td> <td>${u.is_admin?'✅':'❌'}</td> <td>${u.is_banned?'🔴':'🟢'}</td> <td>${!u.is_super_admin?`<button class="setAdminBtn" data-id="${u.id}" data-admin="${!u.is_admin}">${u.is_admin?'Снять админа':'Назначить админа'}</button><button class="banBtn" data-id="${u.id}" data-ban="${!u.is_banned}">${u.is_banned?'Разбанить':'Забанить'}</button>`:'<i>Суперадмин</i>'}</td> </tr>`;
    }
    html+=`</tr><hr><h4>Заявки на создание групп/каналов</h4>表胖<th>Пользователь</th><th>Название</th><th>Тип</th><th>Дата</th><th>Действие</th></tr>`;
    for(let rr of roomRequests){
        html+=`<tr> <td>${escapeHtml(rr.requester_name)}</td> <td>${escapeHtml(rr.room_name)}</td> <td>${rr.type}</td> <td>${new Date(rr.created_at*1000).toLocaleString()}</td> <td><button class="approveRoomReqBtn" data-reqid="${rr.id}">✅ Одобрить</button><button class="rejectRoomReqBtn" data-reqid="${rr.id}">❌ Отклонить</button></td> </tr>`;
    }
    html+=`<tr><hr><h4>Все сообщения (без ботов)</h4>表胖<th>От</th><th>Кому</th><th>Текст</th><th>Время</th></tr>`;
    for(let m of allMessages){
        let fromUser=users.find(u=>u.id===m.from_id);
        let toUser=users.find(u=>u.id===m.to_id);
        if(fromUser && (fromUser.username==='test1' || fromUser.username==='test2')) continue;
        if(toUser && (toUser.username==='test1' || toUser.username==='test2')) continue;
        html+=`<tr> <td>${fromUser?fromUser.username:'?'}</td> <td>${toUser?toUser.username:'?'}</td> <td>${escapeHtml(m.content)}</td> <td>${new Date(m.timestamp*1000).toLocaleString()}</td> </tr>`;
    }
    html+=`</table><br><button id="closeAdminBtn">Закрыть</button></div></div>`;
    document.body.insertAdjacentHTML('beforeend',html);
    document.getElementById('syncUsersBtn').onclick=async()=>{
        let r=await fetch('/api/admin/sync_users',{method:'POST'});
        let data=await r.json();
        showToast(data.status==='ok'?'Синхронизация выполнена':'Ошибка');
        document.querySelector('.admin-panel').remove();
        openAdminPanel();
    };
    document.getElementById('toggleCrownBtn').onclick=()=>{showCrown=!showCrown;localStorage.setItem('showCrown',showCrown);updateCrownVisibility();document.querySelector('.admin-panel').remove();openAdminPanel();};
    document.querySelectorAll('.setAdminBtn').forEach(btn=>{btn.onclick=async()=>{let userId=btn.dataset.id,isAdmin=btn.dataset.admin==='true';await fetch('/api/admin/set_admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:parseInt(userId),is_admin:isAdmin})});location.reload();};});
    document.querySelectorAll('.banBtn').forEach(btn=>{btn.onclick=async()=>{let userId=btn.dataset.id,ban=btn.dataset.ban==='true';await fetch('/api/admin/ban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:parseInt(userId),ban:ban})});location.reload();};});
    document.querySelectorAll('.approveRoomReqBtn').forEach(btn=>{btn.onclick=async()=>{let reqId=btn.dataset.reqid;await fetch('/api/admin/approve_room_request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:parseInt(reqId)})});document.querySelector('.admin-panel').remove();openAdminPanel();};});
    document.querySelectorAll('.rejectRoomReqBtn').forEach(btn=>{btn.onclick=async()=>{let reqId=btn.dataset.reqid;await fetch('/api/admin/reject_room_request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:parseInt(reqId)})});document.querySelector('.admin-panel').remove();openAdminPanel();};});
    document.getElementById('closeAdminBtn').onclick=()=>document.querySelector('.admin-panel').remove();
}
function updateCrownVisibility(){
    if(currentTab==='chats') renderDialogs();
    if(currentChatUser){
        chatHeader.innerHTML=`<strong>${escapeHtml(currentChatUser.display_name||currentChatUser.username)}${currentChatUser.is_admin && showCrown ? ' 👑' : ''}</strong> <span>@${currentChatUser.username}</span>`;
    }
}
function switchTab(tab){
    currentTab=tab;
    document.getElementById('sidebarTitle').innerText = tab==='chats' ? 'Диалоги' : (tab==='channels' ? 'Каналы' : 'Группы');
    selectedId = null;
    selectedType = null;
    if(tab==='chats'){ loadDialogs(); }
    else if(tab==='channels'){ loadRooms(); renderChannels(); }
    else if(tab==='groups'){ loadRooms(); renderGroups(); }
    document.getElementById('sidebar').classList.remove('open');
}
async function afterLogin(user){
    currentUser=user;
    sessionStorage.setItem('alex_user',JSON.stringify(user));
    authScreen.classList.add('hidden');
    mainScreen.classList.remove('hidden');
    logoutBtn.style.display='inline-block';
    menuToggle.style.display='inline-block';
    if(user.is_admin) adminBtn.style.display='inline-block';
    await loadDialogs();
    await loadRooms();
    menuToggle.onclick=()=>document.getElementById('sidebar').classList.toggle('open');
    adminBtn.onclick=openAdminPanel;
    settingsBtn.onclick=()=>{
        let roomName=prompt('Название канала/группы:');
        if(roomName){
            let type=prompt('Тип: channel или group');
            if(type==='channel'||type==='group'){
                fetch('/api/request_room',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:roomName,type:type})})
                .then(r=>r.json()).then(data=>{if(data.status==='ok') showToast('Заявка отправлена админу');else showToast('Ошибка');});
            }else showToast('Неверный тип');
        }
    };
    document.addEventListener('click',function(e){
        let sidebar=document.getElementById('sidebar');
        if(window.innerWidth<=640 && sidebar.classList.contains('open')){
            if(!sidebar.contains(e.target) && e.target!==menuToggle && !menuToggle.contains(e.target)){
                sidebar.classList.remove('open');
            }
        }
    });
}
let navDiv = document.createElement('div');
navDiv.className = 'nav-buttons';
navDiv.innerHTML = `
    <button class="nav-btn active" data-tab="chats">Чаты</button>
    <button class="nav-btn" data-tab="channels">Каналы</button>
    <button class="nav-btn" data-tab="groups">Группы</button>
`;
document.querySelector('.header div:first-child').after(navDiv);
document.querySelectorAll('.nav-btn').forEach(btn=>{
    btn.addEventListener('click',()=>{
        document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        switchTab(btn.dataset.tab);
    });
});
doRegisterBtn.onclick=async()=>{
    let username=document.getElementById('regUsername').value.trim();
    let display_name=document.getElementById('regDisplayName').value.trim()||username;
    let password=document.getElementById('regPassword').value;
    if(!username||!password){showToast('Заполните все поля');return;}
    if(!/^[a-zA-Z0-9_]{4,32}$/.test(username)){showToast('Username 4-32 буквы/цифры/_');return;}
    let r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,display_name,password})});
    let data=await r.json();
    if(r.ok){showToast('Регистрация успешна, теперь войдите');backToLoginBtn.click();}
    else showToast(data.error);
};
loginBtn.onclick=async()=>{
    let username=document.getElementById('loginUsername').value.trim();
    let password=document.getElementById('loginPassword').value;
    if(!username||!password){showToast('Введите username и пароль');return;}
    let r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
    let data=await r.json();
    if(r.ok)await afterLogin(data.user);
    else showToast(data.error);
};
logoutBtn.onclick=async()=>{
    await fetch('/api/logout',{method:'POST'});
    if(pollingIntervalChat)clearInterval(pollingIntervalChat);
    if(pollingIntervalRoom)clearInterval(pollingIntervalRoom);
    sessionStorage.clear();
    location.reload();
};
showRegisterBtn.onclick=()=>{
    document.querySelector('.auth-container').classList.add('hidden');
    registerForm.classList.remove('hidden');
};
backToLoginBtn.onclick=()=>{
    registerForm.classList.add('hidden');
    document.querySelector('.auth-container').classList.remove('hidden');
};
searchBtn.onclick=()=>{
    let q=searchInput.value.trim();
    if(q) searchUserOrRoom(q);
};
searchInput.addEventListener('keypress',(e)=>{if(e.key==='Enter')searchBtn.click();});
sendMsgBtn.onclick=()=>{
    let content=messageInput.value.trim();
    if(content&&(currentChatUser||currentRoom)) sendMessage(content);
};
messageInput.addEventListener('keypress',(e)=>{if(e.key==='Enter')sendMsgBtn.click();});
let saved=sessionStorage.getItem('alex_user');
if(saved){let user=JSON.parse(saved);afterLogin(user);}
</script>
</body>
</html>'''

# ---------- API маршруты ----------
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username, display_name, password = data.get('username'), data.get('display_name', username), data.get('password')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if not re.match(r'^[a-zA-Z0-9_]{4,32}$', username):
        return jsonify({'error': 'Username 4-32 letters/digits/_'}), 400
    if get_user_by_username(username):
        return jsonify({'error': 'Username already exists'}), 409
    pwd_hash = generate_password_hash(password)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO users (username, display_name, password_hash, plain_password, created_at)
        VALUES (%s, %s, %s, %s, %s)
    ''', (username, display_name, pwd_hash, password, int(time.time())))
    conn.commit()
    conn.close()
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
    return jsonify({'status': 'ok', 'user': {
        'id': user['id'], 'username': user['username'],
        'display_name': user['display_name'], 'is_admin': user['is_admin']
    }})

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
    return jsonify({'user': {
        'id': target['id'], 'username': target['username'],
        'display_name': target['display_name'], 'is_admin': target['is_admin']
    }})

@app.route('/api/search_room', methods=['GET'])
@login_required
def search_room(user):
    name = request.args.get('name', '')
    if len(name) < 2:
        return jsonify({'room': None})
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id, name, type, owner_id FROM rooms WHERE name = %s AND is_active = 1', (name,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({'room': {'id': row[0], 'name': row[1], 'type': row[2], 'owner_id': row[3]}})
    return jsonify({'room': None})

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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT from_id, to_id FROM messages
        WHERE from_id = %s OR to_id = %s
    ''', (user['id'], user['id']))
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

@app.route('/api/unread', methods=['GET'])
@login_required
def unread(user):
    return jsonify(get_unread_counts(user['id']))

@app.route('/api/mark_read', methods=['POST'])
@login_required
def mark_read(user):
    data = request.json
    with_id = data.get('with_id')
    if with_id:
        mark_messages_read(user['id'], with_id)
    return jsonify({'status': 'ok'})

# ---------- API для изображений ----------
@app.route('/api/upload_image', methods=['POST'])
@login_required
def upload_image(user):
    if 'image' not in request.files:
        return jsonify({'error': 'No image file'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    file_data = file.read()
    filename, expiry = save_temp_image(file_data, file.filename)
    if not filename:
        return jsonify({'error': 'Unsupported image format'}), 400
    return jsonify({'file_id': filename, 'expiry': expiry})

@app.route('/api/image/<file_id>')
def get_image(file_id):
    info = get_temp_image_info(file_id)
    if not info or info['expiry'] < int(time.time()):
        return jsonify({'error': 'Image expired or not found'}), 404
    filepath = os.path.join(TEMP_IMAGES_DIR, file_id)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    download = request.args.get('download') == '1'
    return send_file(filepath, mimetype='image/jpeg', as_attachment=download, download_name='image.jpg')

@app.route('/api/image_info/<file_id>')
def image_info(file_id):
    info = get_temp_image_info(file_id)
    if not info:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'expiry': info['expiry']})

# ---------- API для групп и каналов ----------
@app.route('/api/user_rooms', methods=['GET'])
@login_required
def user_rooms(user):
    rooms = get_user_rooms(user['id'])
    return jsonify({'rooms': rooms})

@app.route('/api/room_messages', methods=['GET'])
@login_required
def room_messages(user):
    room_id = request.args.get('room_id', type=int)
    if not room_id:
        return jsonify({'error': 'Missing room_id'}), 400
    msgs = get_room_messages(room_id)
    return jsonify({'messages': msgs})

@app.route('/api/send_room_message', methods=['POST'])
@login_required
def send_room_message(user):
    data = request.json
    room_id = data.get('room_id')
    content = data.get('content')
    if not room_id or not content:
        return jsonify({'error': 'Missing parameters'}), 400
    save_room_message(room_id, user['id'], content)
    return jsonify({'status': 'ok', 'timestamp': int(time.time())})

@app.route('/api/room_unread', methods=['GET'])
@login_required
def room_unread(user):
    room_id = request.args.get('room_id', type=int)
    if not room_id:
        return jsonify({'error': 'Missing room_id'}), 400
    count = get_room_unread_count(room_id, user['id'])
    return jsonify({'count': count})

@app.route('/api/mark_room_read', methods=['POST'])
@login_required
def mark_room_read(user):
    data = request.json
    room_id = data.get('room_id')
    if room_id:
        mark_room_messages_read(room_id, user['id'])
    return jsonify({'status': 'ok'})

@app.route('/api/request_room', methods=['POST'])
@login_required
def request_room(user):
    data = request.json
    name = data.get('name')
    room_type = data.get('type')
    if not name or room_type not in ('channel', 'group'):
        return jsonify({'error': 'Invalid data'}), 400
    # Проверяем уникальность имени
    if get_room_by_name(name):
        return jsonify({'error': 'Room with this name already exists'}), 409
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO rooms (name, type, owner_id, created_at, is_active)
        VALUES (%s, %s, %s, %s, 0)
    ''', (name, room_type, user['id'], int(time.time())))
    room_id = c.lastrowid
    c.execute('''
        INSERT INTO room_requests (requester_id, room_id, type, created_at)
        VALUES (%s, %s, 'create', %s)
    ''', (user['id'], room_id, int(time.time())))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/admin/room_requests', methods=['GET'])
@login_required
@admin_required
def admin_room_requests(user):
    requests = get_pending_room_requests()
    return jsonify(requests)

@app.route('/api/admin/approve_room_request', methods=['POST'])
@login_required
@admin_required
def approve_room_request_route(user):
    data = request.json
    req_id = data.get('request_id')
    if not req_id:
        return jsonify({'error': 'Missing request_id'}), 400
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT room_id FROM room_requests WHERE id = %s', (req_id,))
    row = c.fetchone()
    if row:
        c.execute('UPDATE rooms SET is_active = 1 WHERE id = %s', (row[0],))
        c.execute('UPDATE room_requests SET status = %s WHERE id = %s', ('approved', req_id))
        c.execute('''
            INSERT INTO room_members (room_id, user_id, role, joined_at)
            VALUES (%s, %s, 'owner', %s)
            ON CONFLICT DO NOTHING
        ''', (row[0], user['id'], int(time.time())))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/admin/reject_room_request', methods=['POST'])
@login_required
@admin_required
def reject_room_request_route(user):
    data = request.json
    req_id = data.get('request_id')
    if not req_id:
        return jsonify({'error': 'Missing request_id'}), 400
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT room_id FROM room_requests WHERE id = %s', (req_id,))
    row = c.fetchone()
    if row:
        c.execute('DELETE FROM rooms WHERE id = %s', (row[0],))
        c.execute('DELETE FROM room_requests WHERE id = %s', (req_id,))
    conn.commit()
    conn.close()
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
    return jsonify(get_all_messages_exclude_bots())

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

@app.route('/api/admin/self_toggle_admin', methods=['POST'])
@login_required
def self_toggle_admin(user):
    if not user['is_admin']:
        return jsonify({'error': 'Only admin can toggle'}), 403
    data = request.json
    new_admin = data.get('is_admin', False)
    if user.get('is_super_admin'):
        return jsonify({'error': 'Superadmin cannot change own admin status'}), 403
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET is_admin = %s WHERE id = %s', (1 if new_admin else 0, user['id']))
    conn.commit()
    conn.close()
    session['user_id'] = user['id']
    return jsonify({'status': 'ok'})

@app.route('/api/admin/sync_users', methods=['POST'])
@login_required
@admin_required
def admin_sync_users(user):
    sync_users_from_txt()
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)