# -*- coding: utf-8 -*-

import pytest

import json
import sys

import chalice
from chalice import Chalice, Response
from chalice.testutils import TestHTTPClient


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

    @app.route('/any_response_code/{code}')
    def any_response(code):
        # type: (str) -> Response
        return Response(
            body=json.dumps({'hello': 'world'}),
            status_code=int(code),
            headers={'Content-Type': 'application/json'},
        )

    @app.route('/exception/{exception_class}')
    def exception(exception_class):
        # type: (str) -> None
        raise getattr(chalice, exception_class)

    yield app


@pytest.fixture
def sample_client(sample_app):
    # type: (Chalice) -> TestHTTPClient
    return TestHTTPClient(sample_app)


class TestTestHTTPClient:
    @pytest.mark.parametrize('method',  (
        'get', 'head', 'post', 'put',
        'delete', 'trace', 'patch', 'link', 'unlink',
    ))
    def test_json_response(self, method, sample_client):
        response = getattr(sample_client, method)('/')
        assert response.status_code == 200
        assert response.json == {'hello': 'world'}

    @pytest.mark.parametrize('status_code', [
        '100', '200', '300', '400', '500',
    ])
    def test_any_response_with_response_class(
            self, sample_client, status_code):
        # type: (TestHTTPClient, str) -> None
        response = sample_client.get(
            '/any_response_code/{}'.format(status_code))
        assert response.status_code == int(status_code)

    @pytest.mark.parametrize(('exception_class', 'expected_response_status'), (
        ('BadRequestError', 400),
        ('UnauthorizedError', 401),
        ('NotFoundError', 404),
        ('ConflictError', 409),
        ('UnprocessableEntityError', 422),
        ('TooManyRequestsError', 429),
        ('ChaliceViewError', 500),
    ))
    def test_abnormal_response(
            self, sample_client, exception_class, expected_response_status):
        # type: (TestHTTPClient, str, int) -> None
        response = sample_client.get('/exception/{}'.format(exception_class))
        assert response.status_code == expected_response_status
        assert response.json['Code'] == exception_class

    def test_unexpected_exception(self, sample_client):
        # type: (TestHTTPClient) -> None
        response = sample_client.get('/exception/{}'.format('RuntimeError'))
        assert response.status_code == 500
        assert response.json['Code'] == 'InternalServerError'

    def test_invalid_method(self, sample_client):
        # type: (TestHTTPClient) -> None
        with pytest.raises(AttributeError, match=r' object has no attribute '):
            sample_client.invalid_method('/')

    def test_string_response_dont_have_json_attribute(self, sample_client):
        # type: (TestHTTPClient) -> None
        response = sample_client.get('/string')
        assert not hasattr(response, 'json')


class TestCustomContext:
    def test_check_default_context(self, sample_client):
        # type: (TestHTTPClient) -> None
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
        # type: (TestHTTPClient) -> None
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
