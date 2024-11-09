import os
import time
from datetime import datetime
from dotenv import find_dotenv, load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telethon import TelegramClient
import re
from collections import defaultdict
import logging
import asyncio


PORT = int(os.environ.get('PORT', '8080'))

# Telegram bot configuration
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

# Telethon client configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# Create Telethon client
telethon_client = TelegramClient('test', API_ID, API_HASH)

# Excluded token address
EXCLUDED_TOKEN = 'So11111111111111111111111111111112'

# Authorized users and groups (store without @ symbol)
AUTHORIZED_USERS = {'orehub1378', 'busiiiiii', 'jeremi1234'}
AUTHORIZED_GROUPS = {'THETRACKOORS'}

class MonitoringSession:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.is_monitoring = False
        self.multi_trader_tokens = {}
        self.previous_messages = []
        self.monitoring_task = None
        self.token_pump_types = {}
        self.token_market_caps = {}
        self.start_time = None
        self.round_start_time = None

async def check_authorization(update):
    """Check if the user/group is authorized to use the bot"""
    chat_id = update.effective_chat.id
    user_username = update.effective_user.username
    chat_username = update.effective_chat.username
    
    logging.info(f"Auth attempt - Chat type: {update.effective_chat.type}")
    logging.info(f"User username: {user_username}")
    logging.info(f"Chat username: {chat_username}")
    logging.info(f"Chat username (lowercase): {chat_username.lower() if chat_username else None}")
    logging.info(f"Authorized groups: {AUTHORIZED_GROUPS}")
    
    if update.effective_chat.type == 'private':
        is_authorized = user_username and user_username.lower() in {user.lower() for user in AUTHORIZED_USERS}
        logging.info(f"Private chat authorization result: {is_authorized}")
        return is_authorized
    
    is_authorized = chat_username and chat_username.lower() in {group.lower() for group in AUTHORIZED_GROUPS}
    logging.info(f"Group chat authorization result: {is_authorized}")
    return is_authorized

def extract_market_cap(text):
    """Extract market cap information from the message"""
    mc_pattern = r'(?:MC|MCP):\s*\$?\s*([\d.]+)K\$?'
    match = re.search(mc_pattern, text)
    if match:
        value = match.group(1)
        return f"MC: ${value}K"
    return None

def has_pump_keywords(text):
    """Check if the message contains any pump-related keywords with case sensitivity for PUMP"""
    # Check for case-sensitive "PUMP" or "Pump"
    pump_match = any(pump_word in text for pump_word in ['PUMP', 'Pump'])
    # Check for case-insensitive "pumpfun" or "raydium"
    other_keywords = any(keyword in text.lower() for keyword in ['pumpfun', 'raydium'])
    return pump_match or other_keywords

async def is_valid_buy_message(text):
    """Check if the message is a valid buy message with pump keywords"""
    if not has_pump_keywords(text):
        return False
        
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

def extract_pump_type(text):
    """Extract pump type from the message with case sensitivity for PUMP"""
    # Check for pumpfun first (case insensitive)
    if 'pumpfun' in text.lower():
        return 'PUMPFUN'
    # Check for raydium (case insensitive)
    elif 'raydium' in text.lower():
        return 'RAYDIUM'
    # Check for PUMP or Pump (case sensitive)
    elif 'PUMP' in text or 'Pump' in text:
        return 'PUMPFUN'
    return None

