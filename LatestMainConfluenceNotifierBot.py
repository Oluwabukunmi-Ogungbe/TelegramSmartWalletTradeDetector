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
import sys
from contextlib import suppress
from httpx import Timeout
import logging
import nest_asyncio
from keep_alive import keep_alive
nest_asyncio.apply()

keep_alive()

PORT = int(os.getenv("PORT", 8443))  # Render will provide the PORT environment variable
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  

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
        self.token_sol_amounts = {}
        self.token_timestamps = {}  # New: Track timestamps of trades
        self.start_time = None
        self.round_start_time = None

async def check_authorization(update):
    """Check if the user/group is authorized to use the bot"""
    chat_id = update.effective_chat.id
    user_username = update.effective_user.username
    chat_username = update.effective_chat.username
    
    if update.effective_chat.type == 'private':
        return user_username and user_username.lower() in {user.lower() for user in AUTHORIZED_USERS}
    
    return chat_username and chat_username.lower() in {group.lower() for group in AUTHORIZED_GROUPS}

def extract_market_cap(text):
    """Extract market cap value and unit from the message"""
    mc_pattern = r'(?:(?:MC|MCP):\s*\$?\s*([\d.]+)\s*([KkMm])?|\$?\s*([\d.]+)\s*([KkMm])?\s*(?=(?:MC|MCP)))'
    match = re.search(mc_pattern, text, re.IGNORECASE)
    
    if match:
        value = match.group(1) or match.group(3)
        unit = match.group(2) or match.group(4)
        
        try:
            value = float(value)
            # Standardize unit to uppercase
            if unit:
                unit = unit.upper()
            else:
                unit = 'K'  # Default to K if no unit specified
            return {'value': value, 'unit': unit}
        except ValueError:
            return None
    return None

def extract_sol_amount(text):
    """Extract the last number before 'SOL' in the text"""
    sol_pos = text.find('SOL')
    if sol_pos == -1:
        return None
        
    text_before_sol = text[:sol_pos]
    numbers = re.findall(r'[-+]?\d*\.\d+|\d+', text_before_sol)
    
    if numbers:
        try:
            return float(numbers[-1])
        except ValueError:
            return None
    return None

def has_pump_keywords(text):
    """Check if the message contains any pump-related keywords with case sensitivity for PUMP"""
    pump_match = any(pump_word in text for pump_word in ['PUMP', 'Pump'])
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
    if 'pumpfun' in text.lower():
        return 'PUMPFUN'
    elif 'raydium' in text.lower():
        return 'RAYDIUM'
    elif 'PUMP' in text or 'Pump' in text:
        return 'PUMPFUN'
    return None

def get_token_address(text, chat_link):
    """Extract token address based on the chat source"""
    solana_addresses = re.findall(r'[0-9A-HJ-NP-Za-km-z]{32,44}', text)
    if not solana_addresses:
        return None
        
    if 'Godeye_wallet_trackerBot' in chat_link:
        return solana_addresses[0]
    
    return solana_addresses[-1]

async def scrap_message(chat, session, limit=50):
    logging.info("scrape started")
    """Scrape messages and track token purchases"""
    async for message in telethon_client.iter_messages(chat, limit=limit):
        if message.text:
            text = message.text

            if not has_pump_keywords(text):
                continue

            if await is_valid_buy_message(text):
                trader_pattern = r'(?:TRADER|Trader|trader)\d+'
                trader_match = re.search(trader_pattern, text)

                token_address = get_token_address(text, chat)

                if trader_match and token_address:
                    trader = trader_match.group()
                    
                    if token_address != EXCLUDED_TOKEN:
                        pump_type = extract_pump_type(text)
                        market_cap = extract_market_cap(text)
                        sol_amount = extract_sol_amount(text)
                        timestamp = message.date.timestamp()
                        
                        if token_address not in session.multi_trader_tokens:
                            session.multi_trader_tokens[token_address] = set()
                            session.token_market_caps[token_address] = {}
                            session.token_sol_amounts[token_address] = {}
                            session.token_timestamps[token_address] = {}
                            if pump_type:
                                session.token_pump_types[token_address] = pump_type
                        
                        session.multi_trader_tokens[token_address].add(trader)
                        if market_cap is not None:
                            session.token_market_caps[token_address][trader] = market_cap
                        if sol_amount is not None:
                            session.token_sol_amounts[token_address][trader] = sol_amount
                        session.token_timestamps[token_address][trader] = timestamp
    logging.info("scrap ended")

async def monitor_channels(context, session):
    """Monitor channels for a specific chat session"""
    chat_limits = {
        'https://t.me/ray_silver_bot': 150,
        'https://t.me/handi_cat_bot': 300,
        'https://t.me/Wallet_tracker_solana_spybot': 75,
        'https://t.me/Godeye_wallet_trackerBot': 75,
        
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
                latest_trader = max(traders, key=lambda t: session.token_timestamps[address].get(t, 0))
                pump_type = session.token_pump_types.get(address, "Unknown")
                sol_amount = session.token_sol_amounts[address].get(latest_trader)
                market_cap = session.token_market_caps[address].get(latest_trader)
                
                message = (
                    f"{len(traders)} traders bought {address}:\n"
                    f"last trader bought"
                )
                
                if sol_amount is not None:
                    message += f" {sol_amount:.1f} SOL"
                
                message += f" on {pump_type}"
                
                if market_cap is not None:
                    message += f" at MC: ${market_cap['value']:.2f}{market_cap['unit']}"
                
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
                    text=message
                )
            session.previous_messages = current_messages.copy()
        else:
            await context.bot.send_message(
                chat_id=session.chat_id,
                text="No new multiple-trader tokens found" + timing_message
            )

        await asyncio.sleep(1)
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
            session.token_sol_amounts.clear()
            session.token_timestamps.clear()
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
    """Initialize the bot with webhook for Render deployment"""
    # Initialize Application instance
    application = Application.builder().token(BOT_TOKEN).build()
    application.bot_data["application"] = application

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))

    # Set up webhook using Render's external URL
    webhook_url = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"
    
    logging.info("Starting bot initialization...")
    try:
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"]
        )
        logging.info(f"Webhook set successfully to {webhook_url}")
        
        # Initialize the application
        await application.initialize()
        return application

    except Exception as e:
        logging.error(f"Error in webhook setup: {e}")
        raise

def run_bot():
    """Runner function for the bot"""
    # Configure logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    try:
        # Initialize the event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Initialize the application
        application = loop.run_until_complete(main())
        logging.info("webhookrun abt to start")
        
        # Run the webhook server
        application.run_webhook(
            listen="0.0.0.0",  # Listen on all available interfaces
            port=PORT,  # Use the PORT provided by Render
            url_path=BOT_TOKEN,
            webhook_url=f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )

    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    run_bot()
