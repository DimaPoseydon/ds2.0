import socket

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

SERVER_HOST = "0.0.0.0"
SERVER_HTTP_PORT = 8888
SERVER_WS_PORT = 8888
SERVER_UDP_VOICE_PORT = 10000
SERVER_UDP_VIDEO_PORT = 10001
DATABASE_PATH = "swill.db"
SERVER_IP = get_local_ip()
FIXED_CRYPTO_KEY = "swill_fixed_key_2024"