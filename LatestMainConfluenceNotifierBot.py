import os
import time
from datetime import datetime

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
PORT = int(os.getenv("PORT", 8080))# Render will provide the PORT environment variable

# Telegram bot configuration


# Telethon client configuration
BOT_TOKEN = "7327291802:AAFPM911VQH5uyTX2uPG8j503NCt3r62yMs"
API_ID = 21202746
API_HASH = "e700432294937e6925a83149ee7165a0"


# Create Telethon client
telethon_client = TelegramClient('test', API_ID, API_HASH)

# Excluded token address
EXCLUDED_TOKEN = 'So11111111111111111111111111111112'

# Authorized users allowed to command the bot in THETRACKOORS group
AUTHORIZED_USERS = {'orehub1378', 'Kemoo1975', 'jeremi1234', 'Busiiiiii'}
# The THETRACKOORS group identifier
THETRACKOORS_CHAT_ID = -1002297141126  # Replace with actual chat ID for THETRACKOORS

# Global variable to indicate if THETRACKOORS is being monitored
is_tracking_thetrackoors = False

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

async def check_authorization(update):
    """Check if the user is authorized to use the bot in the THETRACKOORS group"""
    user_username = update.effective_user.username

    # Check if the user is in AUTHORIZED_USERS and the chat is THETRACKOORS
    if update.effective_chat.id == THETRACKOORS_CHAT_ID:
        return user_username and user_username.lower() in {user.lower() for user in AUTHORIZED_USERS}
    
    return False  # Not authorized if not in THETRACKOORS group

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

async def monitor_channels(context, session):
    """Monitor channels for a specific chat session"""
    global is_tracking_thetrackoors

    chat_limits = {
        'https://t.me/ray_silver_bot': 150,
        'https://t.me/handi_cat_bot': 300,
        'https://t.me/Wallet_tracker_solana_spybot': 75,
        'https://t.me/Godeye_wallet_trackerBot': 150,

        'https://t.me/GMGN_alert_bot': 150,
        'https://t.me/Solbix_bot': 300
    }

    if is_tracking_thetrackoors:
        await scrap_message('https://t.me/THETRACKOORS', session)

    while session.is_monitoring:

        session.round_start_time = time.time()

        async with telethon_client:
            for chat_link, limit in chat_limits.items():
                if chat_link == 'https://t.me/THETRACKOORS':
                    if is_tracking_thetrackoors:  # Only allow this when the group is being monitored
                        await scrap_message(chat_link, session, limit)

                # Personal chats are not allowed if THETRACKOORS is active
                if not is_tracking_thetrackoors:
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
            pass
        else:
            final_duration = time.time() - session.start_time
            await context.bot.send_message(
                chat_id=session.chat_id,
                text=f"Monitoring stopped. Total running time: {final_duration:.2f} seconds"
            )
            break

async def start(update, context):
    """Start the message monitoring process for the THETRACKOORS group"""
    global is_tracking_thetrackoors
    chat_id = update.effective_chat.id

    # Check if user is authorized and the chat is THETRACKOORS
    if not await check_authorization(update):
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"You are not eligible to use the bot. Your username: {update.effective_user.username}"
        )
        return
    else:
        is_tracking_thetrackoors = True

    # Ensure Telethon client is connected
    if not telethon_client.is_connected():
        await telethon_client.connect()
        if not await telethon_client.is_user_authorized():
            await context.bot.send_message(
                chat_id=chat_id,
                text="Error: Telethon client is not authorized. Please check your configuration."
            )
            return

    # Start monitoring session for THETRACKOORS group
    if chat_id in context.bot_data:
        session = context.bot_data[chat_id]
        
        if not session.is_monitoring:
            session.is_monitoring = True
            session.start_time = time.time()
            try:
                # Create and start the monitoring task
                session.monitoring_task = asyncio.create_task(monitor_channels(context, session))
                # Add task error handling
                session.monitoring_task.add_done_callback(lambda t: handle_task_completion(t, context, chat_id))
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Monitoring now started for THETRACKOORS."
                )
            except Exception as e:
                session.is_monitoring = False
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Error starting monitoring: {str(e)}"
                )
    else:
        context.bot_data[chat_id] = MonitoringSession(chat_id)
        session = context.bot_data[chat_id]
        session.is_monitoring = True
        session.start_time = time.time()
        try:
            # Create and start the monitoring task
            session.monitoring_task = asyncio.create_task(monitor_channels(context, session))
            # Add task error handling
            session.monitoring_task.add_done_callback(lambda t: handle_task_completion(t, context, chat_id))
            await context.bot.send_message(
                chat_id=chat_id,
                text="Monitoring started for THETRACKOORS."
            )
        except Exception as e:
            session.is_monitoring = False
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Error starting monitoring: {str(e)}"
            )




async def stop(update, context):
    """Stop the message monitoring process for the THETRACKOORS group"""
    global is_tracking_thetrackoors
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
                text=f"Monitoring stopped for THETRACKOORS.\nTotal running time: {final_duration:.2f} seconds"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Monitoring is not active for THETRACKOORS."
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="No monitoring session found for THETRACKOORS."
        )

async def main():
    """Initialize the bot with webhook for Render deployment"""
    # Initialize and connect Telethon client first
    await telethon_client.start()
    
    logging.info("Telethon client started")
    
    # Initialize Application instance
    application = Application.builder().token(BOT_TOKEN).build()
    application.bot_data["application"] = application

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))

    # Set up webhook using a placeholder external URL (adjust as necessary)
    webhook_url = f"https://{os.getenv('RENDER_SERVICE_NAME')}.onrender.com/{BOT_TOKEN}"

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
        logging.info("webhookrun about to start")
        
        # Run the webhook server
        application.run_webhook(
            listen="0.0.0.0",  # Listen on all available interfaces
            port=PORT,  # Use the PORT provided by Render
            url_path=BOT_TOKEN,
            webhook_url=f"https://{os.getenv('RENDER_SERVICE_NAME')}.onrender.com/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise
    logging.info("webhook started")

if __name__ == "__main__":
    run_bot()
