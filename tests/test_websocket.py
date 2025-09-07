import pytest
from app.app import app, socketio


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['APCA_API_KEY_ID'] = 'test_key'
    app.config['APCA_API_SECRET_KEY'] = 'test_secret'
    with app.test_client() as client:
        yield client


@pytest.fixture
def socketio_client():
    return socketio.test_client(app, namespace='/ws/watchlist')


def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Real-Time Stock Watchlist' in response.data


def test_socketio_connect(socketio_client):
    assert socketio_client.is_connected('/ws/watchlist')
