# client.py - ПОЛНОСТЬЮ ИСПРАВЛЕННЫЙ
import sys
import asyncio
import json
import threading
import time
import socket
import struct
import requests
import numpy as np
import cv2
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import pyaudio
import websockets

from config import SERVER_UDP_VOICE_PORT, SERVER_UDP_VIDEO_PORT, FIXED_CRYPTO_KEY
from crypto import get_crypto, set_crypto_password

set_crypto_password(FIXED_CRYPTO_KEY)

COLORS = {
    "bg_primary": "#1e1f22",
    "bg_secondary": "#2b2d31",
    "bg_tertiary": "#383a40",
    "text_normal": "#dbdee1",
    "text_muted": "#949ba4",
    "text_bright": "#ffffff",
    "accent_primary": "#5865f2",
    "accent_success": "#57f287",
    "accent_danger": "#ed4245",
    "accent_warning": "#faa61a",
    "border": "#1e1f22",
    "hover": "#404249",
    "message_self": "#404249",
}

class AvatarLabel(QLabel):
    def __init__(self, username, size=40):
        super().__init__()
        self.username = username
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"""
            background-color: {self.get_color(username)};
            border-radius: {size//2}px;
            font-size: {size//3}px;
            font-weight: bold;
            color: white;
        """)
        initials = username[:2].upper() if len(username) >= 2 else username.upper()
        self.setText(initials)

    def get_color(self, name):
        hash_val = sum(ord(c) for c in name)
        colors = ["#5865f2", "#57f287", "#ed4245", "#faa61a", "#eb459e", "#00b0f4"]
        return colors[hash_val % len(colors)]

class VoiceUserWidget(QWidget):
    def __init__(self, user_id, username, speaking=False, muted=False):
        super().__init__()
        self.user_id = user_id
        self.username = username
        self.speaking = speaking
        self.muted = muted
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        self.avatar = AvatarLabel(self.username, 32)
        layout.addWidget(self.avatar)
        self.name_label = QLabel(self.username)
        self.name_label.setStyleSheet(f"color: {COLORS['text_normal']};")
        layout.addWidget(self.name_label)
        self.mic_icon = QLabel("🔇" if self.muted else "🎤")
        self.mic_icon.setFixedSize(20, 20)
        layout.addWidget(self.mic_icon)
        self.speaking_indicator = QLabel()
        self.speaking_indicator.setFixedSize(12, 12)
        self.speaking_indicator.setStyleSheet(f"background-color: {COLORS['text_muted']}; border-radius:6px;")
        layout.addWidget(self.speaking_indicator)
        layout.addStretch()
        self.setLayout(layout)

    def set_speaking(self, speaking):
        self.speaking = speaking
        if speaking:
            self.speaking_indicator.setStyleSheet(f"background-color: {COLORS['accent_success']}; border-radius:6px;")
            self.name_label.setStyleSheet(f"color: {COLORS['accent_success']};")
        else:
            self.speaking_indicator.setStyleSheet(f"background-color: {COLORS['text_muted']}; border-radius:6px;")
            self.name_label.setStyleSheet(f"color: {COLORS['text_normal']};")

    def set_muted(self, muted):
        self.muted = muted
        self.mic_icon.setText("🔇" if muted else "🎤")

class VoicePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.users = {}
        self.current_room = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.header = QLabel("🔊 VOICE CHANNELS")
        self.header.setStyleSheet(f"padding:12px; font-weight:bold; color:{COLORS['accent_success']}; background-color:{COLORS['bg_secondary']};")
        layout.addWidget(self.header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border:none;")
        self.container = QWidget()
        self.container.setStyleSheet(f"background-color:{COLORS['bg_secondary']};")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)
        self.setFixedWidth(260)

    def update_users(self, room_id, users_list):
        self.current_room = room_id
        # Очищаем существующие виджеты
        for i in reversed(range(self.container_layout.count())):
            w = self.container_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        self.users.clear()
        
        if not users_list:
            empty = QLabel("✨ No one here")
            empty.setStyleSheet(f"color:{COLORS['text_muted']}; padding:20px;")
            empty.setAlignment(Qt.AlignCenter)
            self.container_layout.addWidget(empty)
            return
        
        for u in users_list:
            widget = VoiceUserWidget(u["id"], u["username"], u.get("speaking", False), u.get("muted", False))
            self.container_layout.addWidget(widget)
            self.users[u["id"]] = widget
        
        self.container_layout.addStretch()

    def set_speaking(self, user_id, speaking):
        if user_id in self.users:
            self.users[user_id].set_speaking(speaking)

    def set_muted(self, user_id, muted):
        if user_id in self.users:
            self.users[user_id].set_muted(muted)

class AudioDeviceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audio Devices")
        self.setFixedSize(550, 500)
        self.setModal(True)
        self.selected_input_device = None
        self.selected_output_device = None
        self.test_stream = None
        self.audio = None
        self.test_timer = None
        self.init_ui()
        self.scan_devices()
    
    def init_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['bg_primary']};
                color: {COLORS['text_normal']};
            }}
            QLabel {{
                color: {COLORS['text_normal']};
            }}
            QComboBox {{
                background-color: {COLORS['bg_tertiary']};
                color: {COLORS['text_normal']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                min-height: 30px;
            }}
            QGroupBox {{
                color: {COLORS['text_bright']};
                border: 2px solid {COLORS['bg_tertiary']};
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }}
            QPushButton {{
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }}
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel("🎵 AUDIO DEVICES")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color:{COLORS['accent_success']};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        input_group = QGroupBox("🎤 Microphone (Input)")
        input_layout = QVBoxLayout()
        input_layout.setSpacing(10)
        self.input_combo = QComboBox()
        self.input_combo.setMinimumHeight(35)
        input_layout.addWidget(self.input_combo)
        
        self.test_input_btn = QPushButton("🔍 Test Microphone")
        self.test_input_btn.clicked.connect(self.test_input_device)
        input_layout.addWidget(self.test_input_btn)
        
        self.input_level_bar = QProgressBar()
        self.input_level_bar.setRange(0, 100)
        self.input_level_bar.setFixedHeight(25)
        self.input_level_bar.setFormat("")
        input_layout.addWidget(self.input_level_bar)
        
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        output_group = QGroupBox("🎧 Speakers / Headphones (Output)")
        output_layout = QVBoxLayout()
        output_layout.setSpacing(10)
        self.output_combo = QComboBox()
        self.output_combo.setMinimumHeight(35)
        output_layout.addWidget(self.output_combo)
        
        self.test_output_btn = QPushButton("🔊 Test Speakers")
        self.test_output_btn.clicked.connect(self.test_output_device)
        output_layout.addWidget(self.test_output_btn)
        
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.save_btn = QPushButton("💾 Save & Apply")
        self.save_btn.clicked.connect(self.save_devices)
        btn_layout.addWidget(self.save_btn)
        self.cancel_btn = QPushButton("❌ Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
        self.test_input_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_primary']};
            color: white;
            border: none;
        """)
        self.test_output_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_warning']};
            color: white;
            border: none;
        """)
        self.save_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_success']};
            color: #1e1f22;
            font-weight: bold;
            border: none;
        """)
        self.cancel_btn.setStyleSheet(f"""
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_normal']};
            border: none;
        """)
    
    def scan_devices(self):
        try:
            self.audio = pyaudio.PyAudio()
            self.input_combo.clear()
            self.input_combo.addItem("-- Default Device --", None)
            self.output_combo.clear()
            self.output_combo.addItem("-- Default Device --", None)
            
            print("\n📋 Available audio devices:")
            for i in range(self.audio.get_device_count()):
                try:
                    info = self.audio.get_device_info_by_index(i)
                    name = info.get('name', f'Device {i}')
                    
                    if info.get('maxInputChannels', 0) > 0:
                        self.input_combo.addItem(f"🎤 {i}: {name}", i)
                        print(f"  Input [{i}]: {name}")
                    
                    if info.get('maxOutputChannels', 0) > 0:
                        self.output_combo.addItem(f"🎧 {i}: {name}", i)
                        print(f"  Output [{i}]: {name}")
                except:
                    continue
            
            settings = QSettings("SWILL", "AudioDevices")
            saved_input = settings.value("input_device", None)
            saved_output = settings.value("output_device", None)
            
            if saved_input is not None:
                idx = self.input_combo.findData(int(saved_input))
                if idx >= 0:
                    self.input_combo.setCurrentIndex(idx)
            
            if saved_output is not None:
                idx = self.output_combo.findData(int(saved_output))
                if idx >= 0:
                    self.output_combo.setCurrentIndex(idx)
                    
        except Exception as e:
            print(f"Error scanning devices: {e}")
    
    def test_input_device(self):
        idx = self.input_combo.currentData()
        try:
            if self.test_timer:
                self.test_timer.stop()
            if self.test_stream:
                self.test_stream.close()
            
            self.test_stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=48000,
                input=True,
                frames_per_buffer=960,
                input_device_index=idx if idx is not None else None
            )
            self.test_stream.start_stream()
            
            self.test_timer = QTimer()
            self.test_timer.timeout.connect(self.update_test_level)
            self.test_timer.start(50)
            
            QMessageBox.information(self, "Microphone Test", "🎤 Speak into microphone...")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open microphone:\n{str(e)}")
    
    def update_test_level(self):
        if self.test_stream and self.test_stream.is_active():
            try:
                data = self.test_stream.read(960, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_data.astype(np.float32)**2)) / 32768.0
                level = min(rms * 100, 100)
                self.input_level_bar.setValue(int(level))
                
                if level > 30:
                    self.input_level_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLORS['accent_success']}; }}")
                elif level > 10:
                    self.input_level_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLORS['accent_warning']}; }}")
                else:
                    self.input_level_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLORS['accent_danger']}; }}")
            except:
                pass
        else:
            if self.test_timer:
                self.test_timer.stop()
            self.input_level_bar.setValue(0)
    
    def test_output_device(self):
        idx = self.output_combo.currentData()
        try:
            duration = 0.3
            sample_rate = 44100
            frames = int(duration * sample_rate)
            t = np.linspace(0, duration, frames)
            wave = 0.3 * np.sin(2 * np.pi * 440 * t)
            wave = (wave * 32767).astype(np.int16)
            
            test_audio = pyaudio.PyAudio()
            stream = test_audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                output=True,
                output_device_index=idx if idx is not None else None,
                frames_per_buffer=1024
            )
            stream.write(wave.tobytes())
            stream.close()
            test_audio.terminate()
            
            QMessageBox.information(self, "Speakers Test", "🔊 If you heard a beep, speakers work!")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not play sound:\n{str(e)}")
    
    def save_devices(self):
        settings = QSettings("SWILL", "AudioDevices")
        settings.setValue("input_device", self.input_combo.currentData())
        settings.setValue("output_device", self.output_combo.currentData())
        QMessageBox.information(self, "Saved", "✅ Audio settings saved!")
        self.accept()
    
    def closeEvent(self, event):
        if self.test_timer:
            self.test_timer.stop()
        if self.test_stream:
            self.test_stream.close()
        if self.audio:
            self.audio.terminate()
        event.accept()

class WSThread(QThread):
    message_received = pyqtSignal(dict)
    status_changed = pyqtSignal(bool)

    def __init__(self, token, server_ip):
        super().__init__()
        self.token = token
        self.server_ip = server_ip
        self.ws = None
        self.loop = None
        self.running = True
        self.ws_url = f"ws://{server_ip}:8888/ws/{token}"

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run())

    async def _run(self):
        try:
            async with websockets.connect(self.ws_url) as ws:
                self.ws = ws
                self.status_changed.emit(True)
                while self.running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        data = json.loads(msg)
                        self.message_received.emit(data)
                    except asyncio.TimeoutError:
                        continue
        except Exception as e:
            print(f"WS error: {e}")
            self.status_changed.emit(False)

    def send(self, data):
        if self.ws and self.loop:
            asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(data)), self.loop)

    def stop(self):
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

class VoiceEngine(QObject):
    speaking_changed = pyqtSignal(bool)
    level_updated = pyqtSignal(float)
    
    def __init__(self, server_ip):
        super().__init__()
        self.server_ip = server_ip
        self.crypto = get_crypto()
        self.audio = None
        self.audio_out = None
        self.stream = None
        self.output_stream = None
        self.running = False
        self.muted = False
        self.sensitivity = 0.02
        self.is_speaking = False
        self.current_level = 0
        self.input_device = None
        self.output_device = None
        self.receive_thread = None
        self.running_receive = True
        
        settings = QSettings("SWILL", "AudioDevices")
        self.input_device = settings.value("input_device", None)
        self.output_device = settings.value("output_device", None)
        if self.input_device is not None:
            self.input_device = int(self.input_device)
        if self.output_device is not None:
            self.output_device = int(self.output_device)
        
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.bind(('0.0.0.0', 0))
        self.local_port = self.udp_sock.getsockname()[1]
        self.server_addr = (server_ip, SERVER_UDP_VOICE_PORT)
        self.local_ip = self._get_local_ip()
        
    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.server_ip, 8888))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
        
    def start(self):
        self.running = True
        self.running_receive = True
        try:
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=48000,
                input=True,
                frames_per_buffer=960,
                input_device_index=self.input_device,
                stream_callback=self.audio_callback
            )
            self.stream.start_stream()
            print("✅ Microphone started")
        except Exception as e:
            print(f"❌ Microphone error: {e}")
        try:
            self.audio_out = pyaudio.PyAudio()
            self.output_stream = self.audio_out.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=48000,
                output=True,
                frames_per_buffer=960,
                output_device_index=self.output_device
            )
            print("✅ Speakers started")
        except Exception as e:
            print(f"⚠️ Speakers error: {e}")
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.receive_thread.start()
        
    def _receive_loop(self):
        while self.running_receive:
            try:
                self.udp_sock.settimeout(0.05)
                data, addr = self.udp_sock.recvfrom(4096)
                if data and len(data) > 0 and data[0] != 0xFF:
                    decrypted = self.crypto.decrypt_audio(data)
                    if self.output_stream and self.output_stream.is_active():
                        self.output_stream.write(decrypted)
            except:
                pass
                
    def stop(self):
        self.running = False
        self.running_receive = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except:
                pass
        if self.audio:
            try:
                self.audio.terminate()
            except:
                pass
        if self.audio_out:
            try:
                self.audio_out.terminate()
            except:
                pass
        print("🔇 Voice engine stopped")

    def set_muted(self, muted):
        self.muted = muted

    def set_sensitivity(self, val):
        self.sensitivity = max(0.001, min(val, 0.5))

    def audio_callback(self, in_data, frame_count, time_info, status):
        if not self.running:
            return (None, pyaudio.paAbort)
        try:
            audio_data = np.frombuffer(in_data, dtype=np.int16)
            rms = float(np.sqrt(np.mean(audio_data.astype(np.float32)**2)) / 32768.0)
            self.current_level = rms * 100
            self.level_updated.emit(self.current_level)
            speaking_now = bool((rms > self.sensitivity) and not self.muted)
            if speaking_now != self.is_speaking:
                self.is_speaking = speaking_now
                self.speaking_changed.emit(speaking_now)
                status_byte = b'\xFF' + (b'\x01' if speaking_now else b'\x00')
                try:
                    self.udp_sock.sendto(status_byte, self.server_addr)
                except:
                    pass
            if not self.muted and self.running:
                encrypted = self.crypto.encrypt_audio(in_data)
                self.udp_sock.sendto(encrypted, self.server_addr)
        except:
            pass
        return (in_data, pyaudio.paContinue)
    
    def get_local_port(self):
        return self.local_port

class VideoSender(QThread):
    frame_sent = pyqtSignal(QImage)

    def __init__(self, server_ip):
        super().__init__()
        self.crypto = get_crypto()
        self.server_addr = (server_ip, SERVER_UDP_VIDEO_PORT)
        self.running = True
        self.cap = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def run(self):
        try:
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                print("❌ Cannot open camera")
                return
            print("✅ Camera started")
        except Exception as e:
            print(f"❌ Camera error: {e}")
            return
            
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.resize(frame, (320, 240))
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                data = jpeg.tobytes()
                encrypted = self.crypto.encrypt_video(data)
                packet = struct.pack("I", len(encrypted)) + encrypted
                try:
                    self.sock.sendto(packet, self.server_addr)
                except:
                    pass
                
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
                self.frame_sent.emit(qimg)
            time.sleep(0.05)
        
        if self.cap:
            self.cap.release()

    def stop(self):
        self.running = False
        self.wait()

class VideoReceiver(QThread):
    frame_received = pyqtSignal(QImage)

    def __init__(self, server_ip):
        super().__init__()
        self.crypto = get_crypto()
        self.server_ip = server_ip
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', 0))
        self.local_port = self.sock.getsockname()[1]
        self.server_addr = (server_ip, SERVER_UDP_VIDEO_PORT)
        self.local_ip = self._get_local_ip()
        
    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.server_ip, 8888))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def run(self):
        while self.running:
            try:
                self.sock.settimeout(0.05)
                data, addr = self.sock.recvfrom(65535)
                if len(data) > 4:
                    size = struct.unpack("I", data[:4])[0]
                    video_data = data[4:4+size]
                    if video_data:
                        decrypted = self.crypto.decrypt_video(video_data)
                        np_arr = np.frombuffer(decrypted, np.uint8)
                        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            h, w, ch = rgb.shape
                            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
                            self.frame_received.emit(qimg)
            except socket.timeout:
                continue
            except:
                pass
    
    def stop(self):
        self.running = False
        self.wait()
    
    def get_port(self):
        return self.local_port

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SWILL - Secure Messenger")
        self.setFixedSize(450, 620)
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_primary']};
            }}
            QLineEdit {{
                background-color: {COLORS['bg_tertiary']};
                color: {COLORS['text_normal']};
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLORS['accent_primary']};
            }}
            QPushButton {{
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
            }}
            QLabel {{
                color: {COLORS['text_muted']};
            }}
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(40, 40, 40, 40)
        
        logo = QLabel("🔐 SWILL")
        logo.setStyleSheet(f"font-size: 42px; color:{COLORS['accent_primary']}; font-weight:bold;")
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)
        
        subtitle = QLabel("Secure Encrypted Messenger")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 12px;")
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
        ip_label = QLabel("SERVER IP")
        ip_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(ip_label)
        
        self.server_ip_edit = QLineEdit()
        self.server_ip_edit.setPlaceholderText("192.168.1.100")
        self.server_ip_edit.setText("127.0.0.1")
        layout.addWidget(self.server_ip_edit)
        
        user_label = QLabel("USERNAME")
        user_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(user_label)
        
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Enter username")
        layout.addWidget(self.user_edit)
        
        pass_label = QLabel("PASSWORD")
        pass_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(pass_label)
        
        self.pass_edit = QLineEdit()
        self.pass_edit.setPlaceholderText("Enter password")
        self.pass_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pass_edit)
        
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.status_label)
        
        self.login_btn = QPushButton("LOGIN")
        self.login_btn.clicked.connect(self.login)
        self.login_btn.setStyleSheet(f"background-color: {COLORS['accent_primary']}; color: white;")
        layout.addWidget(self.login_btn)
        
        self.register_btn = QPushButton("CREATE ACCOUNT")
        self.register_btn.clicked.connect(self.register)
        self.register_btn.setStyleSheet(f"background-color: {COLORS['bg_tertiary']};")
        layout.addWidget(self.register_btn)
        
        info = QLabel("💡 End-to-end encryption")
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)
        info.setStyleSheet(f"background-color: {COLORS['bg_secondary']}; padding: 10px; border-radius: 8px; font-size: 11px;")
        layout.addWidget(info)
        
        layout.addStretch()
        self.setLayout(layout)

    def login(self):
        user = self.user_edit.text().strip()
        pw = self.pass_edit.text()
        server_ip = self.server_ip_edit.text().strip()
        
        if not user or not pw:
            self.status_label.setText("❌ Fill all fields")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
            return
        if not server_ip:
            self.status_label.setText("❌ Enter server IP")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
            return
        
        try:
            self.status_label.setText("🔄 Connecting...")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_primary']}; font-size: 12px;")
            QApplication.processEvents()
            r = requests.post(f"http://{server_ip}:8888/login", json={"username": user, "password": pw}, timeout=5)
            if r.status_code == 200 and r.json().get("success"):
                data = r.json()
                self.token = data["token"]
                self.user_id = data["user_id"]
                self.username = data["username"]
                self.server_ip = server_ip
                self.open_main()
            else:
                self.status_label.setText("❌ Invalid credentials")
                self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
        except requests.exceptions.ConnectionError:
            self.status_label.setText(f"❌ Cannot connect to {server_ip}")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
        except Exception as e:
            self.status_label.setText(f"❌ Error: {str(e)}")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")

    def register(self):
        user = self.user_edit.text().strip()
        pw = self.pass_edit.text()
        server_ip = self.server_ip_edit.text().strip()
        
        if len(user) < 3:
            self.status_label.setText("❌ Username min 3 chars")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
            return
        if len(pw) < 3:
            self.status_label.setText("❌ Password min 3 chars")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
            return
        if not server_ip:
            self.status_label.setText("❌ Enter server IP")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
            return
        
        try:
            self.status_label.setText("🔄 Creating account...")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_primary']}; font-size: 12px;")
            QApplication.processEvents()
            r = requests.post(f"http://{server_ip}:8888/register", json={"username": user, "password": pw}, timeout=5)
            if r.status_code == 200 and r.json().get("success"):
                self.status_label.setText("✅ Account created! Now login")
                self.status_label.setStyleSheet(f"color: {COLORS['accent_success']}; font-size: 12px;")
                self.pass_edit.clear()
            else:
                error = r.json().get("error", "Unknown")
                self.status_label.setText(f"❌ Failed: {error}")
                self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")
        except Exception as e:
            self.status_label.setText(f"❌ Error: {str(e)}")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']}; font-size: 12px;")

    def open_main(self):
        self.main = MainWindow(self.token, self.user_id, self.username, self.server_ip)
        self.main.show()
        self.close()

class MainWindow(QMainWindow):
    def __init__(self, token, user_id, username, server_ip):
        super().__init__()
        self.token = token
        self.user_id = user_id
        self.username = username
        self.server_ip = server_ip
        self.current_channel = "general"
        self.ws_thread = None
        self.voice_engine = None
        self.video_sender = None
        self.video_receiver = None
        self.message_cache = {}
        self.crypto = get_crypto()
        self.voice_panel = None
        
        self.init_ui()
        self.init_websocket()
        self.setup_mic_indicator()
        
        self.statusBar().showMessage(f"🔒 Encrypted | Server: {server_ip}", 5000)
    
    def init_ui(self):
        self.setWindowTitle(f"SWILL - {self.username} @ {self.server_ip}")
        self.setGeometry(50, 50, 1300, 750)
        
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['bg_primary']};
            }}
            QListWidget {{
                background-color: {COLORS['bg_secondary']};
                color: {COLORS['text_normal']};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px;
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['accent_primary']};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {COLORS['hover']};
            }}
            QTextEdit {{
                background-color: {COLORS['bg_tertiary']};
                color: {COLORS['text_normal']};
                border: none;
                border-radius: 8px;
                font-size: 14px;
            }}
            QScrollArea {{
                border: none;
                background-color: {COLORS['bg_secondary']};
            }}
            QScrollBar:vertical {{
                background-color: {COLORS['bg_secondary']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {COLORS['text_muted']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {COLORS['accent_primary']};
            }}
            QPushButton {{
                border: none;
                border-radius: 6px;
            }}
            QStatusBar {{
                background-color: {COLORS['bg_secondary']};
                color: {COLORS['text_normal']};
            }}
        """)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Левая панель
        self.server_list = QListWidget()
        self.server_list.setFixedWidth(72)
        self.server_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_primary']};
                border-right: 1px solid {COLORS['border']};
            }}
            QListWidget::item {{
                padding: 12px;
                font-size: 24px;
                text-align: center;
            }}
        """)
        self.server_list.addItems(["🎮", "💬"])
        layout.addWidget(self.server_list)

        # Панель каналов
        self.channel_panel = QWidget()
        self.channel_panel.setFixedWidth(250)
        self.channel_panel.setStyleSheet(f"background-color: {COLORS['bg_secondary']};")
        vbox = QVBoxLayout(self.channel_panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        
        self.server_label = QLabel(f"🔒 {self.server_ip}")
        self.server_label.setStyleSheet(f"padding: 16px; font-weight: bold; font-size: 12px; color: {COLORS['accent_success']}; border-bottom: 1px solid {COLORS['border']};")
        vbox.addWidget(self.server_label)
        
        text_label = QLabel("TEXT CHANNELS")
        text_label.setStyleSheet(f"padding: 12px 16px 4px 16px; color: {COLORS['text_muted']}; font-size: 11px; font-weight: bold;")
        vbox.addWidget(text_label)
        
        self.channel_list = QListWidget()
        self.channel_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_secondary']};
                border: none;
            }}
            QListWidget::item {{
                padding: 6px 16px;
                border-radius: 6px;
            }}
        """)
        self.channel_list.addItems(["# general", "# off-topic"])
        self.channel_list.itemClicked.connect(self.on_channel_click)
        vbox.addWidget(self.channel_list)
        
        voice_label = QLabel("VOICE CHANNELS")
        voice_label.setStyleSheet(f"padding: 16px 16px 4px 16px; color: {COLORS['text_muted']}; font-size: 11px; font-weight: bold;")
        vbox.addWidget(voice_label)
        
        self.voice_room_list = QListWidget()
        self.voice_room_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_secondary']};
                border: none;
            }}
            QListWidget::item {{
                padding: 6px 16px;
                border-radius: 6px;
            }}
        """)
        self.voice_room_list.addItems(["🔊 General Voice"])
        self.voice_room_list.itemClicked.connect(self.on_voice_click)
        vbox.addWidget(self.voice_room_list)
        
        self.leave_voice_btn = QPushButton("🔇 Disconnect")
        self.leave_voice_btn.setFixedHeight(32)
        self.leave_voice_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_danger']};
            color: white;
            font-size: 12px;
            font-weight: bold;
            margin: 10px;
        """)
        self.leave_voice_btn.clicked.connect(self.leave_voice_channel)
        self.leave_voice_btn.setVisible(False)
        vbox.addWidget(self.leave_voice_btn)
        
        vbox.addStretch()
        layout.addWidget(self.channel_panel)

        # Чат
        self.chat_panel = QWidget()
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        
        self.chat_header = QLabel("# general")
        self.chat_header.setStyleSheet(f"padding: 16px 20px; border-bottom: 1px solid {COLORS['border']}; font-size: 16px; font-weight: bold; color: {COLORS['text_bright']}; background-color: {COLORS['bg_primary']};")
        chat_layout.addWidget(self.chat_header)
        
        self.messages_display = QTextEdit()
        self.messages_display.setReadOnly(True)
        self.messages_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_primary']};
                color: {COLORS['text_normal']};
                border: none;
                font-size: 14px;
                padding: 16px;
            }}
        """)
        chat_layout.addWidget(self.messages_display)
        
        input_container = QWidget()
        input_container.setStyleSheet(f"background-color: {COLORS['bg_primary']}; padding: 16px;")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)
        
        self.input_field = QTextEdit()
        self.input_field.setMaximumHeight(80)
        self.input_field.setPlaceholderText("Type a message...")
        self.input_field.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_tertiary']};
                color: {COLORS['text_normal']};
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
            }}
        """)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedSize(75, 42)
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_primary']};
            color: white;
            font-weight: bold;
            font-size: 13px;
            border-radius: 8px;
        """)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_btn)
        chat_layout.addWidget(input_container)
        
        layout.addWidget(self.chat_panel)

        # Панель голоса
        self.voice_panel = VoicePanel()
        layout.addWidget(self.voice_panel)

        # Видео
        self.video_label = QLabel()
        self.video_label.setFixedSize(320, 240)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setText("📷 Video Off")
        self.video_label.setStyleSheet(f"border: 2px solid {COLORS['accent_primary']}; background-color: {COLORS['bg_secondary']}; border-radius: 8px;")
        
        self.video_dock = QDockWidget("Webcam", self)
        self.video_dock.setWidget(self.video_label)
        self.video_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.video_dock.setStyleSheet(f"""
            QDockWidget::title {{
                background-color: {COLORS['bg_secondary']};
                color: {COLORS['text_normal']};
                padding: 4px;
            }}
        """)
        self.addDockWidget(Qt.TopDockWidgetArea, self.video_dock)

        # Статус
        self.connection_status = QLabel("🟡 Connecting...")
        self.statusBar().addPermanentWidget(self.connection_status)
    
    def leave_voice_channel(self):
        if self.ws_thread:
            self.ws_thread.send({"cmd": "leave_voice"})
            self.voice_status.setText("🔇 Not in voice")
            self.leave_voice_btn.setVisible(False)
            if self.voice_engine:
                self.voice_engine.stop()
            if self.video_sender:
                self.video_sender.stop()
                self.video_sender = None
    
    def setup_mic_indicator(self):
        status = self.statusBar()
        
        self.mic_btn = QPushButton("🎤 Mic On")
        self.mic_btn.clicked.connect(self.toggle_mic)
        self.mic_btn.setStyleSheet(f"""
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_normal']};
            padding: 5px 12px;
            border-radius: 4px;
        """)
        
        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setFixedWidth(100)
        self.mic_level_bar.setFixedHeight(18)
        self.mic_level_bar.setFormat("")
        self.mic_level_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {COLORS['bg_tertiary']};
                border-radius: 3px;
                background-color: {COLORS['bg_secondary']};
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent_success']};
                border-radius: 2px;
            }}
        """)
        
        self.test_btn = QPushButton("🔍 Test")
        self.test_btn.clicked.connect(self.test_microphone)
        self.test_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_primary']};
            color: white;
            padding: 5px 12px;
            border-radius: 4px;
        """)
        
        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setFixedWidth(35)
        self.settings_btn.clicked.connect(self.open_audio_settings)
        self.settings_btn.setStyleSheet(f"""
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_normal']};
            border-radius: 4px;
        """)
        
        self.device_btn = QPushButton("🎛️")
        self.device_btn.setFixedWidth(35)
        self.device_btn.clicked.connect(self.select_audio_devices)
        self.device_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_primary']};
            color: white;
            border-radius: 4px;
        """)
        
        self.video_btn = QPushButton("📷")
        self.video_btn.setFixedWidth(35)
        self.video_btn.clicked.connect(self.toggle_video)
        self.video_btn.setStyleSheet(f"""
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_normal']};
            border-radius: 4px;
        """)
        
        self.voice_status = QLabel("🔇 Not in voice")
        self.voice_status.setStyleSheet(f"color: {COLORS['accent_success']}; padding: 0 10px;")
        
        status.addPermanentWidget(self.mic_btn)
        status.addPermanentWidget(self.mic_level_bar)
        status.addPermanentWidget(self.test_btn)
        status.addPermanentWidget(self.settings_btn)
        status.addPermanentWidget(self.device_btn)
        status.addPermanentWidget(self.video_btn)
        status.addPermanentWidget(self.voice_status)
        
        self.mic_timer = QTimer()
        self.mic_timer.timeout.connect(self.update_mic_level)
        self.mic_timer.start(100)
    
    def select_audio_devices(self):
        dialog = AudioDeviceDialog(self)
        dialog.exec_()

    def test_microphone(self):
        try:
            settings = QSettings("SWILL", "AudioDevices")
            input_device = settings.value("input_device", None)
            if input_device:
                input_device = int(input_device)
            audio = pyaudio.PyAudio()
            stream = audio.open(format=pyaudio.paInt16, channels=1, rate=48000, input=True, input_device_index=input_device, frames_per_buffer=960)
            stream.start_stream()
            print("\n🎤 Microphone test:")
            for i in range(50):
                data = stream.read(960, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_data.astype(np.float32)**2)) / 32768.0
                level = int(rms * 100)
                print(f"\rLevel: {level:3d}%", end="", flush=True)
                time.sleep(0.05)
            print("\n✅ Test complete")
            stream.close()
            audio.terminate()
            QMessageBox.information(self, "Test", "Microphone test complete")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def update_mic_level(self):
        if self.voice_engine:
            level = int(self.voice_engine.current_level)
            self.mic_level_bar.setValue(level)

    def init_websocket(self):
        self.ws_thread = WSThread(self.token, self.server_ip)
        self.ws_thread.message_received.connect(self.on_ws_message)
        self.ws_thread.status_changed.connect(self.on_ws_status)
        self.ws_thread.start()

    def on_ws_status(self, connected):
        if connected:
            self.connection_status.setText("🟢 Connected")
            self.connection_status.setStyleSheet(f"color: {COLORS['accent_success']};")
            QTimer.singleShot(500, self.init_voice_udp)
        else:
            self.connection_status.setText("🔴 Disconnected")
            self.connection_status.setStyleSheet(f"color: {COLORS['accent_danger']};")

    def init_voice_udp(self):
        self.voice_engine = VoiceEngine(self.server_ip)
        self.voice_engine.speaking_changed.connect(self.on_speaking)
        self.voice_engine.level_updated.connect(self.update_mic_level)
        if self.ws_thread:
            port = self.voice_engine.get_local_port()
            local_ip = self.voice_engine.local_ip
            self.ws_thread.send({"cmd": "voice_udp_ready", "port": port, "ip": local_ip})
            self.init_video_receiver()
    
    def init_video_receiver(self):
        self.video_receiver = VideoReceiver(self.server_ip)
        self.video_receiver.frame_received.connect(self.on_video_received)
        self.video_receiver.start()
        if self.ws_thread:
            port = self.video_receiver.get_port()
            local_ip = self.video_receiver.local_ip
            self.ws_thread.send({"cmd": "video_udp_ready", "port": port, "ip": local_ip})
            print(f"[Video] Receiver ready on port {port}")
    
    def on_video_received(self, qimg):
        self.video_label.setPixmap(QPixmap.fromImage(qimg).scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.video_label.setText("")

    def on_ws_message(self, data):
        typ = data.get("type")
        if typ == "new_message":
            channel_id = data.get("channel_id", self.current_channel)
            if channel_id not in self.message_cache:
                self.message_cache[channel_id] = []
            self.message_cache[channel_id].append(data)
            if channel_id == self.current_channel:
                content = self.crypto.decrypt_message(data["content"])
                self.add_message(data["username"], content)
                
        elif typ == "channel_history":
            self.messages_display.clear()
            for msg in data.get("messages", []):
                content = self.crypto.decrypt_message(msg["content"])
                self.add_message(msg["username"], content)
                
        elif typ == "voice_state_update":
            self.voice_panel.update_users(data["room_id"], data.get("users", []))
            count = len(data.get("users", []))
            if count > 0:
                self.voice_status.setText(f"🎙️ {count} in voice")
            else:
                self.voice_status.setText("🔇 Voice empty")
                
        elif typ == "speaking_update":
            self.voice_panel.set_speaking(data["user_id"], data["speaking"])
            
        elif typ == "voice_joined":
            self.voice_status.setText(f"🎙️ Connected")
            self.leave_voice_btn.setVisible(True)
            if self.voice_engine:
                self.voice_engine.start()
                
        elif typ == "voice_left":
            self.voice_status.setText("🔇 Not in voice")
            self.leave_voice_btn.setVisible(False)
            if self.voice_engine:
                self.voice_engine.stop()
            # Очищаем панель пользователей при выходе
            self.voice_panel.update_users("", [])
                
        elif typ == "video_udp_ack":
            print("✅ Video UDP ready")
            
        elif typ == "ready":
            print(f"✅ Connected as {data['username']}")
            if self.current_channel:
                self.ws_thread.send({"cmd": "join_channel", "channel_id": self.current_channel})

    def on_speaking(self, speaking):
        pass

    def toggle_mic(self):
        if self.voice_engine:
            muted = not self.voice_engine.muted
            self.voice_engine.set_muted(muted)
            self.mic_btn.setText("🔇 Mic Off" if muted else "🎤 Mic On")
            if muted:
                self.mic_btn.setStyleSheet(f"""
                    background-color: {COLORS['accent_danger']};
                    color: white;
                    padding: 5px 12px;
                    border-radius: 4px;
                """)
            else:
                self.mic_btn.setStyleSheet(f"""
                    background-color: {COLORS['bg_tertiary']};
                    color: {COLORS['text_normal']};
                    padding: 5px 12px;
                    border-radius: 4px;
                """)
            if self.ws_thread:
                self.ws_thread.send({"cmd": "mute_mic", "muted": muted})

    def open_audio_settings(self):
        if not self.voice_engine:
            QMessageBox.warning(self, "Error", "Join a voice channel first")
            return
        
        dlg = QDialog(self)
        dlg.setWindowTitle("Audio Settings")
        dlg.setFixedSize(400, 150)
        dlg.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['bg_primary']};
                color: {COLORS['text_normal']};
            }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: {COLORS['bg_tertiary']};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['accent_primary']};
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}
        """)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Microphone sensitivity:"))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(1, 100)
        slider.setValue(int(self.voice_engine.sensitivity * 100))
        slider.valueChanged.connect(lambda v: self.voice_engine.set_sensitivity(v/100))
        layout.addWidget(slider)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        close_btn.setStyleSheet(f"""
            background-color: {COLORS['accent_primary']};
            color: white;
            padding: 8px;
            border-radius: 4px;
        """)
        layout.addWidget(close_btn)
        
        dlg.setLayout(layout)
        dlg.exec_()

    def toggle_video(self):
        if self.video_sender and self.video_sender.isRunning():
            self.video_sender.stop()
            self.video_sender = None
            self.video_label.setText("📷 Video Off")
            self.video_btn.setStyleSheet(f"""
                background-color: {COLORS['bg_tertiary']};
                color: {COLORS['text_normal']};
                border-radius: 4px;
            """)
        else:
            self.video_sender = VideoSender(self.server_ip)
            self.video_sender.frame_sent.connect(self.update_my_video)
            self.video_sender.start()
            self.video_btn.setStyleSheet(f"""
                background-color: {COLORS['accent_success']};
                color: #1e1f22;
                font-weight: bold;
                border-radius: 4px;
            """)
    
    def update_my_video(self, qimg):
        self.video_label.setPixmap(QPixmap.fromImage(qimg).scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.video_label.setText("")

    def send_message(self):
        text = self.input_field.toPlainText().strip()
        if text and self.current_channel and self.ws_thread:
            self.ws_thread.send({"cmd": "send_message", "channel_id": self.current_channel, "content": text})
            self.add_message(self.username, text)
            self.input_field.clear()

    def add_message(self, username, content):
        color = COLORS['accent_primary'] if username == self.username else COLORS['text_bright']
        bg_color = COLORS['message_self'] if username == self.username else COLORS['bg_primary']
        self.messages_display.append(f"""
            <div style='background-color: {bg_color}; padding: 8px; border-radius: 8px; margin: 4px 0;'>
                <b style='color: {color}'>{username}</b><br/>
                <span style='color: {COLORS["text_normal"]}'>{content}</span>
            </div>
        """)
        self.messages_display.verticalScrollBar().setValue(self.messages_display.verticalScrollBar().maximum())

    def on_channel_click(self, item):
        ch = item.text().replace("# ", "")
        self.current_channel = ch
        self.chat_header.setText(f"# {ch}")
        self.messages_display.clear()
        if ch in self.message_cache:
            for msg in self.message_cache[ch]:
                content = self.crypto.decrypt_message(msg["content"])
                self.add_message(msg["username"], content)
        if self.ws_thread:
            self.ws_thread.send({"cmd": "join_channel", "channel_id": ch})

    def on_voice_click(self, item):
        room = item.text()
        if self.ws_thread:
            self.ws_thread.send({"cmd": "join_voice", "room_id": room})

    def closeEvent(self, event):
        if self.ws_thread:
            self.ws_thread.stop()
            self.ws_thread.quit()
            self.ws_thread.wait()
        if self.voice_engine:
            self.voice_engine.stop()
        if self.video_sender:
            self.video_sender.stop()
        if self.video_receiver:
            self.video_receiver.stop()
        event.accept()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    login = LoginWindow()
    login.show()
    sys.exit(app.exec_())