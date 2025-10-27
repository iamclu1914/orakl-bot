"""
Ticker Translation Utility
Handles common ticker confusions and legacy names
"""

# Common ticker translations
TICKER_TRANSLATIONS = {
    'BLOCK': 'SQ',       # Block Inc. (formerly Square) 
    'FB': 'META',        # Meta (formerly Facebook)
    'DIDI': 'DIDIY',     # DiDi after delisting
    'BRKB': 'BRK.B',     # Berkshire Hathaway B (Polygon expects dot notation)
    'BRKA': 'BRK.A',     # Berkshire Hathaway A (Polygon expects dot notation)
    'BRK-B': 'BRK.B',    # Alternate hyphen format
    'BRK-A': 'BRK.A',    # Alternate hyphen format
    'BRK.B': 'BRK.B',    # Already in dot format
    'BRK.A': 'BRK.A',    # Already in dot format
    'ABC': 'COR',        # AmerisourceBergen rebranded to Cencora (COR)
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
