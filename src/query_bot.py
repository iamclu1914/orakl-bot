"""ORAKL Discord Bot Commands - Simplified Registration"""
import discord
from discord.ext import commands
from datetime import datetime
import asyncio
import logging
import pandas as pd

logger = logging.getLogger(__name__)

def setup_bot_commands(bot):
    """Setup all ORAKL bot commands"""
    
    @bot.command(name='help', aliases=['commands'])
    async def help_cmd(ctx):
        """Show all ORAKL commands"""
        embed = discord.Embed(
            title="🔮 ORAKL Bot - Professional Visualizations",
            description="Tradytics-quality charts powered by Polygon API",
            color=0x9B59B6
        )

        embed.add_field(
            name="📊 Flow Analysis (Visual)",
            value="`ok-topflow` - Top bull/bear bar chart 📊\n"
                  "`ok-bigflow SYMBOL` - Biggest trades table 💰\n"
                  "`ok-flowsum SYMBOL` - Complete dashboard 📈\n"
                  "`ok-flowheatmap SYMBOL` - Strike x Exp heatmap 🔥",
            inline=False
        )

        embed.add_field(
            name="📈 Technical Analysis (Visual)",
            value="`ok-srlevels SYMBOL [1h|4h|1d]` - S/R levels with timeframe 📊\n"
                  "`ok-darkpool SYMBOL` - Last week's darkpool/block trades 🌑\n"
                  "`ok-dplevels SYMBOL` - Last week's darkpool premium levels 💰",
            inline=False
        )

        embed.add_field(
            name="🤖 AI & Scans",
            value="`ok-all SYMBOL` - AI prediction 🔮\n"
                  "`ok-scan` - Force manual scan 🔍",
            inline=False
        )

        embed.set_footer(text="ORAKL Bot v3.0 Enhanced | 1-Week Darkpool Data | Timeframe Selection")
        await ctx.send(embed=embed)
    
    @bot.command(name='all', aliases=['ai', 'predict'])
    async def ai_predictions(ctx, symbol: str):
        """AI predictions for stock movement"""
        symbol = symbol.upper()
        
        async with ctx.typing():
            trades = await bot.fetcher.get_options_trades(symbol)
            analysis = bot.analyzer.analyze_flow(trades)
            sentiment = bot.analyzer.calculate_flow_sentiment(symbol, trades)
        
        embed = discord.Embed(
            title=f"🔮 ORAKL AI Analysis: {symbol}",
            color=0x9B59B6
        )
        
        prediction = "📈 BULLISH" if sentiment['score'] > 10 else "📉 BEARISH" if sentiment['score'] < -10 else "↔️ NEUTRAL"
        
        embed.add_field(name="Prediction", value=f"**{prediction}**", inline=True)
        embed.add_field(name="Confidence", value=f"{abs(sentiment['score'])}%", inline=True)
        embed.add_field(name="Sentiment", value=sentiment['sentiment'], inline=True)
        
        embed.add_field(
            name="Analysis",
            value=f"Call Flow: ${sentiment['call_premium']:,.0f}\n"
                  f"Put Flow: ${sentiment['put_premium']:,.0f}\n"
                  f"Signal: {analysis.get('dominant_side', 'NEUTRAL')}",
            inline=False
        )
        
        embed.set_footer(text="ORAKL AI | Not Financial Advice")
        await ctx.send(embed=embed)
    
    @bot.command(name='topflow', aliases=['top'])
    async def top_flow(ctx):
        """Most bullish and bearish stocks with professional chart"""
        async with ctx.typing():
            from src.config import Config
            from src.utils.flow_charts import FlowChartGenerator
            
            results = []
            
            for ticker in Config.WATCHLIST[:30]:
                try:
                    trades = await bot.fetcher.get_options_trades(ticker)
                    if not trades.empty:
                        sentiment = bot.analyzer.calculate_flow_sentiment(ticker, trades)
                        results.append({
                            'ticker': ticker,
                            'sentiment': sentiment['sentiment'],
                            'score': sentiment['score']
                        })
                except:
                    continue
        
        if not results:
            await ctx.send("No flow data available currently")
            return
        
        # Create professional chart (fast, non-blocking)
        from src.utils.flow_charts import FlowChartGenerator
        chart_buffer = FlowChartGenerator.create_topflow_chart(results)
        
        if chart_buffer:
            file = discord.File(chart_buffer, filename='topflow.png')
            embed = discord.Embed(
                title="🔥 ORAKL Top Options Flow",
                description="Real-time bullish and bearish sentiment analysis",
                color=0x9B59B6,
                timestamp=datetime.now()
            )
            embed.set_image(url="attachment://topflow.png")
            embed.set_footer(text="ORAKL Flow Bot | Green = Bullish | Red = Bearish")
            await ctx.send(file=file, embed=embed)
        else:
            await ctx.send("Error generating flow chart")
    
    @bot.command(name='bigflow', aliases=['big'])
    async def big_flow(ctx, symbol: str):
        """Biggest options trades with professional table"""
        symbol = symbol.upper()
        
        async with ctx.typing():
            from src.utils.flow_charts import FlowChartGenerator
            
            trades = await bot.fetcher.get_options_trades(symbol)
        
        if trades.empty:
            await ctx.send(f"No trades found for {symbol}")
            return
        
        # Create professional table (fast, non-blocking)
        from src.utils.flow_charts import FlowChartGenerator
        table_buffer = FlowChartGenerator.create_bigflow_table(trades, symbol)
        
        if table_buffer:
            file = discord.File(table_buffer, filename='bigflow.png')
            embed = discord.Embed(
                title=f"💰 {symbol} Biggest Flow",
                description="Largest options trades today",
                color=0x9B59B6,
                timestamp=datetime.now()
            )
            embed.set_image(url="attachment://bigflow.png")
            embed.set_footer(text="ORAKL Flow Bot | Real-time data")
            await ctx.send(file=file, embed=embed)
        else:
            # Fallback to simple text
            top_trades = trades.nlargest(10, 'premium')
            embed = discord.Embed(title=f"💰 {symbol} Big Flow", color=0x9B59B6)
            for i, (_, trade) in enumerate(top_trades.head(6).iterrows(), 1):
                embed.add_field(
                    name=f"#{i} → ${trade['premium']:,.0f}",
                    value=f"{trade['type']} ${trade['strike']:.0f}",
                    inline=True
                )
            await ctx.send(embed=embed)
    
    @bot.command(name='scan')
    async def force_scan(ctx):
        """Force immediate scan"""
        await ctx.send("🔍 Starting ORAKL scan...")
        
        async with ctx.typing():
            signals = await bot.scanner.scan_all()
        
        if signals:
            summary_embed = bot.create_summary_embed(signals)
            await ctx.send(embed=summary_embed)
            
            for signal in signals[:3]:
                embed = bot.create_flow_embed(signal)
                await ctx.send(embed=embed)
                await asyncio.sleep(1)
        else:
            await ctx.send("No signals found in current scan")
    
    @bot.command(name='flowsum', aliases=['summary'])
    async def flow_summary(ctx, symbol: str):
        """Complete flow summary with professional dashboard"""
        symbol = symbol.upper()
        
        async with ctx.typing():
            from src.utils.flow_charts import FlowChartGenerator
            
            summary = await bot.scanner.get_flow_summary(symbol)
        
        if not summary:
            await ctx.send(f"Could not get flow summary for {symbol}")
            return
        
        # Create professional dashboard (fast, non-blocking)
        from src.utils.flow_charts import FlowChartGenerator
        dashboard_buffer = FlowChartGenerator.create_flowsum_dashboard(summary, symbol)
        
        if dashboard_buffer:
            file = discord.File(dashboard_buffer, filename='flowsum.png')
            embed = discord.Embed(
                title=f"📊 {symbol} Flow Summary",
                description=f"Current Price: ${summary.get('current_price', 0):.2f}",
                color=0x9B59B6,
                timestamp=datetime.now()
            )
            embed.set_image(url="attachment://flowsum.png")
            embed.set_footer(text="ORAKL Flow Bot | Comprehensive Analysis")
            await ctx.send(file=file, embed=embed)
        else:
            # Fallback to text
            embed = discord.Embed(
                title=f"📊 ORAKL Flow Summary: {symbol}",
                description=f"Current Price: ${summary.get('current_price', 0):.2f}",
                color=0x9B59B6,
                timestamp=datetime.now()
            )
            
            flow = summary.get('flow_analysis', {})
            embed.add_field(
                name="📈 Flow Analysis",
                value=f"Total Premium: ${flow.get('total_premium', 0):,.0f}\n"
                      f"Dominant Side: {flow.get('dominant_side', 'N/A')}\n"
                      f"Signal Strength: {flow.get('signal_strength', 'N/A')}",
                inline=True
            )
            
            embed.set_footer(text="ORAKL Options Flow Bot")
            await ctx.send(embed=embed)
    
    @bot.command(name='flowheatmap', aliases=['heatmap'])
    async def flow_heatmap(ctx, symbol: str):
        """Options flow heatmap by strike and expiration"""
        symbol = symbol.upper()
        
        async with ctx.typing():
            from src.utils.flow_charts import FlowChartGenerator
            
            trades = await bot.fetcher.get_options_trades(symbol)
            current_price = await bot.fetcher.get_stock_price(symbol)
        
        if trades.empty:
            await ctx.send(f"No options flow data for {symbol}")
            return
        
        # Create professional heatmap (fast, non-blocking)
        from src.utils.flow_charts import FlowChartGenerator
        chart_buffer = FlowChartGenerator.create_flow_heatmap(trades, symbol)
        
        if chart_buffer:
            file = discord.File(chart_buffer, filename='heatmap.png')
            embed = discord.Embed(
                title=f"🔥 {symbol} Flow Heatmap",
                description=f"Net Premium by Strike & Expiration | Price: ${current_price:.2f}",
                color=0x9B59B6,
                timestamp=datetime.now()
            )
            embed.set_image(url="attachment://heatmap.png")
            embed.set_footer(text="ORAKL Bot | Strike x Expiration Matrix | Green = Call Heavy | Red = Put Heavy")
            await ctx.send(file=file, embed=embed)
        else:
            await ctx.send("Error generating heatmap")
    
    @bot.command(name='darkpool', aliases=['dp'])
    async def darkpool_trades(ctx, symbol: str):
        """Last week's darkpool and block trades with visual table"""
        symbol = symbol.upper()

        async with ctx.typing():
            from src.utils.flow_charts import FlowChartGenerator
            from datetime import timedelta

            # Get 1 week of stock trades for darkpool analysis
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)

            trades_list = await bot.fetcher.get_stock_trades_range(
                symbol,
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            )
            current_price = await bot.fetcher.get_stock_price(symbol)

            if not trades_list:
                await ctx.send(f"No darkpool data for {symbol} in the last week")
                return

            # Convert to DataFrame
            trades_df = pd.DataFrame(trades_list)

        # Create professional darkpool table
        from src.utils.flow_charts import FlowChartGenerator
        chart_buffer = FlowChartGenerator.create_darkpool_table(
            trades_df, symbol, current_price
        )

        if chart_buffer:
            file = discord.File(chart_buffer, filename='darkpool.png')
            embed = discord.Embed(
                title=f"🌑 {symbol} Darkpool & Block Trades",
                description=f"Recent large trades | Current: ${current_price:.2f}",
                color=0x9B30FF,
                timestamp=datetime.now()
            )
            embed.set_image(url="attachment://darkpool.png")
            embed.set_footer(text="ORAKL Bot | Darkpool & Block Trades")
            await ctx.send(file=file, embed=embed)
        else:
            await ctx.send("No significant darkpool trades found")

    @bot.command(name='dplevels')
    async def darkpool_levels(ctx, symbol: str):
        """Last week's darkpool premium by price level (horizontal bar chart)"""
        symbol = symbol.upper()

        async with ctx.typing():
            from src.utils.flow_charts import FlowChartGenerator
            from datetime import timedelta

            # Get 1 week of stock trades for darkpool analysis
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)

            trades_list = await bot.fetcher.get_stock_trades_range(
                symbol,
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            )
            current_price = await bot.fetcher.get_stock_price(symbol)

            if not trades_list:
                await ctx.send(f"No darkpool data for {symbol} in the last week")
                return

            # Convert to DataFrame
            trades_df = pd.DataFrame(trades_list)

        # Create professional chart showing PREMIUM by price level
        from src.utils.flow_charts import FlowChartGenerator
        chart_buffer = FlowChartGenerator.create_darkpool_premium_levels(
            trades_df, symbol, current_price
        )

        if chart_buffer:
            file = discord.File(chart_buffer, filename='dplevels.png')
            embed = discord.Embed(
                title=f"🌑 {symbol} Darkpool Premium Levels",
                description=f"Premium accumulation by price | Current: ${current_price:.2f}",
                color=0x9B30FF,
                timestamp=datetime.now()
            )
            embed.set_image(url="attachment://dplevels.png")
            embed.set_footer(text="ORAKL Bot | Darkpool Premium by Price Level")
            await ctx.send(file=file, embed=embed)
        else:
            await ctx.send("No significant darkpool levels found")
    
    @bot.command(name='srlevels', aliases=['sr', 'levels'])
    async def sr_levels(ctx, symbol: str, timeframe: str = 'all'):
        """Support and Resistance levels - specify timeframe: 1h, 4h, 1d, or all"""
        symbol = symbol.upper()
        timeframe = timeframe.lower()

        # Validate timeframe
        valid_timeframes = ['1h', '4h', '1d', 'all']
        if timeframe not in valid_timeframes:
            await ctx.send(f"Invalid timeframe. Use: `1h`, `4h`, `1d`, or `all`\nExample: `/srlevels TSLA 4h`")
            return

        async with ctx.typing():
            from src.utils.flow_charts import FlowChartGenerator
            from datetime import timedelta

            # Get current price
            current_price = await bot.fetcher.get_stock_price(symbol)
            if not current_price:
                await ctx.send(f"Could not get price for {symbol}")
                return

            end_date = datetime.now()

            # Fetch data based on timeframe selection
            data_1h = pd.DataFrame()
            data_4h = pd.DataFrame()
            data_daily = pd.DataFrame()

            if timeframe in ['1h', 'all']:
                start_1h = end_date - timedelta(days=7)
                data_1h = await bot.fetcher.get_aggregates(
                    symbol,
                    timespan='hour',
                    multiplier=1,
                    from_date=start_1h.strftime('%Y-%m-%d'),
                    to_date=end_date.strftime('%Y-%m-%d')
                )

            if timeframe in ['4h', 'all']:
                start_4h = end_date - timedelta(days=30)
                data_4h = await bot.fetcher.get_aggregates(
                    symbol,
                    timespan='hour',
                    multiplier=4,
                    from_date=start_4h.strftime('%Y-%m-%d'),
                    to_date=end_date.strftime('%Y-%m-%d')
                )

            if timeframe in ['1d', 'all']:
                start_daily = end_date - timedelta(days=90)
                data_daily = await bot.fetcher.get_aggregates(
                    symbol,
                    timespan='day',
                    multiplier=1,
                    from_date=start_daily.strftime('%Y-%m-%d'),
                    to_date=end_date.strftime('%Y-%m-%d')
                )

            if data_1h.empty and data_4h.empty and data_daily.empty:
                await ctx.send(f"No price data available for {symbol}")
                return

        # Create chart based on timeframe
        from src.utils.flow_charts import FlowChartGenerator

        if timeframe == 'all':
            chart_buffer = FlowChartGenerator.create_sr_levels_tradingview(
                symbol, data_1h, data_4h, data_daily, current_price
            )
            tf_text = "1H · 4H · Daily"
        else:
            # Single timeframe chart
            if timeframe == '1h':
                chart_buffer = FlowChartGenerator.create_sr_levels_chart(symbol, data_1h, current_price)
                tf_text = "1 Hour"
            elif timeframe == '4h':
                chart_buffer = FlowChartGenerator.create_sr_levels_chart(symbol, data_4h, current_price)
                tf_text = "4 Hour"
            else:  # 1d
                chart_buffer = FlowChartGenerator.create_sr_levels_chart(symbol, data_daily, current_price)
                tf_text = "Daily"

        if chart_buffer:
            file = discord.File(chart_buffer, filename='srlevels.png')

            embed = discord.Embed(
                title=f"📊 {symbol} Support & Resistance Levels",
                description=f"Timeframe: **{tf_text}** | Current: ${current_price:.2f}",
                color=0x5865f2,
                timestamp=datetime.now()
            )

            embed.set_image(url="attachment://srlevels.png")
            embed.set_footer(text=f"ORAKL Bot | {tf_text} | Green = Support | Red = Resistance")

            await ctx.send(file=file, embed=embed)
        else:
            await ctx.send(f"Error generating S/R chart for {symbol}")
