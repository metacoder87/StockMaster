// main.js
console.log('Starting SocketIO connection...');
const socket = io('/ws/watchlist', {transports: ['websocket'], upgrade: false });
let watchlist = [];
const stockData = { };
const tradeData = { };

    // Connection management
    socket.on('connect', () => {
    console.log('Connected to SocketIO at', new Date().toISOString());
updateConnectionStatus(true);
document.getElementById('loading').style.display = 'none';
document.getElementById('content').style.display = 'block';
showInfo('Connected to real-time stock data stream');

// Request all current data
socket.emit('request_all_data');
    });
    
    socket.on('connect_error', (error) => {
    console.error('SocketIO connection error at', new Date().toISOString(), error);
showError(`Connection failed: ${error.message}`);
updateConnectionStatus(false);
document.getElementById('loading').style.display = 'none';
    });
    
    socket.on('disconnect', () => {
    console.log('Disconnected from SocketIO at', new Date().toISOString());
updateConnectionStatus(false);
showError('Disconnected from server');
    });

    // Data handlers
    socket.on('watchlist', (data) => {
    console.log('Received watchlist:', data);
watchlist = data.tickers || [];
renderWatchlist();
updateAlpacaTable();
    });
    
    socket.on('quote', (msg) => {
        const receivedTime = new Date();
console.log('Received quote at', receivedTime.toISOString(), msg);

if (msg.type === 'test') {
    console.log('Test message:', msg.data.message);
return;
        }

const data = msg.data;
if (!data.symbol || (data.bid_price === 0 && data.ask_price === 0)) {
    console.warn('Invalid quote data:', data);
return;
        }

stockData[data.symbol] = {
    ...data,
    receivedTime: receivedTime
        };

updateStockCard(data.symbol);
updateAlpacaTable();
    });
    
    socket.on('trade', (msg) => {
    console.log('Received trade data:', msg);
tradeData[msg.symbol] = msg.data;
updateAlpacaTable();

// Flash the row in the table
const row = document.querySelector(`#alpaca-row-${msg.symbol}`);
if (row) {
    row.classList.add('trade-flash');
            setTimeout(() => row.classList.remove('trade-flash'), 500);
        }
    });
    
    socket.on('market_status', (status) => {
    console.log('Market status:', status);
updateMarketStatus(status);
    });
    
    socket.on('error', (error) => {
    console.error('SocketIO error:', error);
showError(error.message || 'An error occurred');
    });

// UI Functions
function updateConnectionStatus(connected) {
        const status = document.getElementById('connection-status');
if (connected) {
    status.textContent = 'Connected';
status.className = 'connection-status status-connected';
        } else {
    status.textContent = 'Disconnected';
status.className = 'connection-status status-disconnected';
        }
    }

function updateMarketStatus(status) {
        const marketStatusEl = document.getElementById('market-status-text');
if (status.is_open) {
    marketStatusEl.innerHTML = `<span class="market-open">Market is OPEN</span><br>Closes at: ${status.next_close || 'N/A'}`;
        } else {
    marketStatusEl.innerHTML = `<span class="market-closed">Market is CLOSED</span><br>Opens at: ${status.next_open || 'N/A'}`;
        }
    }

function showError(message) {
        const errorEl = document.getElementById('error');
errorEl.textContent = message;
errorEl.style.display = 'block';
        setTimeout(() => {errorEl.style.display = 'none'; }, 5000);
    }

function showInfo(message) {
        const infoEl = document.getElementById('info');
infoEl.textContent = message;
infoEl.style.display = 'block';
        setTimeout(() => {infoEl.style.display = 'none'; }, 3000);
    }

function addTicker() {
        const input = document.getElementById('ticker-input');
const ticker = input.value.trim().toUpperCase();

if (!ticker) {
    showError('Please enter a ticker symbol');
return;
        }

if (watchlist.includes(ticker)) {
    showError('Ticker already in watchlist');
return;
        }

socket.emit('add_ticker', {ticker: ticker });
input.value = '';
showInfo(`Adding ${ticker} to watchlist...`);
    }

function removeTicker(ticker) {
    socket.emit('remove_ticker', { ticker: ticker });
delete stockData[ticker];
delete tradeData[ticker];
showInfo(`Removing ${ticker} from watchlist...`);
    }

