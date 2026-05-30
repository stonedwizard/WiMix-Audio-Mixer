#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import time
import threading
from typing import Dict, List, Optional

import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QFrame, QMessageBox,
    QPushButton, QSplitter, QComboBox, QGridLayout, QMenu, QInputDialog,
    QSystemTrayIcon, QStyle, QAction, QSlider
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QMutex
from PyQt5.QtGui import QPainter, QColor, QDragEnterEvent, QDropEvent, QFont, QIcon

from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from comtypes import CLSCTX_ALL
from ctypes import POINTER, cast

# ================== НАСТРОЙКИ ==================
MAPPING_FILE = "mapping.json"
CONFIG_FILE = "config.json"
BAUD_RATE = 115200
ARDUINO_READY_MSG = "gradient_dot_ready"
MICROPHONE_NAME = "🎤 Микрофон"

# VID/PID для популярных USB-UART мостов
KNOWN_DEVICES = [
    (0x1A86, 0x7523),  # CH340
    (0x1A86, 0x55D4),  # CH340 (alternative)
    (0x1A86, 0x55D3),  # Мой esp
    (0x0403, 0x6001),  # FTDI FT232
    (0x2341, 0x0043),  # Arduino Uno
    (0x2341, 0x0001),  # Arduino Mega
    (0x2E8A, 0x000A),  # Raspberry Pi Pico
]
# ===============================================

# ================== КЛАССЫ ДЛЯ АРДУИНО ==================
class ArduinoFinder:
    @staticmethod
    def find_by_vidpid() -> Optional[str]:
        """Поиск порта по известным VID/PID."""
        for port in serial.tools.list_ports.comports():
            if port.vid and port.pid:
                if (port.vid, port.pid) in KNOWN_DEVICES:
                    return port.device
        return None

    @staticmethod
    def find_by_greeting() -> Optional[str]:
        """Поиск по приветственному сообщению (запасной вариант)."""
        for port in serial.tools.list_ports.comports():
            try:
                ser = serial.Serial(port.device, BAUD_RATE, timeout=2)
                time.sleep(2)
                data = ser.read(100).decode(errors='ignore')
                ser.close()
                if ARDUINO_READY_MSG in data:
                    return port.device
            except Exception:
                continue
        return None

    @staticmethod
    def find_port() -> Optional[str]:
        """Комбинированный поиск: сначала по VID/PID, затем по приветствию."""
        port = ArduinoFinder.find_by_vidpid()
        if port:
            return port
        return ArduinoFinder.find_by_greeting()

    @staticmethod
    def get_ports_list() -> List[str]:
        return [port.device for port in serial.tools.list_ports.comports()]


class SerialReader(QThread):
    data_received = pyqtSignal(dict)
    connection_status = pyqtSignal(bool, str)
    disconnected = pyqtSignal()  # сигнал при потере связи

    def __init__(self, port: str):
        super().__init__()
        self.port = port
        self.ser = None
        self.running = True
        self.mutex = QMutex()
        # Очередь команд для отправки в Arduino
        self.command_queue = []
        self.queue_mutex = QMutex()

    def send_command(self, command_dict: dict):
        """Добавить команду в очередь на отправку."""
        self.queue_mutex.lock()
        self.command_queue.append(json.dumps(command_dict) + '\n')
        self.queue_mutex.unlock()

    def run(self):
        try:
            self.ser = serial.Serial(self.port, BAUD_RATE, timeout=1)
            self.connection_status.emit(True, f"Подключено к {self.port}")
        except Exception as e:
            self.connection_status.emit(False, f"Ошибка подключения: {e}")
            return

        while self.running:
            try:
                # Чтение данных от Arduino
                if self.ser and self.ser.in_waiting:
                    line = self.ser.readline().decode(errors='ignore').strip()
                    if line:
                        data = json.loads(line)
                        self.data_received.emit(data)

                # Отправка команд из очереди
                self.queue_mutex.lock()
                if self.command_queue:
                    cmd = self.command_queue.pop(0)
                    self.ser.write(cmd.encode())
                self.queue_mutex.unlock()

                # Проверка соединения (лёгкий пинг)
                if self.ser and self.ser.timeout != 0:
                    self.ser.write(b'')  # тестовый запрос
            except Exception as e:
                # Ошибка чтения/записи - вероятно, потеря связи
                self.disconnected.emit()
                break
            time.sleep(0.001)

        if self.ser:
            try:
                self.ser.close()
            except:
                pass

    def stop(self):
        self.running = False
        self.wait()


