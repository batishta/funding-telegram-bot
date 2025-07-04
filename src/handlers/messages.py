# src/handlers/messages.py
import html
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from ..services import funding_service, formatters
from ..user_manager import get_user_settings

logger = logging.getLogger(__name__)

async def ticker_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє текстове повідомлення як запит на інформацію по тикеру."""
    ticker = update.message.text.strip().upper()
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    
    logger.info(f"Користувач {chat_id} запитав інформацію по тикеру: {ticker}")
    
    if len(ticker) < 2:
        return

    processing_message = await update.message.reply_text(
        f"🔍 Шукаю дані для <b>{html.escape(ticker)}</b>...", 
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Запускаємо СИНХРОННУ функцію в окремому потоці
        df = await context.application.create_task(
            funding_service.get_funding_for_ticker_sync,
            (ticker, settings['exchanges'])
        )
        
        message_text = formatters.format_ticker_info(df, ticker)
        
        await processing_message.edit_text(
            text=message_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Помилка при пошуку тикера {ticker} для {chat_id}: {e}", exc_info=True)
        await processing_message.edit_text(
            f"😔 Виникла помилка при пошуку даних для <b>{html.escape(ticker)}</b>."
        )