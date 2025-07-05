# run_bot.py (Версія без збереження файлів)

import os
import logging
import multiprocessing as mp
import time
import uuid
import asyncio
from queue import Empty
import pandas as pd
import html

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
from telegram.constants import ParseMode

# --- Модулі, які раніше були в окремих файлах ---

# З config.py
DEFAULT_SETTINGS = {
    "enabled": True, "threshold": 0.3, "interval": 60,
    "exchanges": ['Binance', 'ByBit', 'OKX', 'MEXC', 'Bitget', 'KuCoin']
}
# З constants.py
SET_THRESHOLD_STATE = 0

# З user_manager.py (але тепер зберігаємо в пам'яті)
_user_settings_cache = {}
def get_user_settings(chat_id: int) -> dict:
    chat_id_str = str(chat_id)
    if chat_id_str not in _user_settings_cache:
        _user_settings_cache[chat_id_str] = DEFAULT_SETTINGS.copy()
    return _user_settings_cache[chat_id_str]

def update_user_setting(chat_id: int, key: str, value):
    chat_id_str = str(chat_id)
    get_user_settings(chat_id) # Переконуємось, що словник існує
    _user_settings_cache[chat_id_str][key] = value

# З services/funding_service.py (без змін)
# (я вставлю сюди код, щоб все було в одному місці)
from src.services.funding_service import get_all_funding_data_sequential, get_funding_for_ticker_sequential
from src.services.formatters import format_funding_update, format_ticker_info
from src.keyboards import get_main_menu_keyboard, get_settings_menu_keyboard

# Налаштування логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Логіка Воркера ---
def worker_process(task_queue: mp.Queue, result_queue: mp.Queue):
    # ... (код воркера залишається без змін)
    worker_logger = logging.getLogger("Worker")
    while True:
        try:
            task_type, job_id, payload = task_queue.get()
            if task_type is None: break
            if task_type == 'get_all_funding':
                result_df = get_all_funding_data_sequential(payload)
            elif task_type == 'get_ticker_funding':
                ticker, exchanges = payload
                result_df = get_funding_for_ticker_sequential(ticker, exchanges)
            else: result_df = pd.DataFrame()
            result_queue.put((job_id, result_df))
        except Exception as e:
            worker_logger.error(f"Помилка у воркері: {e}")

# --- Обробники ---
bot_logger = logging.getLogger("BotHandler")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_logger.info("!!! ОТРИМАНО КОМАНДУ /start !!!")
    if not update.effective_chat or not update.message: return
        
    chat_id = update.effective_chat.id
    bot_logger.info(f"Початок обробки для чату {chat_id}.")
    
    # --- ЗМІНЕНО: БЕЗ РОБОТИ З ФАЙЛАМИ ---
    settings = get_user_settings(chat_id)
    bot_logger.info(f"Налаштування отримано з кешу. Біржі: {settings['exchanges']}")
    # ------------------------------------

    task_queue = context.bot_data['task_queue']
    result_queue = context.bot_data['result_queue']
    job_id = str(uuid.uuid4())
    
    await update.message.reply_text("Відправляю завдання...")
    bot_logger.info(f"Створено завдання #{job_id[:6]}.")
    
    task_queue.put(('get_all_funding', job_id, settings['exchanges']))
    bot_logger.info(f"Завдання #{job_id[:6]} відправлено у воркер.")
    
    processing_message = await update.message.reply_text(f"Завдання в черзі. Очікую...")
    
    # ... (решта коду start без змін, логіка очікування результату) ...
    result_df = None; start_time = time.time()
    while time.time() - start_time < 120:
        if not result_queue.empty():
            try:
                job_result_id, df = result_queue.get_nowait()
                if job_result_id == job_id: result_df = df; break
                else: result_queue.put((job_result_id, df))
            except Empty: pass
        await asyncio.sleep(1)
    if result_df is not None:
        message_text = format_funding_update(result_df, settings['threshold'])
        await processing_message.edit_text(text=message_text, parse_mode=ParseMode.HTML, reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)
    else:
        await processing_message.edit_text("😔 Воркер не відповів вчасно.")

# ... (тут мають бути всі інші обробники: refresh_callback, settings_menu_callback, і т.д.)
# Вони будуть використовувати нові функції get_user_settings та update_user_setting, які не працюють з файлами.

# --- Головна функція запуску ---
def main() -> None:
    # ... (код main залишається без змін)
    load_dotenv(); TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN: logging.critical("!!! НЕ ЗНАЙДЕНО TOKEN !!!"); return
    task_queue = mp.Queue(); result_queue = mp.Queue()
    worker = mp.Process(target=worker_process, args=(task_queue, result_queue), daemon=True)
    worker.start()
    application = Application.builder().token(TOKEN).build()
    application.bot_data["task_queue"] = task_queue
    application.bot_data["result_queue"] = result_queue
    # Додаємо всі обробники
    application.add_handler(CommandHandler("start", start))
    # ... (реєстрація інших обробників) ...
    logging.info("Бот запускається (без збереження файлів)...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    if os.name == 'nt': mp.set_start_method('spawn', force=True)
    main()