# ================== КЛАССЫ ДЛЯ АУДИО ==================
class AudioManager:
    def __init__(self):
        self.sessions = []
        self.mic = self.get_microphone()

    def get_microphone(self):
        try:
            dev = AudioUtilities.GetMicrophone()
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(iface, POINTER(IAudioEndpointVolume))
        except Exception:
            return None

    def get_all_sessions(self):
        sessions = []
        try:
            for sess in AudioUtilities.GetAllSessions():
                if sess.Process:
                    sessions.append({
                        'name': sess.Process.name(),
                        'pid': sess.ProcessId,
                        'volume': sess.SimpleAudioVolume.GetMasterVolume(),
                        'session': sess
                    })
        except Exception as e:
            print(f"Ошибка получения аудиосессий: {e}")
        return sessions

    def set_session_volume(self, session, level: float):
        try:
            session.SimpleAudioVolume.SetMasterVolume(level, None)
        except Exception as e:
            print(f"Ошибка установки громкости: {e}")

    def set_microphone_volume(self, level: float):
        if self.mic:
            try:
                self.mic.SetMasterVolumeLevelScalar(level, None)
            except Exception as e:
                print(f"Ошибка установки громкости микрофона: {e}")


# ================== VU-МЕТР ==================
class VUMeter(QWidget):
    def __init__(self, parent=None, orientation=Qt.Horizontal):
        super().__init__(parent)
        self.orientation = orientation
        self.value = 0.0
        self.setMinimumHeight(20 if orientation == Qt.Horizontal else 100)
        self.setMinimumWidth(100 if orientation == Qt.Horizontal else 20)

    def setValue(self, val):
        self.value = max(0.0, min(1.0, val))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        w, h = rect.width(), rect.height()

        painter.fillRect(rect, QColor(40, 40, 40))

        if self.orientation == Qt.Horizontal:
            fill_width = int(w * self.value)
            painter.fillRect(0, 0, fill_width, h, QColor(0, 255, 0))
        else:
            fill_height = int(h * self.value)
            painter.fillRect(0, h - fill_height, w, fill_height, QColor(0, 255, 0))


