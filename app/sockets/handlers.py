import os
import json
import certifi
import threading
import websocket
from flask import request
from flask_socketio import emit
from datetime import datetime, UTC
from threading import Lock

# WebSocket URL
WEBSOCKET_URL = 'wss://stream.data.alpaca.markets/v2/delayed_sip'

# Track per-client watchlists (sid -> set of tickers)
watchlists = {}
MAX_TICKERS = 30

# Track websocket connection and current subscription
ws_app = None
current_subscribed = set()
ws_connected = False

# Cache for latest stock data (symbol -> data)
latest_stock_data = {}
stock_data_lock = Lock()


def on_message_handler(ws, message, socketio):
    """Handle incoming WebSocket messages from Alpaca stream."""
    try:
        messages = json.loads(message)
        for msg in messages:
            if msg['T'] == 'q':
                data = {
                    'symbol': msg['S'],
                    'bid_price': float(msg.get('bp', 0)),
                    'ask_price': float(msg.get('ap', 0)),
                    'timestamp': msg.get('t', ''),
                    'market_hours': 'open'
                }
                with stock_data_lock:
                    latest_stock_data[data['symbol']] = data
                for sid, tickers in watchlists.items():
                    if data['symbol'] in tickers:
                        socketio.emit(
                            'quote', {'data': data, 'type': 'quote'}, namespace='/ws/watchlist', to=sid)
    except Exception as e:
        print(f"Error processing message: {e}")


def on_error_handler(ws, error):
    """Handle WebSocket errors."""
    global ws_connected
    ws_connected = False
    print(f"WebSocket error: {error}")


def on_close_handler(ws, close_status_code, close_msg):
    """Handle WebSocket connection close."""
    global ws_connected
    ws_connected = False
    print("WebSocket closed.")


def on_open_handler(ws):
    """Handle WebSocket connection open."""
    print("WebSocket connected.")
    global ws_connected
    ws_connected = True
    auth_message = {
        "action": "auth",
        "key": os.getenv('APCA_API_KEY_ID'),
        "secret": os.getenv('APCA_API_SECRET_KEY')
    }
    ws.send(json.dumps(auth_message))

    # After auth, re-subscribe to all currently watched tickers
    update_ws_subscription()

def run_websocket(socketio, fetchers):
    """Run the WebSocket connection in a thread."""
    global ws_app
    ws_app = websocket.WebSocketApp(
        WEBSOCKET_URL,
        on_message=lambda ws, msg: on_message_handler(
            ws, msg, socketio),
        on_error=lambda ws, err: on_error_handler(ws, err),
        on_close=lambda ws, a, b: on_close_handler(ws, a, b),
        on_open=lambda ws: on_open_handler(ws)
    )
    ws_app.run_forever(sslopt={"ca_certs": certifi.where()})


def update_ws_subscription():
    """Update WebSocket subscription for current watchlist."""
    global ws_app, ws_connected
    if ws_app and ws_connected:
        try:
            # This is a simplified update. For more complex scenarios,
            # you might want to calculate the diff between old and new subscriptions.
            if current_subscribed:
                subscribe_message = {"action": "subscribe",
                                     "quotes": list(current_subscribed)}
                ws_app.send(json.dumps(subscribe_message))
        except Exception as e:
            print(f"Error updating subscription: {e}")

def update_ws_subscription_diff(added=None, removed=None):
    """Update WebSocket subscription with added/removed tickers."""
    global ws_app, ws_connected
    if ws_app and ws_connected:
        try:
            if added:
                ws_app.send(json.dumps({"action": "subscribe", "quotes": list(added)}))
            if removed:
                ws_app.send(json.dumps({"action": "unsubscribe", "quotes": list(removed)}))
        except Exception as e:
            print(f"Error updating subscription diff: {e}")


