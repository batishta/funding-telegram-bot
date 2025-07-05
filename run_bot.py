# run_bot.py

import os
import logging
import multiprocessing as mp
import time
import uuid
import asyncio
from queue import Empty
import pandas as pd

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# Імпорти з нашого пакету src
# Ми припускаємо, що цей файл знаходиться в корені, а поруч є папка src
from src.services.funding_service import get_all_funding_data_sequential
from src.services.formatters import format_funding_update
from src.keyboards import get_main_menu_keyboard
from src.user_manager import get_user_settings, _save_settings, _load_settings

# --- Налаштування логування ---
# Встановлюємо базову конфігурацію, щоб бачити логи з усіх модулів
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler() # Виводимо логи в консоль
    ]
)
# Зменшуємо кількість логів від сторонніх бібліотек, щоб не заважали
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

# --- Логіка Воркера ---
def worker_process(task_queue: mp.Queue, result_queue: mp.Queue):
    """Процес, який слухає завдання і виконує їх."""
    worker_logger = logging.getLogger("Worker")
    worker_logger.info("Процес-воркер запущений і готовий до роботи.")

    while True:
        try:
            task = task_queue.get()
            
            if task is None:
                worker_logger.info("Отримано сигнал завершення. Воркер зупиняється.")
                break

            job_id, exchanges_list = task
            worker_logger.info(f"Отримано завдання #{job_id[:6]} для бірж: {exchanges_list}")
            
            result_df = get_all_funding_data_sequential(exchanges_list)
            
            result_queue.put((job_id, result_df))
            worker_logger.info(f"Завдання #{job_id[:6]} виконано, результат відправлено.")

        except Exception as e:
            worker_logger.error(f"Критична помилка у воркері: {e}", exc_info=True)


# --- Обробник команди /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробник команди /start, який працює з чергами."""
    bot_logger = logging.getLogger("BotHandler")
    bot_logger.info("!!! ОТРИМАНО КОМАНДУ /start !!!")

    if not update.effective_chat:
        bot_logger.warning("Отримано оновлення без чату, ігнорую.")
        return
        
    chat_id = update.effective_chat.id
    bot_logger.info(f"Початок обробки для чату {chat_id}.")

    try:
        _load_settings()
        settings = get_user_settings(chat_id)
        _save_settings()
        bot_logger.info("Налаштування користувача завантажено/створено.")

        task_queue = context.bot_data['task_queue']
        result_queue = context.bot_data['result_queue']
        
        job_id = str(uuid.uuid4())
        
        await update.message.reply_text("Відправляю завдання в чергу для обробки...")
        bot_logger.info(f"Створено завдання #{job_id[:6]}.")
        
        exchanges_to_scan = list(settings['exchanges'])
        task_queue.put((job_id, exchanges_to_scan))
        bot_logger.info(f"Завдання #{job_id[:6]} відправлено у воркер.")
        
        processing_message = await update.message.reply_text(f"Завдання в черзі. Очікую на результат...")
        
        result_df = None
        start_time = time.time()
        while time.time() - start_time < 120:
            if not result_queue.empty():
                try:
                    job_result_id, df = result_queue.get_nowait()
                    if job_result_id == job_id:
                        result_df = df
                        bot_logger.info(f"Отримано результат для завдання #{job_id[:6]}")
                        break
                    else:
                        result_queue.put((job_result_id, df))
                except Empty:
                    pass
            
            await asyncio.sleep(1)
                
        if result_df is not None:
            bot_logger.info(f"Форматую повідомлення для завдання #{job_id[:6]}")
            message_text = format_funding_update(result_df, settings['threshold'])
            await processing_message.edit_text(
                text=message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu_keyboard(),
                disable_web_page_preview=True
            )
            bot_logger.info(f"Повідомлення для #{job_id[:6]} успішно відправлено.")
        else:
            bot_logger.error(f"Таймаут очікування результату для завдання #{job_id[:6]}")
            await processing_message.edit_text("😔 Воркер не відповів вчасно. Спробуйте пізніше.")

    except Exception as e:
        bot_logger.error(f"Критична помилка в обробнику /start: {e}", exc_info=True)
        await update.message.reply_text("Вибачте, сталася непередбачувана помилка.")


# --- Головна функція запуску ---
def main() -> None:
    """Головна функція запуску."""
    main_logger = logging.getLogger("Main")
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        main_logger.critical("!!! НЕ ЗНАЙДЕНО TELEGRAM_BOT_TOKEN !!! Перевірте змінні середовища на Railway.")
        return

    task_queue = mp.Queue()
    result_queue = mp.Queue()

    worker = mp.Process(target=worker_process, args=(task_queue, result_queue), daemon=True)
    worker.start()
    main_logger.info("Процес-воркер запущений.")

    application = Application.builder().token(TOKEN).build()
    application.bot_data["task_queue"] = task_queue
    application.bot_data["result_queue"] = result_queue

    application.add_handler(CommandHandler("start", start))
    
    main_logger.info("Бот запускається...")
    
    try:
        application.run_polling(drop_pending_updates=True)
    finally:
        main_logger.info("Зупинка бота...")
        task_queue.put(None)
        worker.join(timeout=5)
        if worker.is_alive():
            worker.terminate()
        main_logger.info("Бот та воркер зупинені.")

if __name__ == "__main__":
    # Цей блок критично важливий для Windows та macOS
    if __package__ is None and os.name != 'posix':
        mp.set_start_method('spawn', force=True)
    main()