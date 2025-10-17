#!/usr/bin/env python3
"""Send immediate trading alerts to Discord"""
import asyncio
import aiohttp
from datetime import datetime
from src.config import Config

async def send_alerts():
    """Send sample trading alerts to different channels"""
    
    alerts = [
        {
            "webhook": Config.UNUSUAL_ACTIVITY_WEBHOOK,
            "title": "🚨 Unusual Volume Alert: NVDA",
            "description": "Massive volume spike detected",
            "color": 0xFF9800,
            "fields": [
                {"name": "Volume Ratio", "value": "3.5x average", "inline": True},
                {"name": "Current Volume", "value": "45.2M shares", "inline": True},
                {"name": "Price", "value": "$181.81", "inline": True},
                {"name": "Signal", "value": "BULLISH - Heavy accumulation", "inline": False}
            ]
        },
        {
            "webhook": Config.SWEEPS_WEBHOOK,
            "title": "🎯 Options Sweep: TSLA",
            "description": "Large bullish sweep detected",
            "color": 0x00FF00,
            "fields": [
                {"name": "Contract", "value": "CALL $220 11/15", "inline": True},
                {"name": "Premium", "value": "$85,000", "inline": True},
                {"name": "Volume", "value": "2,500 contracts", "inline": True},
                {"name": "Analysis", "value": "Aggressive near-the-money buying", "inline": False}
            ]
        },
        {
            "webhook": Config.GOLDEN_SWEEPS_WEBHOOK,
            "title": "💰 Golden Sweep: SPY",
            "description": "Million dollar options flow",
            "color": 0xFFD700,
            "fields": [
                {"name": "Contract", "value": "PUT $655 10/18", "inline": True},
                {"name": "Premium", "value": "$1.2M", "inline": True},
                {"name": "Volume", "value": "10,000 contracts", "inline": True},
                {"name": "Analysis", "value": "Hedge or directional bet on pullback", "inline": False}
            ]
        }
    ]
    
    async with aiohttp.ClientSession() as session:
        for alert in alerts:
            embed = {
                "title": alert["title"],
                "description": alert["description"],
                "color": alert["color"],
                "fields": alert["fields"],
                "footer": {"text": "ORAKL Bot | Not Financial Advice"},
                "timestamp": datetime.utcnow().isoformat()
            }
            
            payload = {
                "embeds": [embed],
                "username": "ORAKL Trading Bot"
            }
            
            try:
                async with session.post(alert["webhook"], json=payload) as response:
                    if response.status == 204:
                        print(f"✅ Alert sent: {alert['title']}")
                    else:
                        print(f"❌ Failed to send: {alert['title']} - Status: {response.status}")
            except Exception as e:
                print(f"❌ Error sending {alert['title']}: {e}")
            
            await asyncio.sleep(1)  # Small delay between alerts

if __name__ == "__main__":
    print("Sending trading alerts to Discord...")
    asyncio.run(send_alerts())
    print("\nDone! Check your Discord channels for the alerts.")