import os
import json
import pytz
import base64
import certifi
import websocket
import threading
import matplotlib
import pandas as pd
import yfinance as yf
from io import BytesIO
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import alpaca_trade_api as tradeapi
from flask_socketio import SocketIO
from datetime import datetime, UTC, timedelta
from alpaca.trading.client import TradingClient
from alpaca.data import StockHistoricalDataClient
from flask import Flask, render_template, request
from alpaca_trade_api.rest import REST as AlpacaREST
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
from flask import Flask, render_template, request, jsonify
from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest


# Load environment variables
load_dotenv()

# Use Agg backend for matplotlib to avoid GUI issues in server environments
matplotlib.use('Agg')

# Initialize Flask app and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', engineio_logger=True)

# Initialize Alpaca client (use your env vars)
trading_client = TradingClient(
    os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])

# Fetch all active US equity assets once on startup
assets_request = GetAssetsRequest(
    asset_class=AssetClass.US_EQUITY, status=AssetStatus.ACTIVE)
all_assets = trading_client.get_all_assets(assets_request)
symbol_to_exchange = {asset.symbol: asset.exchange for asset in all_assets}


# Debug template path
print(f"Template folder: {app.template_folder}")
print(f"Current working directory: {os.getcwd()}")
print(f"Template exists: {os.path.exists(os.path.join(app.template_folder, 'index.html'))}")

# Alpaca API credentials
APCA_API_KEY_ID = os.getenv('APCA_API_KEY_ID')
APCA_API_SECRET_KEY = os.getenv('APCA_API_SECRET_KEY')

if not APCA_API_KEY_ID or not APCA_API_SECRET_KEY:
    raise ValueError("Please set APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables")

# Initialize Alpaca REST API client for fetching latest data
alpaca_api = tradeapi.REST(
    APCA_API_KEY_ID,
    APCA_API_SECRET_KEY,
    'https://paper-api.alpaca.markets',  # Use paper trading endpoint
    api_version='v2'
)

# WebSocket URL (toggle between test and delayed_sip)
# WEBSOCKET_URL = 'wss://stream.data.alpaca.markets/v2/test'  # Uncomment for FAKEPACA
WEBSOCKET_URL = 'wss://stream.data.alpaca.markets/v2/delayed_sip'  # Delayed SIP

# Track per-client watchlists (sid -> set of tickers)
watchlists = {}
MAX_TICKERS = 30

# Track websocket connection and current subscription
ws_app = None
current_subscribed = set()
ws_connected = False

# Cache for latest stock data (symbol -> data)
latest_stock_data = {}
stock_data_lock = threading.Lock()

data_client = StockHistoricalDataClient(
    os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])

def fetch_latest_quote(symbol):
    """
    Fetch the latest quote for a symbol using Alpaca REST API.
    This works even when the market is closed.
    
    Args:
        symbol (str): The stock symbol to fetch quote for
    
    Returns:
        dict: Quote data including bid/ask prices and timestamp
    """
    try:
        # Get the latest quote from Alpaca
        quote = alpaca_api.get_latest_quote(symbol)
        
        # Convert timestamp to Eastern Time for display
        eastern = pytz.timezone('US/Eastern')
        timestamp = quote.timestamp.replace(tzinfo=pytz.UTC).astimezone(eastern)
        
        return {
            'symbol': symbol,
            'bid_price': float(quote.bid_price),
            'ask_price': float(quote.ask_price),
            'bid_size': int(quote.bid_size),
            'ask_size': int(quote.ask_size),
            'timestamp': timestamp.isoformat(),
            'market_hours': 'closed' if not is_market_open() else 'open'
        }
    except Exception as e:
        print(f"Error fetching quote for {symbol}: {e}")
        return None

def fetch_latest_trades(symbols):
    """
    Fetch the latest trades for multiple symbols.
    
    Args:
        symbols (list): List of stock symbols
    
    Returns:
        dict: Dictionary of symbol -> trade data
    """
    try:
        if not symbols:
            return {}
        
        # Get latest trades for all symbols
        trades = alpaca_api.get_latest_trades(symbols)
        
        result = {}
        eastern = pytz.timezone('US/Eastern')
        
        for symbol, trade in trades.items():
            if trade:
                timestamp = trade.timestamp.replace(tzinfo=pytz.UTC).astimezone(eastern)
                result[symbol] = {
                    'price': float(trade.price),
                    'size': int(trade.size),
                    'timestamp': timestamp.isoformat()
                }
        
        return result
    except Exception as e:
        print(f"Error fetching trades: {e}")
        return {}

