# src/handlers/commands.py
import logging
import uuid
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from queue import Empty

from ..services.formatters import format_funding_update
from ..keyboards import get_main_menu_keyboard
from ..user_manager import get_user_settings

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info(f"Користувач {chat_id} запустив /start.")

    settings = get_user_settings(chat_id)
    task_queue = context.bot_data['task_queue']
    result_queue = context.bot_data['result_queue']
    
    # Створюємо унікальний ID для нашого завдання
    job_id = str(uuid.uuid4())
    
    await update.message.reply_text("Відправляю завдання в чергу...")
    
    # Кладемо завдання в чергу для воркера
    task_queue.put((job_id, settings['exchanges']))
    
    processing_message = await update.message.reply_text("Завдання в черзі. Очікую на результат від воркера...")
    
    # Асинхронно чекаємо на результат
    result_df = None
    start_time = time.time()
    while time.time() - start_time < 120: # Чекаємо до 2 хвилин
        try:
            # Неблокуючий запит до черги результатів
            job_result_id, df = result_queue.get_nowait()
            if job_result_id == job_id:
                result_df = df
                logger.info(f"Отримано результат для завдання #{job_id}")
                break # Виходимо з циклу, якщо знайшли наш результат
            else:
                # Повертаємо чужий результат назад в чергу
                result_queue.put((job_result_id, df))
        except Empty:
            # Якщо черга пуста, чекаємо трохи і пробуємо знову
            await asyncio.sleep(1)
            
    if result_df is not None:
        message_text = format_funding_update(result_df, settings['threshold'])
        await processing_message.edit_text(
            text=message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(),
            disable_web_page_preview=True
        )
    else:
        logger.error(f"Таймаут очікування результату для завдання #{job_id}")
        await processing_message.edit_text("😔 Воркер не відповів вчасно. Спробуйте пізніше.")