def refresh_all_quotes(socketio, fetchers):
    """Periodically refresh quotes for all watched symbols."""
    while True:
        market_status = fetchers.get_market_status()

        if current_subscribed:
            for symbol in current_subscribed:
                quote_data = fetchers.fetch_latest_quote(symbol)
                if quote_data:
                    with stock_data_lock:
                        latest_stock_data[symbol] = quote_data
                    # Use a copy of watchlists to avoid issues with concurrent modifications
                    for sid, tickers in list(watchlists.items()):
                        if symbol in tickers and sid in watchlists: # Check if sid still exists
                            socketio.emit('quote', {'data': quote_data, 'type': 'quote'}, namespace='/ws/watchlist', to=sid)
        
        socketio.emit('market_status', market_status, namespace='/ws/watchlist')

        # Dynamic sleep time calculation
        if market_status['is_open']:
            sleep_time = 30
        else:
            sleep_time = 180
        socketio.sleep(sleep_time)


def register_socket_handlers(socketio, fetchers):
    """Registers all SocketIO event handlers."""
    @socketio.on('connect', namespace='/ws/watchlist')
    def handle_connect(auth=None):
        sid = request.sid
        watchlists[sid] = set()
        socketio.emit('watchlist', {'tickers': list(
            watchlists[sid])}, namespace='/ws/watchlist', to=sid)
        market_status = fetchers.get_market_status()
        socketio.emit('market_status', market_status,
                      namespace='/ws/watchlist', to=sid)

        if not any(t.name == 'websocket_thread' for t in threading.enumerate()):
            ws_thread = threading.Thread(
                target=run_websocket, name='websocket_thread', daemon=True, args=(socketio, fetchers))
            ws_thread.start()

        if not any(t.name == 'quote_refresh_thread' for t in threading.enumerate()):
            refresh_thread = threading.Thread(
                target=refresh_all_quotes, name='quote_refresh_thread', daemon=True, args=(socketio, fetchers))
            refresh_thread.start()

    @socketio.on('disconnect', namespace='/ws/watchlist')
    def handle_disconnect():
        sid = request.sid
        if sid in watchlists:
            global current_subscribed
            previous_subscribed = current_subscribed.copy()
            del watchlists[sid]
            current_subscribed = set.union(
                *watchlists.values()) if watchlists else set()
            removed = previous_subscribed - current_subscribed
            update_ws_subscription_diff(removed=removed)

    @socketio.on('add_ticker', namespace='/ws/watchlist')
    def handle_add_ticker(data):
        sid = request.sid
        ticker = data.get('ticker', '').upper().strip()
        if not ticker or len(ticker) > 5 or ticker in watchlists[sid]:
            return

        watchlists[sid].add(ticker)
        global current_subscribed
        previous_subscribed = current_subscribed.copy()
        current_subscribed = set.union(
            *watchlists.values()) if watchlists else set()
        
        newly_added = current_subscribed - previous_subscribed
        update_ws_subscription_diff(added=newly_added)

        quote_data = fetchers.fetch_latest_quote(ticker)
        if quote_data:
            with stock_data_lock:
                latest_stock_data[ticker] = quote_data
            socketio.emit('quote', {
                          'data': quote_data, 'type': 'quote'}, namespace='/ws/watchlist', to=sid)

        socketio.emit('watchlist', {'tickers': list(
            watchlists[sid])}, namespace='/ws/watchlist', to=sid)

    @socketio.on('remove_ticker', namespace='/ws/watchlist')
    def handle_remove_ticker(data):
        sid = request.sid
        ticker = data.get('ticker', '').upper().strip()
        if sid in watchlists and ticker in watchlists[sid]:
            watchlists[sid].remove(ticker)
            
            global current_subscribed
            previous_subscribed = current_subscribed.copy()
            current_subscribed = set.union(
                *watchlists.values()) if watchlists else set()
            removed = previous_subscribed - current_subscribed
            update_ws_subscription_diff(removed=removed)
            with stock_data_lock:
                if ticker in latest_stock_data:
                    del latest_stock_data[ticker]
        socketio.emit('watchlist', {'tickers': list(
            watchlists.get(sid, []))}, namespace='/ws/watchlist', to=sid)

    @socketio.on('request_all_data', namespace='/ws/watchlist')
    def handle_request_all_data():
        sid = request.sid
        if sid in watchlists:
            with stock_data_lock:
                for ticker in watchlists[sid]:
                    if ticker in latest_stock_data:
                        socketio.emit('quote', {
                                      'data': latest_stock_data[ticker], 'type': 'quote'}, namespace='/ws/watchlist', to=sid)