def is_market_open():
    """
    Check if the US stock market is currently open.
    
    Returns:
        bool: True if market is open, False otherwise
    """
    try:
        clock = alpaca_api.get_clock()
        print(f"Market is_open: {clock.is_open}, next_open: {clock.next_open}, next_close: {clock.next_close}")
        return clock.is_open
    
    except:
        print(f"Mark")
        return False

def get_market_status():
    """
    Get detailed market status information.
    
    Returns:
        dict: Market status including open/close times
    """
    try:
        clock = alpaca_api.get_clock()
        eastern = pytz.timezone('US/Eastern')
        
        next_open = clock.next_open.replace(tzinfo=pytz.UTC).astimezone(eastern) if clock.next_open else None
        next_close = clock.next_close.replace(tzinfo=pytz.UTC).astimezone(eastern) if clock.next_close else None
        
        return {
            'is_open': clock.is_open,
            'next_open': next_open.strftime('%Y-%m-%d %I:%M %p %Z') if next_open else None,
            'next_close': next_close.strftime('%Y-%m-%d %I:%M %p %Z') if next_close else None
        }
    except Exception as e:
        print(f"Error getting market status: {e}")
        return {'is_open': False, 'next_open': None, 'next_close': None}

def on_message(ws, message):
    """
    Handle incoming WebSocket messages from Alpaca stream.
    """
    print(f"Message received at {datetime.now(UTC).isoformat()}")
    try:
        messages = json.loads(message)
        for msg in messages:
            if msg['T'] == 'success':
                print(f"Success: {msg['msg']}")
                if msg['msg'] == 'authenticated':
                    global ws_connected
                    ws_connected = True
                    # Subscribe to all currently watched tickers
                    if current_subscribed:
                        subscribe_message = {
                            "action": "subscribe",
                            "quotes": list(current_subscribed)
                        }
                        print(f"Sending subscription at {datetime.now(UTC).isoformat()}: {subscribe_message}")
                        ws.send(json.dumps(subscribe_message))
            elif msg['T'] == 'subscription':
                print(f"Current subscriptions: {msg}")
            elif msg['T'] == 'q':
                # Process quote message
                data = {
                    'symbol': msg['S'],
                    'bid_price': float(msg.get('bp', 0)),
                    'ask_price': float(msg.get('ap', 0)),
                    'bid_size': int(msg.get('bs', 0)),
                    'ask_size': int(msg.get('as', 0)),
                    'timestamp': msg.get('t', ''),
                    'market_hours': 'open'  # Real-time data means market is open
                }
                
                if data['bid_price'] == 0 and data['ask_price'] == 0:
                    print(f"Skipping zero-price quote for {data['symbol']}")
                    return
                
                # Update cached data
                with stock_data_lock:
                    latest_stock_data[data['symbol']] = data
                
                # Emit only to clients watching this symbol
                for sid, tickers in watchlists.items():
                    if data['symbol'] in tickers:
                        socketio.emit('quote', {'data': data, 'type': 'quote'}, namespace='/ws/watchlist', to=sid)
            elif msg['T'] == 'error':
                print(f"Error: {msg['code']} - {msg['msg']}")
                if msg['code'] == 406:
                    ws.close()
    except Exception as e:
        print(f"Error processing message: {e}")

def on_error(ws, error):
    """Handle WebSocket errors."""
    global ws_connected
    ws_connected = False
    print(f"WebSocket error at {datetime.now(UTC).isoformat()}: {error}")
    threading.Timer(3, run_websocket).start()

def on_close(ws, close_status_code, close_msg):
    """Handle WebSocket connection close."""
    global ws_connected
    ws_connected = False
    print(f"WebSocket closed at {datetime.now(UTC).isoformat()}: {close_status_code} - {close_msg}")
    threading.Timer(3, run_websocket).start()

def on_open(ws):
    """Handle WebSocket connection open."""
    print(f"WebSocket connected at {datetime.now(UTC).isoformat()}")
    auth_message = {
        "action": "auth",
        "key": APCA_API_KEY_ID,
        "secret": APCA_API_SECRET_KEY
    }
    print(f"Sending auth at {datetime.now(UTC).isoformat()}: {auth_message}")
    ws.send(json.dumps(auth_message))

