import base64
import matplotlib
import matplotlib.pyplot as plt
from io import BytesIO

matplotlib.use('Agg')
plt.style.use("dark_background")


def calculate_technical_indicators(history_df):
    """Calculates technical indicators from historical data."""
    indicators = {}
    if history_df is not None and not history_df.empty:
        indicators['ma_50'] = history_df['c'].rolling(
            50).mean().iloc[-1] if len(history_df) >= 50 else 'N/A'
        indicators['ma_200'] = history_df['c'].rolling(
            200).mean().iloc[-1] if len(history_df) >= 200 else 'N/A'

        if len(history_df) >= 14:
            delta = history_df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            if loss.iloc[-1] != 0:
                rs = gain.iloc[-1] / loss.iloc[-1]
                indicators['rsi'] = 100 - (100 / (1 + rs))
            else:
                # Or some other indicator of strong upward trend
                indicators['rsi'] = 100
        else:
            indicators['rsi'] = 'N/A'
    return indicators


def calculate_intrinsic_value(eps, growth_rate, current_price):
    """
    Calculates intrinsic value using a simplified Graham Formula.
    Assumes a fixed AAA corporate bond yield.
    """
    analysis = {
        'intrinsic_value': 'N/A',
        'price_difference': 'N/A',
        'percentage_difference': 'N/A',
        'recommendation': 'hold'
    }
    BOND_YIELD_AAA = 4.4  # This should ideally be fetched dynamically

    try:
        eps = float(eps) if eps is not None else None
        growth_rate = float(growth_rate) if growth_rate is not None else None


    except ValueError:
        eps = None
        growth_rate = None

    if eps is not None and eps > 0 and growth_rate is not None:
        # Ensure growth_rate is a percentage (e.g., 5 for 5%)
        intrinsic = (eps * (8.5 + 2 * growth_rate) *
                     BOND_YIELD_AAA) / BOND_YIELD_AAA
        analysis['intrinsic_value'] = round(intrinsic, 2)
        price_diff = analysis['intrinsic_value'] - current_price
        analysis['price_difference'] = round(price_diff, 2)
        analysis['percentage_difference'] = round(
            (price_diff / current_price) * 100, 2)
        if analysis['percentage_difference'] > 20:
            analysis['recommendation'] = 'buy'
        elif analysis['percentage_difference'] < -20:
            analysis['recommendation'] = 'sell'
    return analysis


def generate_chart_image(df, **kwargs):
    """Generates a base64-encoded chart image from a DataFrame."""
    if df is None or df.empty:
        return None

    fig, ax = plt.subplots()
    df.plot(x='timestamp', y='c', ax=ax, label='Price')

    if 'title' in kwargs:
        ax.set_title(kwargs['title'])
    if 'intrinsic_value' in kwargs and kwargs['intrinsic_value'] != 'N/A':
        ax.axhline(kwargs['intrinsic_value'], color='r',
                   linestyle='--', label='Intrinsic Value')

    ax.set_ylabel('Price')
    ax.set_xlabel('Date')
    ax.legend()

    buf = BytesIO()
    fig.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')
