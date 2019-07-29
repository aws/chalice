# -*- coding: utf-8 -*-

import pytest

from chalice import Chalice
from chalice.local.internal import RequestHandler


@pytest.fixture
def sample_app():
    # type: () -> Iterator[Union[Iterator, Iterator[Chalice]]]
    app = Chalice(__name__)

    @app.route(
        '/',
        methods=(
            'GET', 'HEAD', 'POST', 'OPTIONS', 'PUT',
            'DELETE', 'TRACE', 'PATCH', 'LINK', 'UNLINK'
        ),
    )
    def index():
        # type: () -> Dict[str, str]
        return {'hello': 'world'}

    @app.route('/context')
    def context():
        # type: () -> Dict[str, Dict[str, Any]]
        context = app.current_request.context
        return {'context': context}

    @app.route('/string')
    def string():
        # type: () -> str
        return 'Foo'

    yield app


@pytest.fixture
def sample_client(sample_app):
    # type: (Chalice) -> RequestHandler
    return RequestHandler(sample_app)


class TestRequestHandler:
    @pytest.mark.parametrize('method',  (
        'get', 'head', 'post', 'put',
        'delete', 'trace', 'patch', 'link', 'unlink',
    ))
    def test_json_response(self, method, sample_client):
        response = getattr(sample_client, method)('/')
        assert response.status_code == 200
        assert response.json == {'hello': 'world'}

    def test_invalid_method(self, sample_client):
        # type: (RequestHandler) -> None
        with pytest.raises(AttributeError, match=r' object has no attribute '):
            sample_client.invalid_method('/')

    def test_string_response_dont_have_json_attribute(self, sample_client):
        # type: (RequestHandler) -> None
        response = sample_client.get('/string')
        assert not hasattr(response, 'json')


class TestCustomContext:
    def test_check_default_context(self, sample_client):
        # type: (RequestHandler) -> None
        response = sample_client.get('/context')
        assert response.json == {
            'context': {
                'httpMethod': 'GET',
                'identity': {'sourceIp': '127.0.0.1'},
                'path': '/context',
                'resourcePath': '/context',
            }
        }

    def test_custom_context(self, sample_client):
        # type: (RequestHandler) -> None
        sample_client.custom_context = {
            'authorizer': {'claims': {}},
        }

        response = sample_client.get('/context')
        response_context = response.json['context']
        assert 'httpMethod' in response_context
        assert 'identity' in response_context
        assert 'path' in response_context
        assert 'resourcePath' in response_context
        assert 'authorizer' in response_context
