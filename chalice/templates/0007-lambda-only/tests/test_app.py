from chalice.test import Client
from app import app


def test_index():
    with Client(app) as client:
        response = client.lambda_.invoke('first_function', {})
        assert response.payload == {'hello': 'world'}
