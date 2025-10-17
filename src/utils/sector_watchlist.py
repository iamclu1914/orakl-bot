"""Comprehensive sector-based watchlist for mega and large cap stocks"""

# Mega and Large Cap stocks by sector (Market Cap > $10B)
SECTOR_WATCHLIST = {
    "Technology": [
        # Mega caps (>$200B)
        "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "TSM", "AVGO", "ORCL", "CSCO",
        # Large caps ($10B-$200B)
        "ADBE", "CRM", "ACN", "INTC", "IBM", "TXN", "QCOM", "AMD", "INTU", "NOW",
        "AMAT", "MU", "LRCX", "ADI", "KLAC", "SNPS", "CDNS", "ASML", "MRVL", "NXPI",
        "CRWD", "PANW", "PLTR", "ADSK", "WDAY", "TEAM", "SNOW", "NET", "DDOG", "ZS",
        "FTNT", "MSI", "APH", "TEL", "GLW", "HPQ", "DELL", "HPE", "WDC", "STX"
    ],
    
    "Healthcare": [
        # Mega caps
        "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT",
        # Large caps  
        "DHR", "BMY", "AMGN", "CVS", "MDT", "ELV", "CI", "GILD", "SYK", "ISRG",
        "ZTS", "BDX", "HUM", "VRTX", "MCK", "REGN", "HCA", "BSX", "EW", "ABC",
        "COR", "A", "IQV", "IDXX", "MTD", "BIIB", "MRNA", "DXCM", "BAX", "ZBH"
    ],
    
    "Financials": [
        # Mega caps
        "BRK.B", "BRK.A", "JPM", "V", "MA", "BAC", "WFC",
        # Large caps
        "GS", "MS", "AXP", "SPGI", "BLK", "C", "SCHW", "CB", "PGR", "BX",
        "CME", "ICE", "AON", "MMC", "PNC", "USB", "TFC", "TRV", "AIG", "MET",
        "PRU", "ALL", "COF", "BK", "STT", "TROW", "MSCI", "NDAQ", "CBOE", "FIS",
        "AFL", "DFS", "WTW", "AJG", "MTB", "FITB", "HBAN", "RF", "CFG", "KEY"
    ],
    
    "Consumer Discretionary": [
        # Mega caps
        "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX",
        # Large caps
        "BKNG", "TGT", "CMG", "MAR", "GM", "F", "HLT", "ORLY", "AZO", "RCL",
        "DHI", "LEN", "YUM", "ROST", "DG", "DLTR", "DPZ", "LULU", "DECK", "NVR",
        "TSCO", "ULTA", "EXPE", "EBAY", "ETSY", "LVS", "WYNN", "MGM", "CCL", "NCLH"
    ],
    
    "Communication Services": [
        # Mega caps
        "GOOGL", "GOOG", "META", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS",
        # Large caps
        "CHTR", "EA", "TTWO", "ATVI", "WBD", "PARA", "FOX", "FOXA", "OMC", "IPG",
        "ROKU", "MTCH", "PINS", "SNAP", "SPOT", "RBLX", "DASH", "ABNB", "UBER", "LYFT"
    ],
    
    "Consumer Staples": [
        # Mega caps
        "WMT", "PG", "COST", "KO", "PEP",
        # Large caps
        "PM", "MDLZ", "MO", "CL", "EL", "KMB", "GIS", "ADM", "KDP", "MNST",
        "STZ", "KHC", "SYY", "HSY", "K", "CHD", "CLX", "TSN", "CAG", "MKC",
        "CPB", "SJM", "HRL", "BG", "LW", "TAP", "KR", "ACI", "WBA", "CVS"
    ],
    
    "Energy": [
        # Mega caps
        "XOM", "CVX",
        # Large caps
        "COP", "SLB", "EOG", "MPC", "VLO", "PSX", "OXY", "HES", "KMI", "WMB",
        "ET", "EPD", "BKR", "HAL", "DVN", "FANG", "TRGP", "LNG", "CTRA", "OKE"
    ],
    
    "Industrials": [
        # Mega caps
        "BA", "RTX", "HON", "UPS", "UNP", "CAT", "LMT", "DE", "GE",
        # Large caps
        "NOC", "CSX", "NSC", "FDX", "ETN", "ITW", "MMM", "EMR", "GD", "TDG",
        "CARR", "OTIS", "JCI", "CMI", "ROK", "DOV", "VRSK", "IR", "FAST", "ODFL",
        "AME", "RSG", "WM", "CPRT", "URI", "WAB", "PWR", "GNRC", "J", "IEX"
    ],
    
    "Materials": [
        # Large caps
        "LIN", "APD", "SHW", "ECL", "DD", "NEM", "FCX", "CTVA", "DOW", "PPG",
        "NUE", "VMC", "MLM", "BALL", "AVY", "CF", "CE", "FMC", "MOS", "ALB",
        "EMN", "LYB", "STLD", "RS", "CLF", "X", "AA", "WRK", "IP", "PKG"
    ],
    
    "Real Estate": [
        # Large caps
        "PLD", "AMT", "CCI", "EQIX", "PSA", "O", "WELL", "DLR", "SPG", "VICI",
        "AVB", "EQR", "VTR", "INVH", "MAA", "ARE", "UDR", "HST", "KIM", "REG",
        "ESS", "CPT", "PEAK", "CUBE", "FR", "ELS", "AMH", "BXP", "VNO", "MPW"
    ],
    
    "Utilities": [
        # Large caps
        "NEE", "SO", "DUK", "CEG", "AEP", "D", "SRE", "PCG", "EXC", "XEL",
        "ED", "WEC", "ES", "DTE", "AWK", "PPL", "AEE", "CMS", "CNP", "ATO",
        "LNT", "EVRG", "AES", "FE", "NI", "PNW", "OGE", "NRG", "VST", "UGI"
    ]
}

