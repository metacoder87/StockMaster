import pytest
from unittest.mock import patch, MagicMock
from app.app import app, socketio
from app.sockets import handlers

@pytest.fixture
def client():
    """Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def socket_client(client):
    """SocketIO test client."""
    return socketio.test_client(app, namespace='/ws/watchlist')

@pytest.fixture(autouse=True)
def clear_watchlists():
    """Clear watchlists before each test."""
    handlers.watchlists.clear()

@pytest.fixture(autouse=True)
def mock_fetchers():
    """Mock fetchers module to prevent real API calls."""
    with patch('app.data.fetchers.get_market_status', return_value={'is_open': True}) as mock_get_market_status, \
         patch('app.data.fetchers.fetch_latest_quote', return_value={
            'symbol': 'AAPL', 'ask_price': 150.0
         }) as mock_fetch_latest_quote:
        yield {
            'get_market_status': mock_get_market_status,
            'fetch_latest_quote': mock_fetch_latest_quote
        }

@pytest.fixture(autouse=True)
def mock_threads():
    """Mock background threads from starting."""
    with patch('threading.Thread') as mock_thread:
        yield mock_thread


def test_connect(socket_client, mock_fetchers):
    """Test client connection and initial events."""
    assert socket_client.is_connected('/ws/watchlist')
    
    received = socket_client.get_received('/ws/watchlist')
    assert len(received) == 2
    
    # Check for watchlist event
    watchlist_events = [msg for msg in received if msg['name'] == 'watchlist']
    assert len(watchlist_events) == 1
    assert watchlist_events[0]['args'][0] == {'tickers': []}
    
    # Check for market_status event
    market_status_events = [msg for msg in received if msg['name'] == 'market_status']
    assert len(market_status_events) == 1
    assert market_status_events[0]['args'][0]['is_open'] is True
    
    mock_fetchers['get_market_status'].assert_called_once()


def test_add_ticker(socket_client, mock_fetchers):
    """Test adding a ticker to the watchlist."""
    socket_client.get_received('/ws/watchlist') # Clear connect messages
    socket_client.emit('add_ticker', {'ticker': 'AAPL'}, namespace='/ws/watchlist')
    
    received = socket_client.get_received('/ws/watchlist')
    
    # We expect a 'quote' and a 'watchlist' update
    assert len(received) == 2
    
    quote_event = received[0]
    assert quote_event['name'] == 'quote'
    assert quote_event['args'][0]['data']['symbol'] == 'AAPL'
    
    watchlist_event = received[1]
    assert watchlist_event['name'] == 'watchlist'
    assert watchlist_event['args'][0]['tickers'] == ['AAPL']
    
    mock_fetchers['fetch_latest_quote'].assert_called_with('AAPL')


def test_remove_ticker(socket_client):
    """Test removing a ticker from the watchlist."""
    # First, add a ticker
    socket_client.emit('add_ticker', {'ticker': 'AAPL'}, namespace='/ws/watchlist')
    socket_client.get_received('/ws/watchlist') # Clear received messages

    # Now, remove it
    socket_client.emit('remove_ticker', {'ticker': 'AAPL'}, namespace='/ws/watchlist')
    received = socket_client.get_received('/ws/watchlist')
    
    assert len(received) == 1
    watchlist_event = received[0]
    assert watchlist_event['name'] == 'watchlist'
    assert watchlist_event['args'][0]['tickers'] == []


def test_disconnect(socket_client):
    """Test client disconnection."""
    # Add a ticker to populate the server-side watchlist for this client
    socket_client.emit('add_ticker', {'ticker': 'GOOG'}, namespace='/ws/watchlist')
    
    # Ensure the ticker is in the server's watchlist
    assert len(handlers.watchlists) == 1
    sid = list(handlers.watchlists.keys())[0]
    assert 'GOOG' in handlers.watchlists[sid]
    
    socket_client.disconnect(namespace='/ws/watchlist')
    
    # Check that the client's watchlist is removed from the server
    assert sid not in handlers.watchlists