def run_websocket():
    """Run the WebSocket connection in a thread."""
    global ws_app
    print(f"Starting WebSocket thread at {datetime.now(UTC).isoformat()}")
    ws_app = websocket.WebSocketApp(
        WEBSOCKET_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open
    )
    ws_app.run_forever(sslopt={"ca_certs": certifi.where()})

def update_ws_subscription():
    """Update WebSocket subscription for current watchlist."""
    global ws_app, ws_connected
    if ws_app and ws_connected:
        # First unsubscribe from all
        unsubscribe_message = {
            "action": "unsubscribe",
            "quotes": ["*"]
        }
        try:
            ws_app.send(json.dumps(unsubscribe_message))
        except:
            pass
        
        # Then subscribe to current set
        if current_subscribed:
            subscribe_message = {
                "action": "subscribe",
                "quotes": list(current_subscribed)
            }
            print(f"Updating subscription: {subscribe_message}")
            try:
                ws_app.send(json.dumps(subscribe_message))
            except Exception as e:
                print(f"Error updating subscription: {e}")

def refresh_all_quotes():
    """
    Periodically refresh quotes for all watched symbols.
    This ensures data is available even when market is closed.
    """
    while True:
        if current_subscribed:
            print(f"Refreshing quotes for {len(current_subscribed)} symbols at {datetime.now(UTC).isoformat()}")
            
            # Fetch latest quotes for all subscribed symbols
            for symbol in current_subscribed:
                quote_data = fetch_latest_quote(symbol)
                if quote_data:
                    # Update cached data
                    with stock_data_lock:
                        latest_stock_data[symbol] = quote_data
                    
                    # Emit to all clients watching this symbol
                    for sid, tickers in watchlists.items():
                        if symbol in tickers:
                            socketio.emit('quote', {'data': quote_data, 'type': 'quote'}, 
                                        namespace='/ws/watchlist', to=sid)
            
            # Also fetch latest trades
            trades = fetch_latest_trades(list(current_subscribed))
            for symbol, trade_data in trades.items():
                # Emit trade data to clients
                for sid, tickers in watchlists.items():
                    if symbol in tickers:
                        socketio.emit('trade', {'symbol': symbol, 'data': trade_data}, 
                                    namespace='/ws/watchlist', to=sid)
        
        # Send market status update
        market_status = get_market_status()
        socketio.emit('market_status', market_status, namespace='/ws/watchlist')
        
        # Refresh every 30 seconds when market is closed, every 60 seconds when open
        sleep_time = 10800 if not is_market_open() else 120
        socketio.sleep(sleep_time)

# Flask routes
@app.route('/')
def index():
    """Render the main application page."""
    print(f"Rendering index.html at {datetime.now(UTC).isoformat()}")
    return render_template('index.html')

# Route for the all-stocks page (renders the table)


@app.route('/all_stocks')
def all_stocks():
    return render_template('all_stocks.html')

# API endpoint for DataTables server-side processing


@app.route('/api/assets')
def api_assets():
    draw = int(request.args.get('draw', 1))
    start = int(request.args.get('start', 0))
    length = int(request.args.get('length', 100))  # Default to 100 per page
    search_value = request.args.get('search[value]', '').lower()
    # 0: symbol, 1: name, etc.
    order_column = int(request.args.get('order[0][column]', 0))
    order_dir = request.args.get('order[0][dir]', 'asc')

    # Filter assets by search (on symbol or name)
    filtered_assets = [
        asset for asset in all_assets
        if search_value in asset.symbol.lower() or search_value in asset.name.lower()
    ]

    # Sort filtered list
    # Adjust based on your table columns
    column_map = {0: 'symbol', 1: 'name', 2: 'exchange'}
    sort_key = column_map.get(order_column, 'symbol')
    filtered_assets.sort(key=lambda a: getattr(
        a, sort_key).lower(), reverse=(order_dir == 'desc'))

    # Paginate
    paginated_assets = filtered_assets[start:start + length]

    # Prepare data for DataTables (list of dicts or lists; here, lists for simplicity)
    data = []
    for asset in paginated_assets:
        data.append([
            # Clickable symbol
            f'<a href="/stock/{asset.symbol}">{asset.symbol}</a>',
            asset.name,
            asset.exchange
        ])

    return jsonify({
        'draw': draw,
        'recordsTotal': len(all_assets),
        'recordsFiltered': len(filtered_assets),
        'data': data
    })

