import json
from pytest import fixture

from chalice.app import Chalice


@fixture(autouse=True)
def ensure_no_local_config(no_local_config):
    pass


@fixture
def sample_app():
    app = Chalice('sample')

    @app.route('/')
    def foo():
        return {}

    return app


@fixture
def sample_app_with_auth():
    app = Chalice('sampleauth')

    @app.authorizer('myauth')
    def myauth(auth_request):
        pass

    @app.route('/', authorizer=myauth)
    def foo():
        return {}

    return app


@fixture
def create_event():
    def create_event_inner(uri, method, path, content_type='application/json'):
        return {
            'requestContext': {
                'httpMethod': method,
                'resourcePath': uri,
            },
            'headers': {
                'Content-Type': content_type,
            },
            'pathParameters': path,
            'queryStringParameters': {},
            'body': "",
            'stageVariables': {},
        }
    return create_event_inner


@fixture
def create_empty_header_event():
    def create_empty_header_event_inner(uri, method, path,
                                        content_type='application/json'):
        return {
            'requestContext': {
                'httpMethod': method,
                'resourcePath': uri,
            },
            'headers': None,
            'pathParameters': path,
            'queryStringParameters': {},
            'body': "",
            'stageVariables': {},
        }
    return create_empty_header_event_inner


@fixture
def create_event_with_body():
    def create_event_with_body_inner(body, uri='/', method='POST',
                                     content_type='application/json'):
        event = create_event()(uri, method, {}, content_type)
        if content_type == 'application/json':
            body = json.dumps(body)
        event['body'] = body
        return event
    return create_event_with_body_inner
