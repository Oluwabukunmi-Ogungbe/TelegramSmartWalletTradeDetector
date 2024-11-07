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

# Dictionary to store the Solana token address and associated traders
solana_trader_map = defaultdict(set)

# Flag to control the monitoring process
is_monitoring = False

async def scrap_message(chat, limit=50):
    """Scrape messages and track token purchases"""
    async for message in telethon_client.iter_messages(chat, limit=limit):
        if message.text:
            text = message.text

            # Case-insensitive pattern for buy and trader
            buy_pattern = r'(?:BUY|Buy|buy)'
            trader_pattern = r'(?:TRADER|Trader|trader)\d+'

            # Check if either buy or trader exists in any case
            if re.search(buy_pattern, text) and re.search(trader_pattern, text):
                # Find only the first trader name
                trader_match = re.search(trader_pattern, text)

                # Find the last Solana address in the message
                solana_addresses = re.findall(r'[0-9A-HJ-NP-Za-km-z]{32,44}', text)

                if trader_match and solana_addresses:
                    # Get only the last Solana address from the message
                    last_solana_address = solana_addresses[-1]

                    # Adding only the first trader to the Solana address entry in the map
                    first_trader = trader_match.group()
                    solana_trader_map[last_solana_address].add(first_trader)

async def start(update, context):
    """Start the message monitoring process"""
    global is_monitoring

    chat_limits = {
        'https://t.me/ray_silver_bot': 150,
        'https://t.me/handi_cat_bot': 300,
        'https://t.me/Wallet_tracker_solana_spybot': 75,
        'https://t.me/CashCash_alert_bot': 75,
        'https://t.me/GMGN_alert_bot': 150,
        'https://t.me/Solbix_bot': 30
    }

    previous_messages = []  # Store previous round's messages

    async def monitor_channels():
        nonlocal previous_messages
        while is_monitoring:
            async with telethon_client:
                for chat_link, limit in chat_limits.items():
                    await scrap_message(chat_link, limit)

            # Prepare the current round's message summary
            current_messages = []
            for address, traders in solana_trader_map.items():
                if len(traders) > 1:
                    current_messages.append(f"{len(traders)} traders bought {address}")

            # Check for new addresses
            new_addresses = [msg for msg in current_messages if msg not in previous_messages]

            if not new_addresses:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="SAME TRADERS")
            else:
                # Send each new message and update previous_messages
                for message in new_addresses:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=message)
                previous_messages = current_messages.copy()

            # Notify end of monitoring round, wait, and restart
            await asyncio.sleep(10)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=".....\n ROUND RESTARTED \n .......")

    # Start the monitoring process
    is_monitoring = True
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Monitoring started.")
    asyncio.create_task(monitor_channels())

async def stop(update, context):
    """Stop the message monitoring process"""
    global is_monitoring
    is_monitoring = False
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Monitoring stopped.")

def main():
    """Start the bot"""
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    main()