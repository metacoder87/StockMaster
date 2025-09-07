import os
import pytz
import yfinance as yf
import pandas as pd
import alpaca
from dotenv import load_dotenv
from datetime import datetime, UTC, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.data.requests import StockLatestQuoteRequest

# Load environment variables
load_dotenv()


# Initialize Alpaca clients
APCA_API_KEY_ID = os.getenv('APCA_API_KEY_ID')
APCA_API_SECRET_KEY = os.getenv('APCA_API_SECRET_KEY')

if not APCA_API_KEY_ID or not APCA_API_SECRET_KEY:
    raise ValueError(
        "Please set APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables")

trading_client = TradingClient(
    APCA_API_KEY_ID, APCA_API_SECRET_KEY, paper=True)

stock_data_client = StockHistoricalDataClient(
    APCA_API_KEY_ID, APCA_API_SECRET_KEY
)

# Fetch all active US equity assets once on startup
assets_request = GetAssetsRequest(
    asset_class=AssetClass.US_EQUITY, status=AssetStatus.ACTIVE)
all_assets = trading_client.get_all_assets(assets_request)
symbol_to_exchange = {asset.symbol: asset.exchange for asset in all_assets}


def fetch_latest_quote(symbol):
    """
    Fetch the latest quote for a symbol using Alpaca REST API.
    
    Args:
        symbol (str): The stock symbol.
    
    Returns:
        dict: Quote data.
    """
    try:
        latest_quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        latest_quote = stock_data_client.get_stock_latest_quote(latest_quote_request)
        if symbol in latest_quote:
            quote = latest_quote[symbol]
            eastern = pytz.timezone('US/Eastern')
            timestamp = quote.timestamp.astimezone(eastern)
            return {
                'symbol': symbol,
                'bid_price': float(quote.bid_price),
                'ask_price': float(quote.ask_price),
                'bid_size': int(quote.bid_size),
                'ask_size': int(quote.ask_size),
                'timestamp': timestamp.isoformat(),
                'market_hours': 'closed' if not is_market_open() else 'open'
            }
        return None
    except Exception as e:
        print(f"Error fetching quote for {symbol}: {e}")
        return None


def is_market_open():
    """Checks if the US stock market is currently open."""
    try:
        clock = trading_client.get_clock()
        return clock.is_open
    except Exception as e:
        print(f"Error checking market status: {e}")
        return False


def get_market_status():
    """Gets detailed market status information."""
    try:
        clock = trading_client.get_clock()
        eastern = pytz.timezone('US/Eastern')
        next_open_dt_utc = clock.next_open
        next_close_dt_utc = clock.next_close

        next_open_eastern = next_open_dt_utc.astimezone(eastern) if next_open_dt_utc else None
        next_close_eastern = next_close_dt_utc.astimezone(eastern) if next_close_dt_utc else None
        return {
            'is_open': clock.is_open,
            'next_open': next_open_eastern.strftime('%Y-%m-%d %I:%M %p %Z') if next_open_eastern else None,
            'next_close': next_close_eastern.strftime('%Y-%m-%d %I:%M %p %Z') if next_close_eastern else None
        }
    except Exception as e:
        print(f"Error getting market status: {e}")
        return {'is_open': False, 'next_open': None, 'next_close': None}


def get_stock_details(symbol):
    """Fetches comprehensive stock data from Alpaca and yFinance."""
    data = {}
    try:
        # Alpaca Data
        latest_quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        latest_quote = stock_data_client.get_stock_latest_quote(latest_quote_request)
        
        start_date = (datetime.now() - timedelta(days=365)).date().isoformat()
        bars_request = alpaca.data.requests.StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=alpaca.data.timeframe.TimeFrame.Day,
            start=start_date
        )
        bars = stock_data_client.get_stock_bars(bars_request).df

        data['symbol'] = symbol
        data['exchange'] = symbol_to_exchange.get(symbol, 'N/A')
        
        if symbol in latest_quote:
            quote = latest_quote[symbol]
            data['current_price'] = float(quote.ask_price)
            data['bid_price'] = float(quote.bid_price)
            data['ask_price'] = float(quote.ask_price)
        else:
            data['current_price'] = 0
            data['bid_price'] = 0
            data['ask_price'] = 0

        # yFinance Data
        ticker = yf.Ticker(symbol)
        info = ticker.info

        data['name'] = info.get('longName', 'N/A')
        data['description'] = info.get('longBusinessSummary', 'N/A')
        data['sector'] = info.get('sector', 'N/A')
        data['industry'] = info.get('industry', 'N/A')
        data['website'] = info.get('website', 'N/A')
        data['market_cap'] = info.get('marketCap', 'N/A')
        data['pe_ratio'] = info.get('trailingPE', 'N/A')
        data['eps'] = info.get('trailingEps', 'N/A')
        data['earnings_growth'] = info.get('earningsGrowth') # Can be None
        data['fifty_two_week_high'] = info.get('fiftyTwoWeekHigh', 'N/A')
        data['fifty_two_week_low'] = info.get('fiftyTwoWeekLow', 'N/A')

        # Financials and News
        data['financials'] = {
            'income_statement': {k: str(v) for k, v in ticker.financials.iloc[:, 0].items()} if not ticker.financials.empty else {},
            'balance_sheet': {k: str(v) for k, v in ticker.balance_sheet.iloc[:, 0].items()} if not ticker.balance_sheet.empty else {},
            'cash_flow': {k: str(v) for k, v in ticker.cashflow.iloc[:, 0].items()} if not ticker.cashflow.empty else {},
        }

        yf_news = ticker.news[:5]
        data['news'] = []
        for item in yf_news:
            news_content = item.get('content', {})
            if not news_content:
                continue

            published_at = 'N/A'
            pub_date_str = news_content.get('pubDate')
            if pub_date_str:
                # pubDate is in '2025-09-05T19:01:00Z' format
                published_dt = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                published_at = published_dt.strftime('%Y-%m-%d %H:%M')

            data['news'].append({
                'title': news_content.get('title', 'N/A'),
                'publisher': news_content.get('provider', {}).get('displayName', 'N/A'),
                'link': news_content.get('canonicalUrl', {}).get('url', '#'),
                'published_at': published_at,
                'summary': news_content.get('summary', 'N/A')
            })

        # Historical data for charts and indicators
        if not bars.empty:
            # Alpaca returns a multi-index dataframe, we need to reset it for a single symbol
            bars = bars.reset_index()
            bars.rename(columns={'close': 'c'}, inplace=True)
            data['history_df'] = bars
        else:
            data['history_df'] = None
    except Exception as e:
        print(f"Error fetching details for {symbol}: {e}")
        return None

    return data