# Dynamic route for stock details


@app.route('/stock/<symbol>')
def stock_details(symbol):
    data = {}

    # Fetch from Alpaca (real-time quote, bars, news)
    quote = alpaca_api.get_latest_quote(symbol)
    start_date = (datetime.now() - timedelta(days=365)).date().isoformat()
    bars = alpaca_api.get_bars(symbol, timeframe='1D', start=start_date, limit=365)
    news = alpaca_api.get_news(symbol, limit=5)  # Recent news

    data['symbol'] = symbol
    data['exchange'] = symbol_to_exchange.get(symbol, 'N/A')
    data['current_price'] = quote.ask_price  # Or use last trade, etc.
    data['bid_price'] = quote.bid_price
    data['ask_price'] = quote.ask_price
    latest_bar = alpaca_api.get_latest_bar(symbol)
    data['volume'] = latest_bar.volume if latest_bar else 'N/A'
    latest_trade = alpaca_api.get_latest_trade(symbol)
    data['latest_trade_price'] = latest_trade.price if latest_trade else 'N/A'

    # Convert bars to DataFrame for history
    history_df = pd.DataFrame([bar._raw for bar in bars])
    history_df['timestamp'] = pd.to_datetime(history_df['t'])

    # Fetch from yFinance (fundamentals, financials, more info)
    ticker = yf.Ticker(symbol)
    info = ticker.info
    data['name'] = info.get('longName', 'N/A')
    data['description'] = info.get('longBusinessSummary', 'N/A')
    data['sector'] = info.get('sector', 'N/A')
    data['industry'] = info.get('industry', 'N/A')
    data['website'] = info.get('website', 'N/A')
    data['market_cap'] = info.get('marketCap', 'N/A')
    data['pe_ratio'] = info.get('trailingPE', 'N/A')
    data['fifty_two_week_high'] = info.get('fiftyTwoWeekHigh', 'N/A')
    data['fifty_two_week_low'] = info.get('fiftyTwoWeekLow', 'N/A')
    data['dividend_yield'] = info.get('dividendYield', 0) * 100
    data['eps'] = info.get('trailingEps', 'N/A')
    data['beta'] = info.get('beta', 'N/A')

    # IPO Date
    first_trade = info.get('firstTradeDateEpochUtc')
    data['ipo_date'] = datetime.fromtimestamp(
        first_trade).strftime('%Y-%m-%d') if first_trade else 'N/A'

    # Financials (simplified key metrics)
    data['financials'] = {}
    try:
        income = ticker.financials.iloc[:, 0]  # Latest year
        data['financials']['income_statement'] = {
            'Revenue': income.get('Total Revenue', 'N/A'),
            'Net Income': income.get('Net Income', 'N/A'),
            'EBITDA': income.get('EBITDA', 'N/A')
        }
        balance = ticker.balance_sheet.iloc[:, 0]
        data['financials']['balance_sheet'] = {
            'Total Assets': balance.get('Total Assets', 'N/A'),
            'Total Liabilities': balance.get('Total Liabilities Net Minority Interest', 'N/A'),
            'Equity': balance.get('Stockholders Equity', 'N/A')
        }
        cashflow = ticker.cashflow.iloc[:, 0]
        data['financials']['cash_flow'] = {
            'Operating Cash Flow': cashflow.get('Operating Cash Flow', 'N/A'),
            'Free Cash Flow': cashflow.get('Free Cash Flow', 'N/A')
        }
    except:
        data['financials'] = None

    # News from yFinance (supplement if Alpaca news is limited)
    yf_news = ticker.news[:5]


    data['news'] = []
    for item in yf_news:
        # Access the 'title' within the 'content' dictionary
        title = item.get('content', {}).get('title', 'No Title Available')
        # Access publisher within content -> provider -> displayName
        publisher = item.get('content', {}).get(
            'provider', {}).get('displayName', 'N/A')
        link = item.get('content', {}).get('canonicalUrl', {}).get(
            'url', '#')  # Access link within content -> canonicalUrl -> url
        
        # Convert ISO 8601 string to datetime object
        pub_date_str = item.get('content', {}).get('pubDate', '')
        if pub_date_str:
            # datetime.fromisoformat handles the 'Z' (UTC) and '+00:00' offsets automatically
            published_dt = datetime.fromisoformat(
                pub_date_str.replace('Z', '+00:00'))  # Handles 'Z' for UTC
            published_at = published_dt.strftime('%Y-%m-%d %H:%M')
        else:
            published_at = 'N/A'
            # Use summary within content and use title as fallback
        summary = item.get('content', {}).get('summary', title)

        data['news'].append({
            'title': title,
            'publisher': publisher,
            'link': link,
            'published_at': published_at,
            'summary': summary
        })

    # Historical Chart
    fig, ax = plt.subplots()
    history_df.plot(x='timestamp', y='c', ax=ax,
                    title=f'{symbol} 1-Year Price History')
    ax.set_ylabel('Price')
    buf = BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)
    data['history_chart'] = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)

    # Technical Indicators (using history_df)
    data['ma_50'] = history_df['c'].rolling(
        50).mean().iloc[-1] if len(history_df) >= 50 else 'N/A'
    data['ma_200'] = history_df['c'].rolling(
        200).mean().iloc[-1] if len(history_df) >= 200 else 'N/A'

    # RSI Calculation (simple 14-day)
    delta = history_df['c'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    data['rsi'] = 100 - (100 / (1 + rs.iloc[-1])
                         ) if len(history_df) >= 14 else 'N/A'

    # Intrinsic Value Calculation (Simple Graham Formula: Intrinsic = EPS * (8.5 + 2*growth) * 4.4 / yield)
    # Assume growth rate from yf (forwardEps or historical)
    growth_rate = info.get('earningsGrowth', 0.05) * 100  # Default 5%
    bond_yield = 4.4  # Approximate US Treasury yield; fetch dynamically if needed
    if data['eps'] != 'N/A' and data['eps'] > 0:
        intrinsic = (data['eps'] * (8.5 + 2 * growth_rate) * 4.4) / bond_yield
        data['intrinsic_value'] = round(intrinsic, 2)
    else:
        data['intrinsic_value'] = 'N/A'

    # Price Difference and Recommendation
    if data['intrinsic_value'] != 'N/A':
        data['price_difference'] = round(
            data['intrinsic_value'] - data['current_price'], 2)
        data['percentage_difference'] = round(
            (data['price_difference'] / data['current_price']) * 100, 2)
        if data['percentage_difference'] > 20:
            data['recommendation'] = 'buy'
        elif data['percentage_difference'] < -20:
            data['recommendation'] = 'sell'
        else:
            data['recommendation'] = 'hold'
    else:
        data['price_difference'] = 'N/A'
        data['percentage_difference'] = 'N/A'
        data['recommendation'] = 'hold'

    # Analysis Chart (Intrinsic vs Historical Price)
    if data['intrinsic_value'] != 'N/A':
        fig, ax = plt.subplots()
        history_df.plot(x='timestamp', y='c', ax=ax, label='Price')
        ax.axhline(data['intrinsic_value'], color='r',
                   linestyle='--', label='Intrinsic Value')
        ax.legend()
        ax.set_title(f'{symbol} Price vs Intrinsic Value')
        buf = BytesIO()
        fig.savefig(buf, format='png')
        buf.seek(0)
        data['analysis_chart'] = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
    else:
        data['analysis_chart'] = None

    return render_template('stock_details.html', data=data)

@socketio.on('connect', namespace='/ws/watchlist')
def handle_connect():
    """Handle client connection to watchlist namespace."""
    print(f"Client connected to watchlist namespace at {datetime.now(UTC).isoformat()}")
    sid = request.sid
    watchlists[sid] = set()  # Start with empty watchlist
    
    # Send current watchlist to client
    socketio.emit('watchlist', {'tickers': list(watchlists[sid])}, namespace='/ws/watchlist', to=sid)
    
    # Send market status
    market_status = get_market_status()
    socketio.emit('market_status', market_status, namespace='/ws/watchlist', to=sid)
    
    # Start websocket thread if not running
    if not any(t.name == 'websocket_thread' for t in threading.enumerate()):
        ws_thread = threading.Thread(target=run_websocket, name='websocket_thread', daemon=True)
        ws_thread.start()
    
    # Start quote refresh thread if not running
    if not any(t.name == 'quote_refresh_thread' for t in threading.enumerate()):
        refresh_thread = threading.Thread(target=refresh_all_quotes, name='quote_refresh_thread', daemon=True)
        refresh_thread.start()

@socketio.on('disconnect', namespace='/ws/watchlist')
def handle_disconnect():
    """Handle client disconnection from watchlist namespace."""
    print(f"Client disconnected from watchlist namespace at {datetime.now(UTC).isoformat()}")
    sid = request.sid
    if sid in watchlists:
        del watchlists[sid]
    global current_subscribed
    current_subscribed = set.union(*watchlists.values()) if watchlists else set()
    update_ws_subscription()

@socketio.on('add_ticker', namespace='/ws/watchlist')
def handle_add_ticker(data):
    """
    Add a ticker to the client's watchlist.
    
    Args:
        data (dict): Contains 'ticker' key with symbol to add
    """
    sid = request.sid
    ticker = data.get('ticker', '').upper().strip()
    
    # Validate ticker
    if not ticker or not ticker.isalnum() or len(ticker) > 5:
        socketio.emit('error', {'message': 'Invalid ticker symbol'}, namespace='/ws/watchlist', to=sid)
        return
    
    if sid not in watchlists:
        watchlists[sid] = set()
    
    if len(watchlists[sid]) >= MAX_TICKERS:
        socketio.emit('error', {'message': f'Maximum {MAX_TICKERS} tickers allowed'}, namespace='/ws/watchlist', to=sid)
        return
    
    if ticker in watchlists[sid]:
        socketio.emit('error', {'message': 'Ticker already in watchlist'}, namespace='/ws/watchlist', to=sid)
        return
    
    watchlists[sid].add(ticker)
    global current_subscribed
    previous_subscribed = current_subscribed.copy()
    current_subscribed = set.union(*watchlists.values()) if watchlists else set()
    
    # Only update subscription if we added a new ticker not previously watched
    if ticker not in previous_subscribed:
        update_ws_subscription()
        
        # Immediately fetch latest quote for new ticker
        quote_data = fetch_latest_quote(ticker)
        if quote_data:
            with stock_data_lock:
                latest_stock_data[ticker] = quote_data
            socketio.emit('quote', {'data': quote_data, 'type': 'quote'}, namespace='/ws/watchlist', to=sid)
    else:
        # Send cached data if available
        with stock_data_lock:
            if ticker in latest_stock_data:
                socketio.emit('quote', {'data': latest_stock_data[ticker], 'type': 'quote'}, 
                            namespace='/ws/watchlist', to=sid)
    
    socketio.emit('watchlist', {'tickers': list(watchlists[sid])}, namespace='/ws/watchlist', to=sid)
    print(f"Added {ticker} to watchlist for client {sid}")

@socketio.on('remove_ticker', namespace='/ws/watchlist')
def handle_remove_ticker(data):
    """
    Remove a ticker from the client's watchlist.
    
    Args:
        data (dict): Contains 'ticker' key with symbol to remove
    """
    sid = request.sid
    ticker = data.get('ticker', '').upper().strip()
    
    if sid in watchlists and ticker in watchlists[sid]:
        watchlists[sid].remove(ticker)
        global current_subscribed
        current_subscribed = set.union(*watchlists.values()) if watchlists else set()
        
        # Only update subscription if no other client is watching this ticker
        if ticker not in current_subscribed:
            update_ws_subscription()
            # Remove from cache
            with stock_data_lock:
                if ticker in latest_stock_data:
                    del latest_stock_data[ticker]
        
        print(f"Removed {ticker} from watchlist for client {sid}")
    
    socketio.emit('watchlist', {'tickers': list(watchlists.get(sid, []))}, namespace='/ws/watchlist', to=sid)

@socketio.on('request_all_data', namespace='/ws/watchlist')
def handle_request_all_data():
    """
    Handle request for all current stock data.
    Sends cached data for all stocks in the client's watchlist.
    """
    sid = request.sid
    if sid in watchlists:
        with stock_data_lock:
            for ticker in watchlists[sid]:
                if ticker in latest_stock_data:
                    socketio.emit('quote', {'data': latest_stock_data[ticker], 'type': 'quote'}, 
                                namespace='/ws/watchlist', to=sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
