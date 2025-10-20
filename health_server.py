"""
Simple health check server to keep Render happy
Runs alongside the main bot
"""

from aiohttp import web
import asyncio
import logging

logger = logging.getLogger(__name__)

async def health_check(request):
    """Simple health endpoint"""
    return web.Response(text="OK", status=200)

async def start_health_server(port=10000):
    """Start a simple health check server"""
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"Health check server running on port {port}")
    
    # Keep running forever
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(start_health_server())
