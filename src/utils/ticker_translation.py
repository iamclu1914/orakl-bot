"""
Ticker Translation Utility
Handles common ticker confusions and legacy names
"""

# Common ticker translations
TICKER_TRANSLATIONS = {
    'BLOCK': 'SQ',      # Block Inc. (formerly Square) 
    'FB': 'META',       # Meta (formerly Facebook)
    'DIDI': 'DIDIY',    # DiDi after delisting
    'BRKB': 'BRK-B',    # Berkshire Hathaway B
    'BRKA': 'BRK-A',    # Berkshire Hathaway A
    'BRK.B': 'BRK-B',   # Alternative format
    'BRK.A': 'BRK-A',   # Alternative format
}

def translate_ticker(ticker: str) -> str:
    """
    Translate common ticker confusions to correct Polygon format
    
    Args:
        ticker: The ticker symbol to translate
        
    Returns:
        The translated ticker or original if no translation needed
    """
    ticker = ticker.upper().strip()
    return TICKER_TRANSLATIONS.get(ticker, ticker)