# Flatten all sectors into a single list
ALL_MEGA_LARGE_CAPS = []
for sector, tickers in SECTOR_WATCHLIST.items():
    ALL_MEGA_LARGE_CAPS.extend(tickers)

# Remove duplicates (some stocks appear in multiple sectors)
ALL_MEGA_LARGE_CAPS = list(set(ALL_MEGA_LARGE_CAPS))

# Additional ETFs for sector exposure
SECTOR_ETFS = [
    "SPY", "QQQ", "DIA", "IWM", "XLK", "XLV", "XLF", "XLY", "XLC", 
    "XLP", "XLE", "XLI", "XLB", "XLRE", "XLU", "VTI", "VOO", "IVV"
]

# Complete STRAT watchlist
STRAT_COMPLETE_WATCHLIST = sorted(ALL_MEGA_LARGE_CAPS + SECTOR_ETFS)

def get_strat_watchlist():
    """Get the complete STRAT bot watchlist"""
    return STRAT_COMPLETE_WATCHLIST

def get_sector_tickers(sector_name):
    """Get tickers for a specific sector"""
    return SECTOR_WATCHLIST.get(sector_name, [])

def get_watchlist_stats():
    """Get statistics about the watchlist"""
    stats = {
        "total_tickers": len(STRAT_COMPLETE_WATCHLIST),
        "sectors": {}
    }
    
    for sector, tickers in SECTOR_WATCHLIST.items():
        stats["sectors"][sector] = len(tickers)
    
    stats["etfs"] = len(SECTOR_ETFS)
    
    return stats

# Print stats when imported
if __name__ == "__main__":
    stats = get_watchlist_stats()
    print(f"Total STRAT Watchlist: {stats['total_tickers']} tickers")
    print("\nBreakdown by sector:")
    for sector, count in stats['sectors'].items():
        print(f"  {sector}: {count} stocks")
    print(f"  ETFs: {stats['etfs']} ETFs")
