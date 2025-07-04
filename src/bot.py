# src/bot.py
import os
import logging
import multiprocessing as mp
import sys
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler

# Додаємо корінь проекту до шляхів пошуку, щоб імпорти працювали надійно
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- ЗМІНА ТУТ ---
from worker import worker_process 
# ------------------
from src.handlers import commands

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def main() -> None:
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("Не знайдено TELEGRAM_BOT_TOKEN")

    task_queue = mp.Queue()
    result_queue = mp.Queue()

    worker = mp.Process(target=worker_process, args=(task_queue, result_queue), daemon=True)
    worker.start()
    logger.info("Процес-воркер запущений.")

    application = Application.builder().token(TOKEN).build()
    application.bot_data["task_queue"] = task_queue
    application.bot_data["result_queue"] = result_queue

    application.add_handler(CommandHandler("start", commands.start))
    
    logger.info("Бот запускається...")
    
    try:
        application.run_polling(drop_pending_updates=True)
    finally:
        logger.info("Зупинка бота...")
        task_queue.put(None)
        worker.join(timeout=5)
        if worker.is_alive():
            worker.terminate()
        logger.info("Бот та воркер зупинені.")

if __name__ == "__main__":
    if os.name == 'nt':
        mp.set_start_method('spawn', force=True)
    main()