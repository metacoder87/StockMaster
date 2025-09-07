import pytest
from app.app import app, socketio
from app.auth import User, users
from werkzeug.security import generate_password_hash

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test_secret_key'
    app.config['APCA_API_KEY_ID'] = 'test_key'
    app.config['APCA_API_SECRET_KEY'] = 'test_secret'
    with app.test_client() as client:
        yield client


@pytest.fixture
def socketio_client():
    return socketio.test_client(app, namespace='/ws/watchlist')


def test_index_route(client):
    # Create a test user
    hashed_password = generate_password_hash('testpassword', method='pbkdf2:sha256')
    test_user = User(id=1, username='testuser', password=hashed_password)
    users[1] = test_user

    # Log in the user
    client.post('/auth/login', data=dict(
        username='testuser',
        password='testpassword'
    ), follow_redirects=True)

    # Access the index route
    response = client.get('/')
    assert response.status_code == 200
    assert b'Real-Time Stock Info' in response.data


def test_socketio_connect(socketio_client):
    assert socketio_client.is_connected('/ws/watchlist')
