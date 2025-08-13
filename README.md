# Real-Time Stock Watchlist with Alpaca API Integration

## Overview

This is an enhanced version of the stock streamer application that now provides real-time stock data even when the market is closed. The application uses Alpaca Markets API to fetch the most recent quotes and trade data, ensuring users always have access to the latest available information.

## New Features

### 1. **After-Hours Data Support**
- The application now fetches and displays the most recent stock data even when the market is closed
- Uses Alpaca REST API to retrieve latest quotes when WebSocket stream is unavailable
- Clearly indicates when data is from after-hours trading

### 2. **Market Status Indicator**
- Real-time market status display showing whether the market is open or closed
- Shows next market open/close times in Eastern Time
- Visual indicators for market status throughout the UI

### 3. **Alpaca Market Data Section**
- New dedicated section displaying comprehensive market data from Alpaca
- Shows bid/ask prices, last trade price, trade size, and timestamps
- Visual flash animation when new trade data is received
- Table format for easy comparison of multiple stocks

### 4. **Enhanced Data Caching**
- Server-side caching of latest stock data
- Immediate data display for newly added tickers
- Persistent data availability even during connection issues

### 5. **Automatic Quote Refresh**
- Periodic refresh of all watched stocks (every 30 seconds when market is closed, 60 seconds when open)
- Ensures data is always up-to-date
- Seamless integration with real-time WebSocket updates

## Technical Improvements

### Backend (app.py)
- **Alpaca REST API Integration**: Added `alpaca_trade_api` client for fetching latest quotes and trades
- **Market Status Checking**: Implemented functions to check market hours and status
- **Data Caching**: Thread-safe caching mechanism for latest stock data
- **Enhanced Documentation**: Added comprehensive docstrings for all major functions
- **Improved Error Handling**: Better error handling for API calls and WebSocket connections

### Frontend (index.html)
- **New UI Components**: Added Alpaca data section with responsive table layout
- **Market Status Display**: Visual indicators for market open/closed status
- **Enhanced Animations**: Trade flash animations and improved visual feedback
- **Responsive Design**: Maintained the dark neon theme while adding new features

## API Integration Details

### Alpaca REST API Endpoints Used:
- `get_latest_quote(symbol)`: Fetches the most recent quote for a symbol
- `get_latest_trades(symbols)`: Fetches latest trade data for multiple symbols
- `get_clock()`: Gets current market status and hours

### WebSocket Integration:
- Maintains real-time connection when market is open
- Falls back to REST API data when WebSocket data is unavailable
- Seamless switching between data sources

## Configuration

The application requires the following environment variables:
- `APCA_API_KEY_ID`: Your Alpaca API key ID
- `APCA_API_SECRET_KEY`: Your Alpaca API secret key

## Usage

1. Start the application:
   ```bash
   python app.py
   ```

2. Open your browser to `http://localhost:5000`

3. Add stock symbols to your watchlist (up to 30 symbols)

4. View real-time data during market hours and latest available data after hours

## Key Functions Documentation

### Backend Functions

#### `fetch_latest_quote(symbol)`
Fetches the latest quote for a given stock symbol using Alpaca REST API.
- **Parameters**: symbol (str) - The stock symbol
- **Returns**: dict with bid/ask prices, sizes, and timestamp
- **Note**: Works even when market is closed

#### `fetch_latest_trades(symbols)`
Fetches the latest trades for multiple symbols.
- **Parameters**: symbols (list) - List of stock symbols
- **Returns**: dict mapping symbols to trade data

#### `is_market_open()`
Checks if the US stock market is currently open.
- **Returns**: boolean indicating market status

#### `get_market_status()`
Gets detailed market status information including next open/close times.
- **Returns**: dict with market status and schedule

#### `refresh_all_quotes()`
Periodically refreshes quotes for all watched symbols.
- Runs in a separate thread
- Adjusts refresh rate based on market status

### Frontend Functions

#### `updateMarketStatus(status)`
Updates the market status display in the UI.

#### `updateAlpacaTable()`
Updates the Alpaca data table with latest quote and trade information.

## Dependencies

- Flask & Flask-SocketIO for web framework
- alpaca-trade-api for market data
- websocket-client for real-time streaming
- pytz for timezone handling
- Other dependencies listed in requirements.txt

## Notes

- The application uses the paper trading endpoint by default
- Data is delayed by 15 minutes for free tier users
- Maximum of 30 stocks can be tracked simultaneously
- All times are displayed in Eastern Time (ET)