# ================== ВИДЖЕТ КАНАЛА ==================
class ChannelWidget(QFrame):
    def __init__(self, channel_num: int, main_window):
        super().__init__()
        self.channel_num = channel_num
        self.main = main_window
        self.processes: List[str] = []
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.Box)
        self.setLineWidth(2)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.label = QLabel(f"Канал {channel_num}")
        self.label.setFont(QFont("Arial", 10, QFont.Bold))
        header.addWidget(self.label)
        header.addStretch()
        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(20, 20)
        clear_btn.clicked.connect(self.clear_channel)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.vu = VUMeter(orientation=Qt.Horizontal)
        layout.addWidget(self.vu)

        self.proc_list = QLabel("(пусто)")
        self.proc_list.setWordWrap(True)
        self.proc_list.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.proc_list)

        self.vol_label = QLabel("0%")
        self.vol_label.setAlignment(Qt.AlignRight)
        layout.addWidget(self.vol_label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        proc_name = event.mimeData().text()
        self.main.assign_process_to_channel(proc_name, self.channel_num)

    def add_process(self, proc_name: str):
        if proc_name not in self.processes:
            self.processes.append(proc_name)
        self.update_display()

    def remove_process(self, proc_name: str):
        if proc_name in self.processes:
            self.processes.remove(proc_name)
        self.update_display()

    def clear_channel(self):
        self.processes.clear()
        self.main.remove_channel_mapping(self.channel_num)
        self.update_display()

    def update_display(self):
        if self.processes:
            self.proc_list.setText("\n".join(self.processes))
        else:
            self.proc_list.setText("(пусто)")

    def set_vu(self, value: float):
        self.vu.setValue(value)
        self.vol_label.setText(f"{int(value*100)}%")


# ================== ГЛАВНОЕ ОКНО ==================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.audio = AudioManager()
        self.mapping = self.load_mapping()
        self.config = self.load_config()
        self.channels: Dict[int, ChannelWidget] = {}
        self.serial_reader: Optional[SerialReader] = None
        self.current_sessions: List[dict] = []
        self.reconnect_timer = QTimer()
        self.reconnect_timer.setInterval(5000)  # 5 секунд
        self.reconnect_timer.timeout.connect(self.try_auto_connect)

        self.initUI()
        self.setup_tray()
        self.try_auto_connect()
        self.start_scan_timer()

    def initUI(self):
        self.setWindowTitle("WiMix Audio Controller")
        self.setGeometry(100, 100, 950, 600)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Левая панель
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # Блок выбора порта
        port_group = QFrame()
        port_group.setFrameStyle(QFrame.Box)
        port_layout = QGridLayout(port_group)

        port_layout.addWidget(QLabel("COM-порт:"), 0, 0)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(100)
        port_layout.addWidget(self.port_combo, 0, 1)

        self.refresh_ports_btn = QPushButton("Обновить")
        self.refresh_ports_btn.clicked.connect(self.refresh_ports_list)
        port_layout.addWidget(self.refresh_ports_btn, 0, 2)

        self.connect_btn = QPushButton("Подключиться")
        self.connect_btn.clicked.connect(self.manual_connect)
        port_layout.addWidget(self.connect_btn, 0, 3)

        left_layout.addWidget(port_group)

        # ========== НОВЫЙ БЛОК УПРАВЛЕНИЯ ЯРКОСТЬЮ ==========
        brightness_group = QFrame()
        brightness_group.setFrameStyle(QFrame.Box)
        brightness_layout = QHBoxLayout(brightness_group)

        brightness_layout.addWidget(QLabel("Яркость ленты:"))
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 255)
        # Загружаем значение из конфига, по умолчанию 7
        self.brightness_slider.setValue(self.config.get("led_brightness", 7))
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        brightness_layout.addWidget(self.brightness_slider)

        self.brightness_label = QLabel(str(self.brightness_slider.value()))
        brightness_layout.addWidget(self.brightness_label)

        left_layout.addWidget(brightness_group)
        # =====================================================

        # Список приложений
        left_layout.addWidget(QLabel("Активные приложения:"))

        self.app_list = QListWidget()
        self.app_list.setDragEnabled(True)
        self.app_list.setSelectionMode(QListWidget.SingleSelection)
        self.app_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.app_list.customContextMenuRequested.connect(self.show_app_context_menu)
        self.app_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        left_layout.addWidget(self.app_list)

        refresh_btn = QPushButton("Обновить список")
        refresh_btn.clicked.connect(self.update_app_list)
        left_layout.addWidget(refresh_btn)

        # Правая панель: каналы
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("Каналы:"))

        for i in range(1, 6):
            ch = ChannelWidget(i, self)
            self.channels[i] = ch
            right_layout.addWidget(ch)

        right_layout.addStretch()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 600])

        main_layout.addWidget(splitter)

        self.statusBar().showMessage("Поиск Arduino...")

        self.refresh_ports_list()
        self.restore_mapping()

    def setup_tray(self):
        """Настройка иконки в системном трее."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        tray_menu = QMenu()
        show_action = QAction("Показать окно", self)
        show_action.triggered.connect(self.show_window)
        tray_menu.addAction(show_action)

        hide_action = QAction("Скрыть окно", self)
        hide_action.triggered.connect(self.hide_window)
        tray_menu.addAction(hide_action)

        tray_menu.addSeparator()

        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_window()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_window(self):
        self.hide()

    def quit_app(self):
        if self.serial_reader:
            self.serial_reader.stop()
        self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event):
        """При закрытии окна сворачиваем в трей, а не выходим."""
        event.ignore()
        self.hide_window()
        self.tray_icon.showMessage(
            "WiMix Controller",
            "Приложение свёрнуто в трей",
            QSystemTrayIcon.Information,
            2000
        )

    # ---------- Управление портом ----------
    def refresh_ports_list(self):
        self.port_combo.clear()
        ports = ArduinoFinder.get_ports_list()
        if ports:
            self.port_combo.addItems(ports)
        else:
            self.port_combo.addItem("Нет доступных портов")

    def load_config(self) -> dict:
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Ошибка сохранения config: {e}")

    def try_auto_connect(self):
        """Пытается подключиться: сначала последний использованный порт, затем поиск."""
        # Если уже подключены, ничего не делаем
        if self.serial_reader and self.serial_reader.isRunning():
            self.reconnect_timer.stop()
            return

        # Пробуем последний успешный порт
        last_port = self.config.get("last_port")
        if last_port:
            if last_port in ArduinoFinder.get_ports_list():
                self.connect_to_port(last_port)
                return

        # Иначе ищем устройство
        port = ArduinoFinder.find_port()
        if port:
            self.connect_to_port(port)
        else:
            self.statusBar().showMessage("Arduino не найдена. Повторная попытка через 5 сек...")
            self.reconnect_timer.start()

    def connect_to_port(self, port: str):
        if self.serial_reader and self.serial_reader.isRunning():
            self.serial_reader.stop()
            self.serial_reader = None

        self.statusBar().showMessage(f"Подключение к {port}...")
        self.serial_reader = SerialReader(port)
        self.serial_reader.data_received.connect(self.on_arduino_data)
        self.serial_reader.connection_status.connect(self.on_connection_status)
        self.serial_reader.disconnected.connect(self.on_disconnected)
        self.serial_reader.start()

        # Сохраняем порт как последний
        self.config["last_port"] = port
        self.save_config()

        # Обновим комбобокс
        index = self.port_combo.findText(port)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)

        # Отправляем текущую яркость после подключения
        QTimer.singleShot(1000, lambda: self.on_brightness_changed(self.brightness_slider.value()))

    def manual_connect(self):
        port = self.port_combo.currentText()
        if port and port != "Нет доступных портов":
            self.connect_to_port(port)

    def on_connection_status(self, success: bool, message: str):
        self.statusBar().showMessage(message)
        if success:
            self.reconnect_timer.stop()
        else:
            self.reconnect_timer.start()

    def on_disconnected(self):
        self.statusBar().showMessage("Связь с Arduino потеряна. Переподключение...")
        if self.serial_reader:
            self.serial_reader.stop()
            self.serial_reader = None
        self.reconnect_timer.start()

    # ---------- Обработка данных с Arduino ----------
    def on_arduino_data(self, data: dict):
        for i in range(1, 6):
            raw = data.get(f"f{i}", 0)
            level = raw / 4095.0
            if i in self.channels:
                self.channels[i].set_vu(level)
                self.apply_volume_to_channel(i, level)

    def apply_volume_to_channel(self, channel: int, level: float):
        proc_names = self.channels[channel].processes
        for sess_info in self.current_sessions:
            if sess_info['name'] in proc_names:
                self.audio.set_session_volume(sess_info['session'], level)
        if MICROPHONE_NAME in proc_names:
            self.audio.set_microphone_volume(level)

    # ========== НОВЫЙ МЕТОД ДЛЯ ИЗМЕНЕНИЯ ЯРКОСТИ ==========
    def on_brightness_changed(self, value):
        self.brightness_label.setText(str(value))
        # Сохраняем в конфиг
        self.config["led_brightness"] = value
        self.save_config()
        # Отправляем команду Arduino, если есть подключение
        if self.serial_reader and self.serial_reader.isRunning():
            self.serial_reader.send_command({"cmd": "set_brightness", "value": value})
    # =======================================================

    # ---------- Управление маппингом ----------
    def load_mapping(self) -> Dict[str, int]:
        try:
            with open(MAPPING_FILE, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            print(f"Ошибка загрузки mapping: {e}")
            return {}

    def save_mapping(self):
        try:
            with open(MAPPING_FILE, 'w') as f:
                json.dump(self.mapping, f, indent=4)
        except Exception as e:
            print(f"Ошибка сохранения mapping: {e}")

    def restore_mapping(self):
        for proc, ch_num in self.mapping.items():
            if ch_num in self.channels:
                self.channels[ch_num].add_process(proc)

    def assign_process_to_channel(self, process_name: str, channel: int):
        old_ch = self.mapping.get(process_name)
        if old_ch and old_ch in self.channels:
            self.channels[old_ch].remove_process(process_name)

        self.mapping[process_name] = channel
        self.channels[channel].add_process(process_name)
        self.save_mapping()
        self.update_app_list()

    def remove_channel_mapping(self, channel: int):
        to_remove = []
        for proc, ch in self.mapping.items():
            if ch == channel:
                to_remove.append(proc)
        for proc in to_remove:
            del self.mapping[proc]
        self.save_mapping()
        self.update_app_list()

    # ---------- Список приложений ----------
    def start_scan_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_app_list)
        self.timer.start(3000)

    def update_app_list(self):
        self.current_sessions = self.audio.get_all_sessions()
        self.app_list.clear()

        if self.audio.mic is not None:
            mic_item = QListWidgetItem(MICROPHONE_NAME)
            mic_item.setData(Qt.UserRole, MICROPHONE_NAME)
            if MICROPHONE_NAME in self.mapping:
                mic_item.setForeground(QColor(100, 100, 255))
                mic_item.setToolTip(f"Канал {self.mapping[MICROPHONE_NAME]}")
            self.app_list.addItem(mic_item)

        for sess in self.current_sessions:
            name = sess['name']
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            if name in self.mapping:
                item.setForeground(QColor(100, 100, 255))
                item.setToolTip(f"Канал {self.mapping[name]}")
            self.app_list.addItem(item)

    # ---------- Контекстное меню ----------
    def show_app_context_menu(self, position):
        item = self.app_list.itemAt(position)
        if not item:
            return
        process_name = item.data(Qt.UserRole)
        menu = QMenu()
        for ch_num in range(1, 6):
            action = menu.addAction(f"Канал {ch_num}")
            action.setData(ch_num)
        chosen = menu.exec_(self.app_list.mapToGlobal(position))
        if chosen:
            channel = chosen.data()
            self.assign_process_to_channel(process_name, channel)

    def on_item_double_clicked(self, item):
        process_name = item.data(Qt.UserRole)
        channel, ok = QInputDialog.getInt(
            self, "Назначить канал",
            f"Введите номер канала (1-5) для {process_name}:",
            1, 1, 5
        )
        if ok:
            self.assign_process_to_channel(process_name, channel)


# ================== ЗАПУСК ==================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # чтобы окно закрывалось, а приложение оставалось в трее
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
