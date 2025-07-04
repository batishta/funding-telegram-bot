# src/user_manager.py
import json
import os
from threading import Lock
from .config import DEFAULT_SETTINGS

SETTINGS_FILE = os.path.join('data', 'user_settings.json')
_settings = {}
_lock = Lock()

def _load_settings():
    global _settings
    if not os.path.exists(os.path.dirname(SETTINGS_FILE)):
        os.makedirs(os.path.dirname(SETTINGS_FILE))
    try:
        with open(SETTINGS_FILE, 'r') as f:
            _settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _settings = {}

def _save_settings():
    with _lock:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(_settings, f, indent=4)

def get_user_settings(chat_id: int) -> dict:
    """Отримує налаштування для конкретного користувача."""
    chat_id_str = str(chat_id)
    with _lock:
        if chat_id_str not in _settings:
            _settings[chat_id_str] = DEFAULT_SETTINGS.copy()
            _save_settings()
        # Переконуємось, що всі ключі з DEFAULT_SETTINGS є у користувача
        for key, value in DEFAULT_SETTINGS.items():
            if key not in _settings[chat_id_str]:
                _settings[chat_id_str][key] = value
        return _settings[chat_id_str]

def update_user_setting(chat_id: int, key: str, value):
    """Оновлює конкретне налаштування для користувача."""
    chat_id_str = str(chat_id)
    with _lock:
        if chat_id_str not in _settings:
            _settings[chat_id_str] = DEFAULT_SETTINGS.copy()
        _settings[chat_id_str][key] = value
        _save_settings()

# Завантажуємо налаштування при старті модуля
_load_settings()