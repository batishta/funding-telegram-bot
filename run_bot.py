# run_bot.py (СУПЕР-СПРОЩЕНА ВЕРСІЯ)

import os
import logging
import time

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# Імпортуємо наші робочі модулі
# Припускаємо, що цей файл в корені, а поруч є папка src
from src.services.funding_service import get_all_funding_data_sequential
from src.services.formatters import format_funding_update
from src.keyboards import get_main_menu_keyboard

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --- Налаштування ---
# Оскільки ми не можемо зберігати налаштування, вони будуть однакові для всіх
DEFAULT_EXCHANGES = ['Binance', 'ByBit', 'OKX', 'MEXC', 'Bitget', 'KuCoin']
DEFAULT_THRESHOLD = 0.3


# --- Обробник команди /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
        
    chat_id = update.effective_chat.id
    logger.info(f"!!! ОТРИМАНО /start ВІД {chat_id} !!!")
    
    await update.message.reply_text("Починаю пошук... Це може зайняти до хвилини, бот не буде відповідати в цей час.")
    logger.info("Надіслано перше повідомлення.")

    try:
        # --- НАЙПРОСТІШИЙ ВИКЛИК ---
        # Викликаємо функцію напряму. Це заблокує бота, але ми повинні побачити логи.
        logger.info(">>> Починаю ПРЯМИЙ виклик get_all_funding_data_sequential...")
        
        start_time = time.time()
        df = get_all_funding_data_sequential(DEFAULT_EXCHANGES)
        end_time = time.time()
        
        logger.info(f"<<< Виклик завершено за {end_time - start_time:.2f} секунд.")
        
        if df.empty:
            logger.info("Отримано пустий DataFrame, надсилаю повідомлення про це.")
            await update.message.reply_text("Не вдалося отримати дані з бірж.")
            return

        message_text = format_funding_update(df, DEFAULT_THRESHOLD)
        logger.info("Повідомлення сформовано, надсилаю...")
        
        await update.message.reply_text(
            text=message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(),
            disable_web_page_preview=True
        )
        logger.info("Фінальне повідомлення надіслано успішно.")

    except Exception as e:
        logger.error(f"Критична помилка в /start для {chat_id}: {e}", exc_info=True)
        await update.message.reply_text("😔 Виникла критична помилка під час обробки.")


# --- Головна функція запуску ---
def main() -> None:
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.critical("!!! НЕ ЗНАЙДЕНО TELEGRAM_BOT_TOKEN !!!")
        return

    application = Application.builder().token(TOKEN).build()
    
    # Реєструємо тільки /start
    application.add_handler(CommandHandler("start", start))
    
    logger.info("Бот запускається в НАЙПРОСТІШОМУ режимі...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()