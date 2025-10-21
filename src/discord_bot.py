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
import re

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
        
        # Auto-formatting enabled for TradingView STRAT alerts
        
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
        
        # Start status update task
        self.status_update.start()

    async def on_message(self, message):
        """Auto-format TradingView STRAT alerts"""
        # Don't process bot messages
        if message.author.bot:
            return
            
        try:
            # Only process messages in STRAT channel (from webhook ID)
            strat_channel_id = int(Config.STRAT_WEBHOOK.split('/')[-2])
            if message.channel.id != strat_channel_id:
                return
                
            # Check if message matches TradingView STRAT alert pattern
            if self._is_strat_alert(message.content):
                try:
                    # Parse and format the alert
                    formatted_embed = await self._format_strat_alert(message.content)
                    
                    if formatted_embed:
                        # Delete original message and post formatted version
                        await message.delete()
                        await message.channel.send(embed=formatted_embed)
                        logger.info(f"Auto-formatted TradingView STRAT alert")
                        
                except Exception as e:
                    logger.error(f"Error auto-formatting STRAT alert: {e}")
        except Exception as e:
            logger.error(f"Error in on_message handler: {e}")
        
        # Process other commands
        await self.process_commands(message)
    
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
    
    def _is_strat_alert(self, message_content: str) -> bool:
        """Check if message is a TradingView STRAT alert"""
        # Look for the specific pattern in TradingView alerts
        pattern = r"[\w-]+ detected for \w+\."
        return bool(re.search(pattern, message_content))
    
    async def _format_strat_alert(self, message_content: str) -> Optional[discord.Embed]:
        """Parse TradingView alert and create formatted STRAT embed"""
        try:
            # Regex to extract all components
            pattern = re.compile(
                r"(?P<pattern>[\w-]+) detected for (?P<ticker>\w+)\.\s+"
                r"50% Trigger: (?P<trigger>[\d.]+)\s+"
                r"If we open above (?P<price1>[\d.]+) First PT is (?P<target1>[\d.]+), "
                r"If we open below (?P<price2>[\d.]+) First PT is (?P<target2>[\d.]+)"
            )
            
            match = pattern.search(message_content)
            if not match:
                return None
                
            data = match.groupdict()
            
            # Parse the trigger logic
            trigger_price = float(data['trigger'])
            price1 = float(data['price1'])  # "above" price
            price2 = float(data['price2'])  # "below" price
            
            # The logic: above trigger = bullish target, below trigger = bearish target  
            bullish_target = data['target1']  # Target when opening above trigger
            bearish_target = data['target2']  # Target when opening below trigger
            
            # Create professional STRAT embed
            embed = discord.Embed(
                title=f"♟️ STRAT Alert: {data['ticker']}",
                color=0xFFD700,  # Gold color
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="📊 Pattern", 
                value=data['pattern'], 
                inline=True
            )
            embed.add_field(
                name="🎯 50% Trigger", 
                value=f"${data['trigger']}", 
                inline=True
            )
            embed.add_field(
                name="⏰ Timeframe", 
                value="12HR", 
                inline=True
            )
            
            embed.add_field(
                name="🟢 Bullish Scenario", 
                value=f"**Open above ${data['trigger']}**\nFirst PT: **${bullish_target}**", 
                inline=True
            )
            embed.add_field(
                name="🔴 Bearish Scenario", 
                value=f"**Open below ${data['trigger']}**\nFirst PT: **${bearish_target}**", 
                inline=True
            )
            embed.add_field(
                name="📈 Status", 
                value="Alert Active", 
                inline=True
            )
            
            # No footer as requested
            
            return embed
            
        except Exception as e:
            logger.error(f"Error parsing STRAT alert: {e}")
            return None
    
