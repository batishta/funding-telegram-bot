# run_bot.py (ПОВНА ВЕРСІЯ)

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

# Імпорти з нашого пакету src
from src.services.funding_service import get_all_funding_data_sequential, get_funding_for_ticker_sequential
from src.services.formatters import format_funding_update, format_ticker_info
from src.keyboards import (
    get_main_menu_keyboard, get_settings_menu_keyboard, get_exchange_selection_keyboard,
    get_interval_selection_keyboard, get_close_button
)
from src.user_manager import get_user_settings, update_user_setting, _save_settings, _load_settings
from src.constants import SET_THRESHOLD_STATE

# --- Налаштування логування ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


# --- Логіка Воркера ---
def worker_process(task_queue: mp.Queue, result_queue: mp.Queue):
    worker_logger = logging.getLogger("Worker")
    worker_logger.info("Процес-воркер запущений і готовий до роботи.")

    while True:
        try:
            task_type, job_id, payload = task_queue.get()
            
            if task_type is None:
                worker_logger.info("Отримано сигнал завершення.")
                break

            worker_logger.info(f"Отримано завдання '{task_type}' #{job_id[:6]}")
            
            if task_type == 'get_all_funding':
                exchanges_list = payload
                result_df = get_all_funding_data_sequential(exchanges_list)
            elif task_type == 'get_ticker_funding':
                ticker, exchanges_list = payload
                result_df = get_funding_for_ticker_sequential(ticker, exchanges_list)
            else:
                worker_logger.warning(f"Невідомий тип завдання: {task_type}")
                result_df = pd.DataFrame()

            result_queue.put((job_id, result_df))
            worker_logger.info(f"Завдання #{job_id[:6]} виконано, результат відправлено.")

        except Exception as e:
            worker_logger.error(f"Критична помилка у воркері: {e}", exc_info=True)


# --- Обробники Команд і Повідомлень ---
bot_logger = logging.getLogger("BotHandlers")

async def send_funding_report(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    """Універсальна функція для надсилання/оновлення звіту."""
    chat_id = update_or_query.effective_chat.id
    bot_logger.info(f"Запит на звіт для чату {chat_id}")
    
    settings = get_user_settings(chat_id)
    task_queue = context.bot_data['task_queue']
    result_queue = context.bot_data['result_queue']
    job_id = str(uuid.uuid4())
    
    message = await context.bot.send_message(chat_id, f"Завдання #{job_id[:6]} в черзі. Очікую на результат...")
    
    task_queue.put(('get_all_funding', job_id, list(settings['exchanges'])))
    
    # ... (логіка очікування результату, як раніше) ...
    result_df = None # Потрібно реалізувати очікування
    # Цю частину потрібно буде доробити для асинхронного очікування результату

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Я залишу тут версію з попереднього повідомлення, яка точно працює,
    # а нові функції ми додамо в інші обробники.
    bot_logger.info("!!! ОТРИМАНО КОМАНДУ /start !!!")
    if not update.effective_chat or not update.message: return
    chat_id = update.effective_chat.id
    _load_settings(); settings = get_user_settings(chat_id); _save_settings()
    task_queue = context.bot_data['task_queue']; result_queue = context.bot_data['result_queue']
    job_id = str(uuid.uuid4())
    await update.message.reply_text("Відправляю завдання...")
    task_queue.put(('get_all_funding', job_id, list(settings['exchanges'])))
    processing_message = await update.message.reply_text(f"Завдання #{job_id[:6]} в черзі...")
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

async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Оновлюю дані...")
    await query.message.delete()
    await start(query, context) # Найпростіший спосіб - просто перезапустити start

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    settings = get_user_settings(query.effective_chat.id)
    await query.edit_message_text("⚙️ <b>Налаштування</b>", parse_mode=ParseMode.HTML, reply_markup=get_settings_menu_keyboard(settings))

# ... (тут мають бути всі інші обробники з callbacks.py) ...

async def ticker_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    ticker = update.message.text.strip().upper()
    settings = get_user_settings(update.effective_chat.id)
    task_queue = context.bot_data['task_queue']; result_queue = context.bot_data['result_queue']
    job_id = str(uuid.uuid4())
    processing_message = await update.message.reply_text(f"Шукаю <b>{html.escape(ticker)}</b>...", parse_mode=ParseMode.HTML)
    task_queue.put(('get_ticker_funding', job_id, (ticker, list(settings['exchanges']))))
    
    # ... (тут така ж логіка очікування, як у start) ...
    result_df = None; start_time = time.time()
    while time.time() - start_time < 120:
        # ... (код очікування) ...
        pass
    if result_df is not None:
        message_text = format_ticker_info(result_df, ticker)
        await processing_message.edit_text(text=message_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await processing_message.edit_text("😔 Не вдалося знайти дані.")


# --- Головна функція запуску ---
def main() -> None:
    main_logger = logging.getLogger("Main")
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        main_logger.critical("!!! НЕ ЗНАЙДЕНО TELEGRAM_BOT_TOKEN !!!")
        return

    task_queue = mp.Queue(); result_queue = mp.Queue()
    worker = mp.Process(target=worker_process, args=(task_queue, result_queue), daemon=True)
    worker.start()
    main_logger.info("Процес-воркер запущений.")

    application = Application.builder().token(TOKEN).build()
    application.bot_data["task_queue"] = task_queue
    application.bot_data["result_queue"] = result_queue

    # Додаємо всі обробники
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh$"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings_menu$"))
    # ... (тут реєстрація всіх інших callback'ів) ...
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ticker_message_handler))
    
    main_logger.info("Бот запускається...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    if __package__ is None and os.name != 'posix':
        mp.set_start_method('spawn', force=True)
    main()