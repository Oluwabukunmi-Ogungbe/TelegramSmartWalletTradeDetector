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
from threading import Thread
from flask import Flask

# Initialize Flask app for keep_alive
app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True  # Set as daemon thread
    t.start()

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Initialize keep_alive
keep_alive()

# Configuration
PORT = int(os.getenv("PORT", 10000))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

# Load environment variables
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

# Telegram configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# Initialize Telethon client
telethon_client = TelegramClient('test', API_ID, API_HASH)

# Constants
EXCLUDED_TOKEN = 'So11111111111111111111111111111112'
AUTHORIZED_USERS = {'orehub1378', 'busiiiiii', 'jeremi1234'}
AUTHORIZED_GROUPS = {'THETRACKOORS'}

# Chat configuration
CHAT_LIMITS = {
    'https://t.me/ray_silver_bot': 150,
    'https://t.me/handi_cat_bot': 300,
    'https://t.me/Wallet_tracker_solana_spybot': 75,
    'https://t.me/Godeye_wallet_trackerBot': 75,
    'https://t.me/GMGN_alert_bot': 150,
    'https://t.me/Solbix_bot': 300
}

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
        self.token_timestamps = {}
        self.start_time = None
        self.round_start_time = None
        self.error_count = 0
        self.last_error_time = None

    async def reset(self):
        self.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
        self.multi_trader_tokens.clear()
        self.previous_messages.clear()
        self.token_pump_types.clear()
        self.token_market_caps.clear()
        self.token_sol_amounts.clear()
        self.token_timestamps.clear()
        self.error_count = 0
        self.last_error_time = None

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
            unit = unit.upper() if unit else 'K'
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
    """Check if the message contains pump-related keywords"""
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
    """Extract pump type from the message"""
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
    """Scrape messages and track token purchases with error handling"""
    try:
        async for message in telethon_client.iter_messages(chat, limit=limit):
            try:
                if not message.text:
                    continue

                text = message.text

                if not has_pump_keywords(text):
                    continue

                if await is_valid_buy_message(text):
                    trader_pattern = r'(?:TRADER|Trader|trader)\d+'
                    trader_match = re.search(trader_pattern, text)

                    token_address = get_token_address(text, chat)

                    if trader_match and token_address and token_address != EXCLUDED_TOKEN:
                        trader = trader_match.group()
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

            except Exception as e:
                logging.error(f"Error processing message in {chat}: {e}")
                continue

    except Exception as e:
        logging.error(f"Error scraping messages from {chat}: {e}")
        raise

async def monitor_channels(context, session):
    """Monitor channels with enhanced error handling and monitoring"""
    try:
        while session.is_monitoring:
            try:
                session.round_start_time = time.time()
                
                async with telethon_client:
                    for chat_link, limit in CHAT_LIMITS.items():
                        try:
                            await scrap_message(chat_link, session, limit)
                        except Exception as e:
                            logging.error(f"Error scraping {chat_link}: {e}")
                            session.error_count += 1
                            session.last_error_time = time.time()
                            continue

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
                
                status_message = (
                    f"\nMonitoring Status:\n"
                    f"Round Duration: {round_duration:.2f} seconds\n"
                    f"Total Running Time: {total_duration:.2f} seconds\n"
                    f"Error Count: {session.error_count}"
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
                        text="No new multiple-trader tokens found" + status_message
                    )

                # Add delay between rounds
                await asyncio.sleep(1)
                
                if session.is_monitoring:
                    await context.bot.send_message(
                        chat_id=session.chat_id,
                        text=".....\n ROUND RESTARTED \n ....."
                    )
                
            except Exception as e:
                logging.error(f"Error in monitoring loop: {e}")
                session.error_count += 1
                session.last_error_time = time.time()
                await asyncio.sleep(5)  # Wait before retrying

    except Exception as e:
        logging.error(f"Fatal error in monitor_channels: {e}")
        session.is_monitoring = False
        if session.chat_id:
            await context.bot.send_message(
                chat_id=session.chat_id,
                text=f"Monitoring stopped due to error: {str(e)}"
            )

async def start(update, context):
    """Start the message monitoring process"""
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
        await session.reset()  # Reset session state
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
    """Stop the message monitoring process"""
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
            await session.reset()
            final_duration = time.time() - session.start_time
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
    async def main():
        application = Application.builder().token(BOT_TOKEN).build()
        application.bot_data["application"] = application

    # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stop", stop))

    # Only set webhook if RENDER_EXTERNAL_URL is provided
        if RENDER_EXTERNAL_URL:
            webhook_url = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"
            await application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True
        )
            logging.info(f"Webhook set successfully to {webhook_url}")
    
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
