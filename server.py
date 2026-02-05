from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import sqlite3
import uuid
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'office-messenger-secret')
socketio = SocketIO(app, cors_allowed_origins="*")

def init_db():
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id TEXT PRIMARY KEY, user TEXT, text TEXT, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (session_id TEXT PRIMARY KEY, user_id TEXT, username TEXT)''')
    conn.commit()
    conn.close()

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

def save_user(session_id, username):
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    user_id = str(uuid.uuid4())[:8]
    c.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)", 
              (session_id, user_id, username))
    conn.commit()
    conn.close()
    return user_id

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

if __name__ == '__main__':
    init_db()
    import os
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)

