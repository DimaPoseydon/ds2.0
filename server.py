import asyncio
import json
import sqlite3
import secrets
import hashlib
import socket
import threading
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from config import SERVER_HOST, SERVER_HTTP_PORT, SERVER_UDP_VOICE_PORT, SERVER_UDP_VIDEO_PORT, DATABASE_PATH, FIXED_CRYPTO_KEY
from crypto import set_crypto_password, get_crypto

set_crypto_password(FIXED_CRYPTO_KEY)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# База данных
conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
c = conn.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT,
    token TEXT,
    created_at REAL
)""")

c.execute("""CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT,
    user_id TEXT,
    username TEXT,
    content TEXT,
    timestamp REAL
)""")

c.execute("""CREATE TABLE IF NOT EXISTS voice_rooms (
    id TEXT PRIMARY KEY,
    server_id TEXT,
    name TEXT
)""")

try:
    c.execute("INSERT OR IGNORE INTO voice_rooms (id, server_id, name) VALUES (?, ?, ?)", 
              ("general_voice", "main", "🔊 General Voice"))
except:
    pass

conn.commit()

# Хранилища
active_ws = {}
user_channels = {}
voice_rooms_members = {}
user_current_voice = {}
user_voice_muted = {}
user_speaking = {}

# UDP голос
voice_clients = {}
user_udp_endpoint = {}

# UDP видео
video_clients = {}
user_video_endpoint = {}

class VoiceUDPHandler:
    def __init__(self, host="0.0.0.0", port=10000):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.running = True
        threading.Thread(target=self.run, daemon=True).start()
        print(f"[UDP Voice] Listening on {host}:{port}")

    def run(self):
        while self.running:
            try:
                self.sock.settimeout(0.1)
                data, addr = self.sock.recvfrom(65535)
                if addr not in voice_clients:
                    continue
                user_id = voice_clients[addr]
                
                if len(data) > 0 and data[0] == 0xFF:
                    speaking = (data[1] == 0x01)
                    if user_speaking.get(user_id) != speaking:
                        user_speaking[user_id] = speaking
                        room_id = user_current_voice.get(user_id)
                        if room_id:
                            self.broadcast_speaking(room_id, user_id, speaking)
                else:
                    room_id = user_current_voice.get(user_id)
                    if room_id and room_id in voice_rooms_members:
                        for uid in voice_rooms_members[room_id]:
                            if uid != user_id and uid in user_udp_endpoint:
                                try:
                                    self.sock.sendto(data, user_udp_endpoint[uid])
                                except:
                                    pass
            except socket.timeout:
                continue
            except:
                pass

    def broadcast_speaking(self, room_id, user_id, speaking):
        if room_id not in voice_rooms_members:
            return
        msg = {"type": "speaking_update", "user_id": user_id, "speaking": speaking}
        for uid in voice_rooms_members[room_id]:
            if uid in active_ws and uid != user_id:
                try:
                    asyncio.run_coroutine_threadsafe(
                        active_ws[uid].send_json(msg), 
                        asyncio.get_event_loop()
                    )
                except:
                    pass

    def register_user(self, addr, user_id):
        voice_clients[addr] = user_id
        user_udp_endpoint[user_id] = addr
        print(f"[UDP Voice] Registered {user_id} at {addr}")

    def unregister_user(self, user_id):
        if user_id in user_udp_endpoint:
            addr = user_udp_endpoint[user_id]
            if addr in voice_clients:
                del voice_clients[addr]
            del user_udp_endpoint[user_id]

class VideoUDPHandler:
    def __init__(self, host="0.0.0.0", port=10001):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.running = True
        threading.Thread(target=self.run, daemon=True).start()
        print(f"[UDP Video] Listening on {host}:{port}")

    def run(self):
        while self.running:
            try:
                self.sock.settimeout(0.1)
                data, addr = self.sock.recvfrom(65535)
                if addr not in video_clients:
                    continue
                user_id = video_clients[addr]
                
                # Ретрансляция видео всем в той же голосовой комнате
                room_id = user_current_voice.get(user_id)
                if room_id and room_id in voice_rooms_members:
                    for uid in voice_rooms_members[room_id]:
                        if uid != user_id and uid in user_video_endpoint:
                            try:
                                self.sock.sendto(data, user_video_endpoint[uid])
                            except:
                                pass
            except socket.timeout:
                continue
            except:
                pass

    def register_user(self, addr, user_id):
        video_clients[addr] = user_id
        user_video_endpoint[user_id] = addr
        print(f"[UDP Video] Registered {user_id} at {addr}")

    def unregister_user(self, user_id):
        if user_id in user_video_endpoint:
            addr = user_video_endpoint[user_id]
            if addr in video_clients:
                del video_clients[addr]
            del user_video_endpoint[user_id]

# Создаем обработчики
voice_handler = VoiceUDPHandler(host=SERVER_HOST, port=SERVER_UDP_VOICE_PORT)
video_handler = VideoUDPHandler(host=SERVER_HOST, port=SERVER_UDP_VIDEO_PORT)

# Аутентификация
class LoginReq(BaseModel):
    username: str
    password: str

class RegisterReq(BaseModel):
    username: str
    password: str

def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.sha256((pw + salt).encode()).hexdigest()

def verify_password(pw: str, hashed: str) -> bool:
    try:
        salt, h = hashed.split(":")
        return hashlib.sha256((pw + salt).encode()).hexdigest() == h
    except:
        return False

@app.post("/register")
async def register(req: RegisterReq):
    if len(req.username) < 3 or len(req.password) < 3:
        return {"success": False, "error": "Too short"}
    
    c.execute("SELECT id FROM users WHERE username = ?", (req.username,))
    if c.fetchone():
        return {"success": False, "error": "Username exists"}
    
    user_id = secrets.token_hex(16)
    token = secrets.token_urlsafe(32)
    pwhash = hash_password(req.password)
    
    c.execute("INSERT INTO users (id, username, password_hash, token, created_at) VALUES (?,?,?,?,?)",
              (user_id, req.username, pwhash, token, time.time()))
    conn.commit()
    
    return {"success": True, "token": token, "user_id": user_id, "username": req.username}

@app.post("/login")
async def login(req: LoginReq):
    c.execute("SELECT id, username, password_hash, token FROM users WHERE username = ?", (req.username,))
    row = c.fetchone()
    
    if not row or not verify_password(req.password, row[2]):
        return {"success": False, "error": "Invalid credentials"}
    
    new_token = secrets.token_urlsafe(32)
    c.execute("UPDATE users SET token = ? WHERE id = ?", (new_token, row[0]))
    conn.commit()
    
    return {"success": True, "token": new_token, "user_id": row[0], "username": row[1]}

# WebSocket
@app.websocket("/ws/{token}")
async def ws_endpoint(ws: WebSocket, token: str):
    c.execute("SELECT id, username FROM users WHERE token = ?", (token,))
    user = c.fetchone()
    
    if not user:
        await ws.close(code=4001)
        return
    
    user_id, username = user
    await ws.accept()
    active_ws[user_id] = ws
    crypto = get_crypto()
    
    await ws.send_json({"type": "ready", "user_id": user_id, "username": username})
    print(f"[WS] {username} connected")

    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd")

            if cmd == "join_channel":
                channel_id = data["channel_id"]
                user_channels[user_id] = channel_id
                
                c.execute("SELECT user_id, username, content, timestamp FROM messages WHERE channel_id = ? ORDER BY timestamp DESC LIMIT 50", (channel_id,))
                rows = c.fetchall()
                msgs = [{"user_id": r[0], "username": r[1], "content": r[2], "timestamp": r[3]} for r in reversed(rows)]
                await ws.send_json({"type": "channel_history", "channel_id": channel_id, "messages": msgs})

            elif cmd == "send_message":
                channel_id = data["channel_id"]
                content = data["content"][:2000]
                ts = time.time()
                
                encrypted_content = crypto.encrypt_message(content)
                
                c.execute("INSERT INTO messages (channel_id, user_id, username, content, timestamp) VALUES (?,?,?,?,?)",
                          (channel_id, user_id, username, encrypted_content, ts))
                conn.commit()
                
                msg_data = {
                    "type": "new_message",
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "username": username,
                    "content": encrypted_content,
                    "timestamp": ts
                }
                
                # Не отправляем сообщение обратно отправителю
                for uid, wsobj in active_ws.items():
                    if user_channels.get(uid) == channel_id and uid != user_id:
                        try:
                            await wsobj.send_json(msg_data)
                        except:
                            pass

            elif cmd == "clear_channel":
                channel_id = data["channel_id"]
                c.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
                conn.commit()
                msg_data = {"type": "channel_cleared", "channel_id": channel_id}
                for uid, wsobj in active_ws.items():
                    if user_channels.get(uid) == channel_id:
                        try:
                            await wsobj.send_json(msg_data)
                        except:
                            pass

            elif cmd == "join_voice":
                room_id = data["room_id"]
                
                if user_id in user_current_voice:
                    old = user_current_voice[user_id]
                    if old in voice_rooms_members:
                        voice_rooms_members[old].discard(user_id)
                        await broadcast_voice_state(old)
                
                user_current_voice[user_id] = room_id
                if room_id not in voice_rooms_members:
                    voice_rooms_members[room_id] = set()
                voice_rooms_members[room_id].add(user_id)
                user_speaking[user_id] = False
                
                await broadcast_voice_state(room_id)
                await ws.send_json({"type": "voice_joined", "room_id": room_id})
                print(f"[Voice] {username} joined {room_id}")

            elif cmd == "leave_voice":
                if user_id in user_current_voice:
                    room_id = user_current_voice[user_id]
                    if room_id in voice_rooms_members:
                        voice_rooms_members[room_id].discard(user_id)
                        await broadcast_voice_state(room_id)
                    del user_current_voice[user_id]
                user_speaking.pop(user_id, None)
                # Отписываем видео при выходе из голоса
                video_handler.unregister_user(user_id)
                await ws.send_json({"type": "voice_left"})

            elif cmd == "mute_mic":
                user_voice_muted[user_id] = data.get("muted", True)

            elif cmd == "voice_udp_ready":
                port = data["port"]
                client_ip = data.get("ip")
                if not client_ip:
                    client_ip = ws.client.host if ws.client else "127.0.0.1"
                voice_handler.register_user((client_ip, port), user_id)
                await ws.send_json({"type": "voice_udp_ack"})

            elif cmd == "video_udp_ready":
                port = data["port"]
                client_ip = data.get("ip")
                if not client_ip:
                    client_ip = ws.client.host if ws.client else "127.0.0.1"
                video_handler.register_user((client_ip, port), user_id)
                await ws.send_json({"type": "video_udp_ack"})
                print(f"[Video] {username} registered for video at {client_ip}:{port}")

    except WebSocketDisconnect:
        print(f"[WS] {username} disconnected")
        if user_id in active_ws:
            del active_ws[user_id]
        if user_id in user_current_voice:
            room_id = user_current_voice[user_id]
            if room_id in voice_rooms_members:
                voice_rooms_members[room_id].discard(user_id)
                await broadcast_voice_state(room_id)
            del user_current_voice[user_id]
        voice_handler.unregister_user(user_id)
        video_handler.unregister_user(user_id)

async def broadcast_voice_state(room_id: str):
    users_in_room = list(voice_rooms_members.get(room_id, set()))
    users_data = []
    
    for uid in users_in_room:
        c.execute("SELECT username FROM users WHERE id = ?", (uid,))
        row = c.fetchone()
        if row:
            users_data.append({
                "id": uid,
                "username": row[0],
                "speaking": user_speaking.get(uid, False),
                "muted": user_voice_muted.get(uid, False)
            })
    
    msg = {"type": "voice_state_update", "room_id": room_id, "users": users_data}
    
    for uid in users_in_room:
        if uid in active_ws:
            try:
                await active_ws[uid].send_json(msg)
            except:
                pass

if __name__ == "__main__":
    print("\n" + "="*50)
    print("SWILL Server with Encryption")
    print("="*50)
    print(f"HTTP/WS Port: {SERVER_HTTP_PORT}")
    print(f"UDP Voice Port: {SERVER_UDP_VOICE_PORT}")
    print(f"UDP Video Port: {SERVER_UDP_VIDEO_PORT}")
    print("="*50 + "\n")
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_HTTP_PORT)