async def scrap_message(chat, session, limit=50):
    """Scrape messages and track token purchases"""
    async for message in telethon_client.iter_messages(chat, limit=limit):
        if message.text:
            text = message.text

            if not has_pump_keywords(text):
                continue

            if await is_valid_buy_message(text):
                trader_pattern = r'(?:TRADER|Trader|trader)\d+'
                trader_match = re.search(trader_pattern, text)

                solana_addresses = re.findall(r'[0-9A-HJ-NP-Za-km-z]{32,44}', text)

                if trader_match and solana_addresses:
                    last_solana_address = solana_addresses[-1]
                    trader = trader_match.group()
                    
                    if last_solana_address != EXCLUDED_TOKEN:
                        pump_type = extract_pump_type(text)
                        market_cap = extract_market_cap(text)
                        
                        if last_solana_address not in session.multi_trader_tokens:
                            session.multi_trader_tokens[last_solana_address] = set()
                            session.token_market_caps[last_solana_address] = {}
                            if pump_type:
                                session.token_pump_types[last_solana_address] = pump_type
                        
                        session.multi_trader_tokens[last_solana_address].add(trader)
                        if market_cap:
                            session.token_market_caps[last_solana_address][trader] = market_cap

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
        session.round_start_time = time.time()
        
        async with telethon_client:
            for chat_link, limit in chat_limits.items():
                await scrap_message(chat_link, session, limit)

        current_messages = []
        for address, traders in session.multi_trader_tokens.items():
            if len(traders) >= 2:
                trader_list = sorted(list(traders))
                pump_type = session.token_pump_types.get(address, "Unknown")
                
                message = f"{len(trader_list)} traders bought {address}:\n\n"
                for trader in trader_list:
                    market_cap = session.token_market_caps.get(address, {}).get(trader, "")
                    mc_info = f" - {market_cap}" if market_cap else ""
                    message += f"{trader} - {pump_type}{mc_info}\n"
                current_messages.append(message)

        new_messages = [msg for msg in current_messages if msg not in session.previous_messages]

        round_duration = time.time() - session.round_start_time
        total_duration = time.time() - session.start_time
        
        timing_message = (
            f"\nRound Timing:\n"
            f"Round Duration: {round_duration:.2f} seconds\n"
            f"Total Running Time: {total_duration:.2f} seconds"
        )

        if new_messages:
            for message in new_messages:
                await context.bot.send_message(
                    chat_id=session.chat_id,
                    text=message + timing_message
                )
            session.previous_messages = current_messages.copy()
        else:
            await context.bot.send_message(
                chat_id=session.chat_id,
                text="No new multiple-trader tokens found" + timing_message
            )

        await asyncio.sleep(10)
        if session.is_monitoring:
            await context.bot.send_message(
                chat_id=session.chat_id,
                text=".....\n ROUND RESTARTED \n ....."
            )
        else:
            final_duration = time.time() - session.start_time
            await context.bot.send_message(
                chat_id=session.chat_id,
                text=f"Monitoring stopped. Total running time: {final_duration:.2f} seconds"
            )
            break

async def start(update, context):
    """Start the message monitoring process for a specific chat"""
    if not await check_authorization(update):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"You are not eligible to use the bot. Your username: {update.effective_user.username}"
        )
        return
    
    chat_id = update.effective_chat.id
    
    if chat_id not in context.bot_data:
        context.bot_data[chat_id] = MonitoringSession(chat_id)
    
    session = context.bot_data[chat_id]
    
    if not session.is_monitoring:
        session.is_monitoring = True
        session.start_time = time.time()
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
    if not await check_authorization(update):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"You are not eligible to use the bot. Your username: {update.effective_user.username}"
        )
        return
    
    chat_id = update.effective_chat.id
    
    if chat_id in context.bot_data:
        session = context.bot_data[chat_id]
        if session.is_monitoring:
            session.is_monitoring = False
            if session.monitoring_task:
                session.monitoring_task.cancel()
            final_duration = time.time() - session.start_time
            session.multi_trader_tokens.clear()
            session.previous_messages.clear()
            session.token_pump_types.clear()
            session.token_market_caps.clear()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Monitoring stopped for this chat.\nTotal running time: {final_duration:.2f} seconds"
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

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers here
    
    await app.bot.set_webhook(url='YOUR_RENDER_URL' + BOT_TOKEN)
    await app.start()
    await app.run_webhook(
        listen='0.0.0.0',
        port=PORT,
        webhook_url='YOUR_RENDER_URL' + BOT_TOKEN
    )

if __name__ == '__main__':
    asyncio.run(main())
