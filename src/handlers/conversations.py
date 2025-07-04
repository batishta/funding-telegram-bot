# src/handlers/conversations.py

import html
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from ..user_manager import update_user_setting

# Додаємо імпорт
from ..constants import SET_THRESHOLD_STATE

# ... решта коду ...

async def set_threshold_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... код функції без змін ...
    return ConversationHandler.END

# Додамо функцію для виходу з діалогу
async def close_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    return ConversationHandler.END