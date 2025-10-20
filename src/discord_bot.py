"""ORAKL Discord Bot with Query Commands"""
import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO
import logging
from typing import Optional, Dict
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.flow_scanner import ORAKLFlowScanner
from src.config import Config

logger = logging.getLogger(__name__)

class ORAKLBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=Config.DISCORD_COMMAND_PREFIX, 
            intents=intents,
            description="ORAKL Options Flow Analysis Bot",
            help_command=None  # Disable default help command
        )
        
        self.fetcher = DataFetcher(Config.POLYGON_API_KEY)
        self.analyzer = OptionsAnalyzer()
        self.scanner = ORAKLFlowScanner(self.fetcher, self.analyzer)
        self.start_time = datetime.now()
        
        # Register commands
        from src.query_bot import setup_bot_commands
        setup_bot_commands(self)
        
    async def on_ready(self):
        logger.info(f'ORAKL Bot connected as {self.user}')
        logger.info(f'Serving {len(self.guilds)} servers')

        # Set status
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Options Flow | ok-commands"
            )
        )

        # Auto-scanning disabled - using dedicated webhook bots instead
        # self.auto_scan.start()
        self.status_update.start()
    
    @tasks.loop(minutes=Config.SCAN_INTERVAL_MINUTES)
    async def auto_scan(self):
        """Automatic ORAKL Flow scanning"""
        try:
            channel = self.get_channel(Config.ALERT_CHANNEL_ID)
            if not channel:
                logger.warning("Alert channel not found")
                return
            
            logger.info("Running ORAKL Flow scan...")
            signals = await self.scanner.scan_all()
            
            if signals:
                # Send summary embed
                summary_embed = self.create_summary_embed(signals)
                await channel.send(embed=summary_embed)
                
                # Send individual signals (top 5)
                for signal in signals[:5]:
                    embed = self.create_flow_embed(signal)
                    await channel.send(embed=embed)
                    await asyncio.sleep(1)
            else:
                logger.info("No signals found in this scan")
                
        except Exception as e:
            logger.error(f"Auto-scan error: {e}")
    
    @tasks.loop(hours=1)
    async def status_update(self):
        """Update bot status with stats"""
        uptime = datetime.now() - self.start_time
        hours = int(uptime.total_seconds() // 3600)
        
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"Flow | {hours}h uptime | ok-commands"
            )
        )
    
    def create_summary_embed(self, signals: list) -> discord.Embed:
        """Create summary embed for multiple signals"""
        embed = discord.Embed(
            title="🔮 ORAKL Flow Summary",
            description=f"Found {len(signals)} high-probability signals",
            color=0x9B59B6,
            timestamp=datetime.now()
        )
        
        # Group by sentiment
        bullish = [s for s in signals if s['type'] == 'CALL']
        bearish = [s for s in signals if s['type'] == 'PUT']
        
        if bullish:
            value = "\n".join([
                f"**{s['ticker']}** ${s['strike']} - {s['probability_itm']}%"
                for s in bullish[:3]
            ])
            embed.add_field(name="🟢 Bullish Signals", value=value, inline=True)
        
        if bearish:
            value = "\n".join([
                f"**{s['ticker']}** ${s['strike']} - {s['probability_itm']}%"
                for s in bearish[:3]
            ])
            embed.add_field(name="🔴 Bearish Signals", value=value, inline=True)
        
        embed.set_footer(text="ORAKL Options Flow Bot")
        return embed
    
    def create_flow_embed(self, signal: Dict) -> discord.Embed:
        """Create embed for individual flow signal"""
        color = 0x00FF00 if signal['type'] == 'CALL' else 0xFF0000
        
        embed = discord.Embed(
            title=f"🎯 ORAKL Signal: {signal['ticker']}",
            description=f"{signal['signal_strength']} Signal Detected",
            color=color,
            timestamp=datetime.now()
        )
        
        # Main info
        embed.add_field(
            name="📊 Contract",
            value=f"{signal['type']} ${signal['strike']}\nExp: {signal['expiration']}",
            inline=True
        )
        embed.add_field(
            name="🎲 Probability ITM",
            value=f"**{signal['probability_itm']}%**",
            inline=True
        )
        embed.add_field(
            name="💰 Premium Flow",
            value=f"${signal['total_premium']:,.0f}",
            inline=True
        )
        
        # Additional metrics
        embed.add_field(
            name="📈 Current Price",
            value=f"${signal['current_price']:.2f}",
            inline=True
        )
        embed.add_field(
            name="📊 Volume/OI",
            value=f"{signal['volume']:,}/{signal.get('open_interest', 0):,}",
            inline=True
        )
        embed.add_field(
            name="🔄 Repeat Signals",
            value=f"{signal['repeat_count']} detected",
            inline=True
        )
        
        # Add target info
        if signal['type'] == 'CALL':
            target = signal['strike']
            embed.add_field(
                name="🎯 Target",
                value=f"Break above ${target:.2f}",
                inline=False
            )
        else:
            target = signal['strike']
            embed.add_field(
                name="🎯 Target",
                value=f"Break below ${target:.2f}",
                inline=False
            )
        
        embed.set_footer(text="ORAKL Options Flow Bot | Not Financial Advice")
        return embed
    
