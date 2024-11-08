from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telethon import TelegramClient
import re
from collections import defaultdict
import logging
import asyncio

# Telegram bot configuration
BOT_TOKEN = '7327291802:AAFPM911VQH5uyTX2uPG8j503NCt3r62yMs'

# Telethon client configuration
API_ID = 21202746
API_HASH = 'e700432294937e6925a83149ee7165a0'

# Create Telethon client
telethon_client = TelegramClient('test', API_ID, API_HASH)

# Excluded token address
EXCLUDED_TOKEN = 'So11111111111111111111111111111112'

class MonitoringSession:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.is_monitoring = False
        self.multi_trader_tokens = {}
        self.previous_messages = []
        self.monitoring_task = None

async def is_valid_buy_message(text):
    """Check if the message is a valid buy message"""
    buy_pattern = r'(?:BUY|Buy|buy)'
    sell_pattern = r'(?:SELL|Sell|sell)'
    
    buy_matches = list(re.finditer(buy_pattern, text))
    sell_matches = list(re.finditer(sell_pattern, text))
    
    if not sell_matches:
        return bool(buy_matches)
        
    if buy_matches and sell_matches:
        first_buy_pos = buy_matches[0].start()
        first_sell_pos = sell_matches[0].start()
        return first_buy_pos < first_sell_pos
        
    return False

async def scrap_message(chat, session, limit=50):
    """Scrape messages and track token purchases"""
    async for message in telethon_client.iter_messages(chat, limit=limit):
        if message.text:
            text = message.text

            if await is_valid_buy_message(text):
                trader_pattern = r'(?:TRADER|Trader|trader)\d+'
                trader_match = re.search(trader_pattern, text)

                solana_addresses = re.findall(r'[0-9A-HJ-NP-Za-km-z]{32,44}', text)

                if trader_match and solana_addresses:
                    last_solana_address = solana_addresses[-1]
                    trader = trader_match.group()
                    
                    if last_solana_address != EXCLUDED_TOKEN:
                        if last_solana_address not in session.multi_trader_tokens:
                            session.multi_trader_tokens[last_solana_address] = set()
                        session.multi_trader_tokens[last_solana_address].add(trader)

async def monitor_channels(context, session):
    """Monitor channels for a specific chat session"""
    chat_limits = {
        'https://t.me/ray_silver_bot': 150,
        'https://t.me/handi_cat_bot': 300,
        'https://t.me/Wallet_tracker_solana_spybot': 75,
        'https://t.me/CashCash_alert_bot': 75,
        'https://t.me/GMGN_alert_bot': 150,
        'https://t.me/Solbix_bot': 300
    }

    while session.is_monitoring:
        async with telethon_client:
            for chat_link, limit in chat_limits.items():
                await scrap_message(chat_link, session, limit)

        current_messages = []
        for address, traders in session.multi_trader_tokens.items():
            if len(traders) >= 2:
                trader_list = sorted(list(traders))
                current_messages.append(f"{len(trader_list)} traders bought {address}")

        new_messages = [msg for msg in current_messages if msg not in session.previous_messages]

        if new_messages:
            for message in new_messages:
                await context.bot.send_message(
                    chat_id=session.chat_id,
                    text=message
                )
            session.previous_messages = current_messages.copy()
        else:
            await context.bot.send_message(
                chat_id=session.chat_id,
                text="No new multiple-trader tokens found"
            )

        await asyncio.sleep(10)
        if session.is_monitoring:
            await context.bot.send_message(
                chat_id=session.chat_id,
                text=".....\n ROUND RESTARTED \n ....."
            )
        else:
            break

async def start(update, context):
    """Start the message monitoring process for a specific chat"""
    chat_id = update.effective_chat.id
    
    # Check if session exists, if not create one
    if chat_id not in context.bot_data:
        context.bot_data[chat_id] = MonitoringSession(chat_id)
    
    session = context.bot_data[chat_id]
    
    if not session.is_monitoring:
        session.is_monitoring = True
        session.monitoring_task = asyncio.create_task(monitor_channels(context, session))
        await context.bot.send_message(
            chat_id=chat_id,
            text="Monitoring started for this chat."
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Monitoring is already active for this chat."
        )

async def stop(update, context):
    """Stop the message monitoring process for a specific chat"""
    chat_id = update.effective_chat.id
    
    if chat_id in context.bot_data:
        session = context.bot_data[chat_id]
        if session.is_monitoring:
            session.is_monitoring = False
            if session.monitoring_task:
                session.monitoring_task.cancel()
            session.multi_trader_tokens.clear()
            session.previous_messages.clear()
            await context.bot.send_message(
                chat_id=chat_id,
                text="Monitoring stopped for this chat."
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Monitoring is not active for this chat."
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="No monitoring session found for this chat."
        )

def main():
    """Start the bot"""
    application = Application.builder().token(BOT_TOKEN).build()
    application.bot_data = {}

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    main()
