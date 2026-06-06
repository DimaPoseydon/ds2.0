import base64
import hashlib
import secrets

class CryptoManager:
    def __init__(self, password=None):
        if password:
            self.key = hashlib.pbkdf2_hmac('sha256', password.encode(), b'swill_salt', 100000, dklen=32)
        else:
            self.key = b'swill_default_key_2024_32_bytes!'  # Фиксированный ключ
        if len(self.key) < 32:
            self.key = hashlib.sha256(self.key).digest()
    
    def _xor_encrypt(self, data: bytes) -> bytes:
        result = bytearray()
        key_len = len(self.key)
        for i, byte in enumerate(data):
            result.append(byte ^ self.key[i % key_len])
        return bytes(result)
    
    def encrypt_message(self, message: str) -> str:
        if not message:
            return message
        encrypted = self._xor_encrypt(message.encode('utf-8'))
        return base64.b64encode(encrypted).decode('utf-8')
    
    def decrypt_message(self, encrypted_message: str) -> str:
        if not encrypted_message:
            return encrypted_message
        try:
            decrypted = self._xor_encrypt(base64.b64decode(encrypted_message))
            return decrypted.decode('utf-8')
        except:
            return encrypted_message
    
    def encrypt_audio(self, audio_data: bytes) -> bytes:
        return self._xor_encrypt(audio_data)
    
    def decrypt_audio(self, encrypted_data: bytes) -> bytes:
        return self._xor_encrypt(encrypted_data)
    
    def encrypt_video(self, video_data: bytes) -> bytes:
        return self._xor_encrypt(video_data)
    
    def decrypt_video(self, encrypted_data: bytes) -> bytes:
        return self._xor_encrypt(encrypted_data)

_crypto_instance = None

def get_crypto(password=None):
    global _crypto_instance
    if _crypto_instance is None:
        _crypto_instance = CryptoManager(password)
    return _crypto_instance

def set_crypto_password(password: str):
    global _crypto_instance
    _crypto_instance = CryptoManager(password)