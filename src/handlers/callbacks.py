# src/handlers/callbacks.py

import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from ..user_manager import get_user_settings, update_user_setting
from ..services import funding_service, formatters
from ..keyboards import (
    get_main_menu_keyboard,
    get_settings_menu_keyboard,
    get_exchange_selection_keyboard,
    get_interval_selection_keyboard,
    get_close_button
)
from ..constants import SET_THRESHOLD_STATE

logger = logging.getLogger(__name__)

async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Оновлює головне повідомлення з фандінгом, запускаючи запит у фоні."""
    query = update.callback_query
    await query.answer("Оновлюю дані...")
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    
    try:
        # Запускаємо СИНХРОННУ функцію в окремому потоці
        df = await context.application.create_task(
            funding_service.get_all_funding_data_sync,
            (settings['exchanges'],)
        )
        message_text = formatters.format_funding_update(df, settings['threshold'])
        
        await query.edit_message_text(
            text=message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.warning(f"Не вдалося оновити повідомлення для {chat_id}: {e}", exc_info=True)
        try:
            await query.answer("Помилка оновлення. Можливо, дані не змінилися.", show_alert=True)
        except Exception:
            pass

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує головне меню налаштувань."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    
    await query.edit_message_text(
        text="⚙️ <b>Налаштування</b>\n\nОберіть опцію для зміни:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_settings_menu_keyboard(settings)
    )

async def close_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Закриває меню налаштувань та оновлює головне повідомлення."""
    query = update.callback_query
    await query.answer("Зберігаю налаштування та оновлюю...")
    # Просто викликаємо функцію оновлення, яка вже містить правильну логіку
    await refresh_callback(update, context)

async def exchange_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує меню вибору бірж."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    
    await query.edit_message_text(
        text="🌐 <b>Вибір бірж</b>\n\nОберіть біржі для сканування:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_exchange_selection_keyboard(settings['exchanges'])
    )

async def toggle_exchange_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Перемикає стан обраної біржі."""
    query = update.callback_query
    exchange_name = query.data.split('_')[-1]
    chat_id = update.effective_chat.id
    
    settings = get_user_settings(chat_id)
    current_exchanges = settings.get('exchanges', [])
    
    if exchange_name in current_exchanges:
        current_exchanges.remove(exchange_name)
    else:
        current_exchanges.append(exchange_name)
    
    update_user_setting(chat_id, 'exchanges', current_exchanges)
    
    await query.edit_message_reply_markup(
        reply_markup=get_exchange_selection_keyboard(current_exchanges)
    )
    await query.answer(f"Біржа {exchange_name} {'увімкнена' if exchange_name in current_exchanges else 'вимкнена'}")

async def set_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Починає діалог для зміни порогу фандінгу."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)

    text = (f"Поточний поріг: <b>{settings['threshold']}%</b>.\n\n"
            "Надішліть нове значення (напр., <code>0.5</code>), щоб змінити його.")
    
    await query.edit_message_text(
        text, 
        parse_mode=ParseMode.HTML, 
        reply_markup=get_close_button()
    )
    return SET_THRESHOLD_STATE

async def interval_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує меню вибору інтервалу оновлення."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text="⏳ <b>Час оновлення</b>\n\nЦя функція в розробці.",
        parse_mode=ParseMode.HTML,
        reply_markup=get_interval_selection_keyboard()
    )

async def set_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Встановлює новий інтервал."""
    query = update.callback_query
    interval_minutes = int(query.data.split('_')[-1])
    chat_id = update.effective_chat.id
    
    update_user_setting(chat_id, 'interval', interval_minutes)
    settings = get_user_settings(chat_id)
    
    await query.answer(f"Інтервал встановлено на {interval_minutes} хв.")
    await query.edit_message_text(
        text="⚙️ <b>Налаштування</b>\n\nОберіть опцію для зміни:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_settings_menu_keyboard(settings)
    )

async def toggle_bot_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Перемикає стан бота (ON/OFF)."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    
    new_status = not settings.get('enabled', True)
    update_user_setting(chat_id, 'enabled', new_status)
    settings['enabled'] = new_status
    
    await query.answer(f"Бот тепер {'УВІМКНЕНИЙ' if new_status else 'ВИМКНЕНИЙ'}")
    await query.edit_message_reply_markup(reply_markup=get_settings_menu_keyboard(settings))

async def delete_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Просто видаляє повідомлення, в якому була натиснута кнопка."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()