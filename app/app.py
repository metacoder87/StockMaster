import os
from dotenv import load_dotenv
from datetime import datetime, UTC
from flask import Flask, render_template, request, jsonify, make_response
from flask_socketio import SocketIO

# New imports from the new modules
from .data import fetchers
from .sockets import handlers as socket_handlers
from . import analysis

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*",
                    async_mode='threading', engineio_logger=True)

# Register the socket handlers
socket_handlers.register_socket_handlers(socketio, fetchers)

# Flask routes


@app.route('/')
def index():
    """Render the main application page."""
    print(f"Rendering index.html at {datetime.now(UTC).isoformat()}")
    return render_template('index.html')


@app.route('/all_stocks')
def all_stocks():
    return render_template('all_stocks.html')


@app.route('/api/assets')
def api_assets():
    try:
        # Validate and parse query parameters
        draw = int(request.args.get('draw', 1))
        start = int(request.args.get('start', 0))
        length = int(request.args.get('length', 100))
        search_value = request.args.get('search[value]', '').lower()
        order_column = int(request.args.get('order[0][column]', 0))
        order_dir = request.args.get('order[0][dir]', 'asc')

        # Ensure fetchers.all_assets is valid
        if not hasattr(fetchers, 'all_assets') or not isinstance(fetchers.all_assets, list):
            raise ValueError("Asset data is unavailable or invalid.")

        # Filter and sort assets
        filtered_assets = [
            asset for asset in fetchers.all_assets
            if search_value in asset.symbol.lower() or search_value in asset.name.lower()
        ]

        column_map = {0: 'symbol', 1: 'name', 2: 'exchange'}
        sort_key = column_map.get(order_column, 'symbol')
        filtered_assets.sort(key=lambda a: getattr(
            a, sort_key).lower(), reverse=(order_dir == 'desc'))

        # Paginate results
        paginated_assets = filtered_assets[start:start + length]
        data = [[f'<a href="/stock/{asset.symbol}">{asset.symbol}</a>',
                 asset.name, asset.exchange] for asset in paginated_assets]

        # Create response with headers
        response = make_response(jsonify({
            'draw': draw,
            'recordsTotal': len(fetchers.all_assets),
            'recordsFiltered': len(filtered_assets),
            'data': data
        }))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    except Exception as e:
        # Handle errors gracefully
        return jsonify({'error': str(e)}), 500


@app.route('/stock/<symbol>')
def stock_details(symbol):
    data = fetchers.get_stock_details(symbol)
    if not data:
        return "Stock not found or data not available.", 404

    history_df = data.get('history_df')

    # Perform analysis
    data.update(analysis.calculate_technical_indicators(history_df))
    
    # Use 'earningsGrowth' if available, otherwise default to a sensible 5%
    growth_rate = data.get('earnings_growth', 0.05)
    if growth_rate:
        growth_rate *= 100 # Convert to percentage for formula

    intrinsic_analysis = analysis.calculate_intrinsic_value(
        data.get('eps'),
        growth_rate,
        data.get('current_price')
    )
    data.update(intrinsic_analysis)

    # Generate charts
    data['history_chart'] = analysis.generate_chart_image(
        history_df, title=f'{symbol} 1-Year Price History')
    data['analysis_chart'] = analysis.generate_chart_image(
        history_df, title=f'{symbol} Price vs Intrinsic Value', intrinsic_value=data['intrinsic_value'])

    # Remove the DataFrame from the data passed to the template
    if 'history_df' in data:
        del data['history_df']

    try:
        rendered = render_template('stock_details.html', data=data)
        response = make_response(rendered)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-cache'
        return response
    except Exception as e:
        print(f"Error rendering template: {e}")
        import traceback
        traceback.print_exc()
        response = make_response("An internal error occurred.")
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        response.headers['Cache-Control'] = 'no-cache'
        return response, 500
