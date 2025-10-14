"""Send a test signal to Discord webhook"""
import asyncio
import aiohttp
import json
from datetime import datetime
from src.config import Config

async def send_test():
    """Send test signal"""
    embed = {
        "title": "🧪 ORAKL BOT TEST SIGNAL",
        "description": "**If you see this, your bot is posting correctly!**",
        "color": 0x00FF00,
        "fields": [
            {"name": "Bot Version", "value": "v2.0 Enhanced", "inline": True},
            {"name": "Status", "value": "ONLINE 24/7", "inline": True},
            {"name": "Test Time", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": False},
            {"name": "Active Bots", "value": "7 specialized bots running", "inline": True},
            {"name": "Watchlist", "value": "12 symbols", "inline": True},
            {"name": "Message", "value": "This test confirms signals are posting to this channel", "inline": False}
        ],
        "footer": {"text": "ORAKL Bot v2.0 Enhanced - Test Signal"}
    }
    
    payload = {"embeds": [embed], "username": "ORAKL Bot Test"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(Config.DISCORD_WEBHOOK_URL, json=payload) as response:
            status = response.status
            print(f"Status Code: {status}")
            
            if status == 204:
                print("SUCCESS - Test signal sent to Discord!")
                print("\nCheck your Discord server in the channel where this webhook posts.")
                print(f"Webhook ID: {Config.DISCORD_WEBHOOK_URL.split('/')[-2]}")
                return True
            else:
                text = await response.text()
                print(f"FAILED - Response: {text}")
                return False

if __name__ == "__main__":
    print("Sending test signal to Discord...")
    print("=" * 60)
    result = asyncio.run(send_test())
    print("=" * 60)
    if result:
        print("\nGo check your Discord now! You should see a green test message.")
    else:
        print("\nWebhook test failed. Check your webhook URL in .env file.")