function renderWatchlist() {
        const grid = document.getElementById('stock-grid');

if (watchlist.length === 0) {
    grid.innerHTML = '<div class="empty-state">No stocks in watchlist. Add some tickers to get started!</div>';
return;
        }
        
        grid.innerHTML = watchlist.map(ticker => `
<div class="stock-card" id="stock-${ticker}">
    <div class="stock-symbol">
        <span>${ticker}</span>
        <button class="remove-btn" onclick="removeTicker('${ticker}')">×</button>
    </div>
    <div class="price-info">
        <div class="price-item">
            <div class="price-label">Bid</div>
            <div class="price-value bid-price" id="bid-${ticker}">—</div>
        </div>
        <div class="price-item">
            <div class="price-label">Ask</div>
            <div class="price-value ask-price" id="ask-${ticker}">—</div>
        </div>
    </div>
    <div class="update-time" id="time-${ticker}">Waiting for data...</div>
</div>
`).join('');

        // Update existing data
        watchlist.forEach(ticker => {
            if (stockData[ticker]) {
    updateStockCard(ticker);
            }
        });
    }

function updateStockCard(ticker) {
        const data = stockData[ticker];
if (!data) return;

const bidEl = document.getElementById(`bid-${ticker}`);
const askEl = document.getElementById(`ask-${ticker}`);
const timeEl = document.getElementById(`time-${ticker}`);

if (bidEl) bidEl.textContent = `$${data.bid_price.toFixed(2)}`;
if (askEl) askEl.textContent = `$${data.ask_price.toFixed(2)}`;
if (timeEl) {
            const time = data.receivedTime || new Date();
let timeText = `Updated: ${time.toLocaleTimeString()}`;
if (data.market_hours === 'closed') {
    timeText += ' <span class="market-closed">(After Hours)</span>';
            }
timeEl.innerHTML = timeText;
        }

// Add flash effect
const card = document.getElementById(`stock-${ticker}`);
if (card) {
    card.style.boxShadow = '0 0 40px rgba(0, 255, 0, 0.5)';
            setTimeout(() => {
    card.style.boxShadow = '';
            }, 300);
        }
    }

function updateAlpacaTable() {
        const tbody = document.getElementById('alpaca-tbody');
const table = document.getElementById('alpaca-table');
const emptyState = document.getElementById('alpaca-empty');

if (watchlist.length === 0) {
    table.style.display = 'none';
emptyState.style.display = 'block';
return;
        }

table.style.display = 'table';
emptyState.style.display = 'none';
        
        tbody.innerHTML = watchlist.map(ticker => {
            const quote = stockData[ticker];
const trade = tradeData[ticker];

return `
<tr id="alpaca-row-${ticker}">
    <td style="color: #00ff00; font-weight: bold;">${ticker}</td>
    <td class="bid-price">${quote ? `$${quote.bid_price.toFixed(2)}` : '—'}</td>
    <td class="ask-price">${quote ? `$${quote.ask_price.toFixed(2)}` : '—'}</td>
    <td class="last-trade">${trade ? `$${trade.price.toFixed(2)}` : '—'}</td>
    <td>${trade ? trade.size : '—'}</td>
    <td style="font-size: 0.8em;">
        ${quote ? formatTimestamp(quote.timestamp || quote.receivedTime) : 'Waiting...'}
        ${quote && quote.market_hours === 'closed' ? '<br><span class="market-closed">(After Hours)</span>' : ''}
    </td>
</tr>
`;
        }).join('');
    }

function formatTimestamp(timestamp) {
        if (!timestamp) return 'N/A';
const date = new Date(timestamp);
return date.toLocaleTimeString();
    }

    // Keyboard shortcut
    document.getElementById('ticker-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
    addTicker();
        }
    });

    // Timeout for initial load
    setTimeout(() => {
        if (document.getElementById('loading').style.display !== 'none') {
    document.getElementById('loading').style.display = 'none';
document.getElementById('content').style.display = 'block';
showError('Connection timeout - check your connection');
        }
    }, 10000);

$(document).ready(function () {
    $('#stocksTable').DataTable({
        "processing": true,
        "serverSide": true,
        "ajax": "/api/assets",
        "pageLength": 100,
        "columns": [
            { "data": 0 },  // Symbol (clickable)
            { "data": 1 },  // Name
            { "data": 2 }   // Exchange
        ]
    });
});