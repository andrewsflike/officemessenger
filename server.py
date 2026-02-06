from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import sqlite3
import uuid
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'office-messenger-secret')
# Use threading mode for compatibility with modern Python runtimes on Render.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

def init_db():
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id TEXT PRIMARY KEY, user TEXT, text TEXT, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS private_messages
                 (id TEXT PRIMARY KEY, from_user_id TEXT, to_user_id TEXT, text TEXT, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (session_id TEXT PRIMARY KEY, user_id TEXT, username TEXT)''')
    conn.commit()
    conn.close()

# Initialize the SQLite DB at import time so gunicorn workers have tables ready.
init_db()

def get_messages():
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute("SELECT * FROM messages ORDER BY timestamp")
    messages = [{'id': row[0], 'user': row[1], 'text': row[2], 'timestamp': row[3]} 
                for row in c.fetchall()]
    conn.close()
    return messages

def save_message(user, text, timestamp):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    message_id = str(uuid.uuid4())
    c.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", 
              (message_id, user, text, timestamp))
    conn.commit()
    conn.close()
    return message_id

def save_private_message(from_user_id, to_user_id, text, timestamp):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    message_id = str(uuid.uuid4())
    c.execute("INSERT INTO private_messages VALUES (?, ?, ?, ?, ?)",
              (message_id, from_user_id, to_user_id, text, timestamp))
    conn.commit()
    conn.close()
    return message_id

def save_user(session_id, username):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    user_id = str(uuid.uuid4())[:8]
    c.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)", 
              (session_id, user_id, username))
    conn.commit()
    conn.close()
    return user_id

def get_user_id_by_session(session_id):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE session_id=?", (session_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_username_by_user_id(user_id):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_session_id_by_user_id(user_id):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute("SELECT session_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_users():
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM users")
    users = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
    conn.close()
    return users

def remove_user(session_id):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()

def get_private_messages(user_id, with_user_id):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute("""SELECT * FROM private_messages
                 WHERE (from_user_id=? AND to_user_id=?)
                    OR (from_user_id=? AND to_user_id=?)
                 ORDER BY timestamp""",
              (user_id, with_user_id, with_user_id, user_id))
    messages = [{
        'id': row[0],
        'fromUserId': row[1],
        'toUserId': row[2],
        'text': row[3],
        'timestamp': row[4],
        'user': get_username_by_user_id(row[1]) or "Unknown"
    } for row in c.fetchall()]
    conn.close()
    return messages

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    emit('message_history', get_messages())

@socketio.on('disconnect')
def handle_disconnect():
    remove_user(request.sid)
    emit('user_left', {'users': get_users()}, broadcast=True)

@socketio.on('set_username')
def set_username(data):
    user_id = save_user(request.sid, data['username'])
    emit('user_joined', {'users': get_users(), 'userId': user_id}, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    message_id = save_message(data['username'], data['message'], timestamp)
    
    message = {
        'id': message_id,
        'user': data['username'],
        'text': data['message'],
        'timestamp': timestamp
    }
    emit('new_message', message, broadcast=True)

@socketio.on('load_private_history')
def handle_private_history(data):
    current_user_id = get_user_id_by_session(request.sid)
    if not current_user_id:
        return
    with_user_id = data.get('withUserId')
    if not with_user_id:
        return
    messages = get_private_messages(current_user_id, with_user_id)
    emit('private_history', {'withUserId': with_user_id, 'messages': messages})

@socketio.on('send_private_message')
def handle_private_message(data):
    current_user_id = get_user_id_by_session(request.sid)
    if not current_user_id:
        return
    to_user_id = data.get('toUserId')
    text = data.get('message')
    if not to_user_id or not text:
        return
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    message_id = save_private_message(current_user_id, to_user_id, text, timestamp)
    message = {
        'id': message_id,
        'fromUserId': current_user_id,
        'toUserId': to_user_id,
        'user': get_username_by_user_id(current_user_id) or "Unknown",
        'text': text,
        'timestamp': timestamp
    }
    recipient_session_id = get_session_id_by_user_id(to_user_id)
    emit('new_private_message', message, to=request.sid)
    if recipient_session_id:
        emit('new_private_message', message, to=recipient_session_id)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
