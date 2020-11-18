import os
import json

import pytest

from chalice.test import Client, FunctionNotFoundError
from chalice import Response, BadRequestError, Chalice, Blueprint, AuthResponse


def test_can_make_http_request(sample_app):
    with Client(sample_app) as client:
        response = client.http.get('/')
        assert response.status_code == 200
        assert response.json_body == {}
        assert response.body == b'{}'


def test_can_pass_http_url(sample_app):

    @sample_app.route('/{name}')
    def hello(name):
        return {'hello': name}

    with Client(sample_app) as client:
        response = client.http.get('/james')
        assert response.json_body == {'hello': 'james'}


def test_make_other_http_methods_request(sample_app):

    @sample_app.route('/methods', methods=['POST', 'PUT', 'PATCH', 'OPTIONS',
                                           'DELETE', 'HEAD'])
    def method():
        return {'method': sample_app.current_request.method}

    with Client(sample_app) as client:
        assert client.http.post('/methods').json_body == {'method': 'POST'}
        assert client.http.put('/methods').json_body == {'method': 'PUT'}
        assert client.http.patch('/methods').json_body == {'method': 'PATCH'}
        assert client.http.delete('/methods').json_body == {'method': 'DELETE'}
        assert client.http.head('/methods').json_body == {'method': 'HEAD'}
        assert client.http.options('/methods').json_body == {
            'method': 'OPTIONS'}


def test_can_provide_http_headers(sample_app):
    @sample_app.route('/header')
    def headers():
        return {'value': sample_app.current_request.headers['x-my-header']}

    with Client(sample_app) as client:
        response = client.http.get('/header', headers={'x-my-header': 'foo'})
        assert response.json_body == {'value': 'foo'}


def test_can_return_error_message(sample_app):
    @sample_app.route('/error')
    def error():
        raise BadRequestError("bad request")

    with Client(sample_app) as client:
        response = client.http.get('/error')
        assert response.status_code == 400
        assert response.json_body['Code'] == 'BadRequestError'
        assert 'bad request' in response.json_body['Message']


def test_can_return_binary_data(sample_app):
    @sample_app.route('/bin-echo')
    def bin_echo():
        raw_request_body = sample_app.current_request.raw_body
        return Response(body=raw_request_body,
                        status_code=200,
                        headers={'Content-Type': 'application/octet-stream'})

    with Client(sample_app) as client:
        random_bytes = os.urandom(16)
        response = client.http.get(
            '/bin-echo', body=random_bytes,
            headers={'Accept': 'application/octet-stream'})
        assert response.body == random_bytes
        assert response.json_body is None


def test_can_access_env_vars_in_rest_api(sample_app, tmpdir):
    fake_config = {
        "version": "2.0",
        "app_name": "testenv",
        "stages": {
            "prod": {
                "api_gateway_stage": "api",
                "environment_variables": {
                    "MY_ENV_VAR": "TOP LEVEL"
                },
            }
        }
    }
    tmpdir.mkdir('.chalice').join('config.json').write(
        json.dumps(fake_config).encode('utf-8'))
    project_dir = str(tmpdir)
    os.environ.pop('MY_ENV_VAR', None)

    @sample_app.route('/env')
    def env_vars():
        return {'value': os.environ.get('MY_ENV_VAR')}

    with Client(sample_app, project_dir=project_dir,
                stage_name='prod') as client:
        response = client.http.get('/env')
        assert response.json_body == {'value': 'TOP LEVEL'}


def test_authorizers_return_http_response_on_error(sample_app):
    @sample_app.authorizer()
    def myauth(event):
        if event.token == 'allow':
            return AuthResponse(['*'], principal_id='id')
        return AuthResponse([], principal_id='noone')

    @sample_app.route('/needs-auth', authorizer=myauth)
    def needs_auth():
        return {'success': True}

    with Client(sample_app) as client:
        response = client.http.get('/needs-auth',
                                   headers={'Authorization': 'deny'})
        assert response.status_code == 403
        assert client.http.get('/needs-auth').status_code == 401


def test_can_test_authorizers(sample_app):
    @sample_app.authorizer()
    def myauth(event):
        if event.token == 'allow':
            return AuthResponse(['*'], principal_id='id')

    @sample_app.route('/needs-auth', authorizer=myauth)
    def needs_auth():
        return {'success': True}

    with Client(sample_app) as client:
        response = client.http.get('/needs-auth',
                                   headers={'Authorization': 'allow'})
        assert response.json_body == {'success': True}


# Tests for pure lambda and event handlers.

def test_can_invoke_pure_lambda_function():
    app = Chalice('lambda-only')

    @app.lambda_function()
    def foo(event, context):
        return {'event': event}

    with Client(app) as client:
        response = client.lambda_.invoke('foo', {'hello': 'world'})
        assert response.payload == {'event': {'hello': 'world'}}


def test_error_if_function_does_not_exist():
    app = Chalice('lambda-only')

    with Client(app) as client:
        with pytest.raises(FunctionNotFoundError):
            client.lambda_.invoke('unknown-function', {})


def test_payload_not_required_for_invoke():
    app = Chalice('lambda-only')

    @app.lambda_function()
    def foo(event, context):
        return {'event': event}

    with Client(app) as client:
        response = client.lambda_.invoke('foo')
        assert response.payload == {'event': {}}


def test_can_access_environment_variables_in_function(tmpdir):
    app = Chalice('lambda-only')
    fake_config = {
        "version": "2.0",
        "app_name": "testenv",
        "stages": {
            "prod": {
                "api_gateway_stage": "api",
                "environment_variables": {
                    "MY_ENV_VAR": "TOP LEVEL"
                },
                "lambda_functions": {
                    "bar": {
                        "environment_variables": {
                            "MY_ENV_VAR": "OVERRIDE"
                        }
                    }
                }
            }
        }
    }
    tmpdir.mkdir('.chalice').join('config.json').write(
        json.dumps(fake_config).encode('utf-8'))
    project_dir = str(tmpdir)
    os.environ.pop('MY_ENV_VAR', None)

    @app.lambda_function()
    def foo(event, context):
        return {'myvalue': os.environ.get('MY_ENV_VAR')}

    @app.lambda_function()
    def bar(event, context):
        return {'myvalue': os.environ.get('MY_ENV_VAR')}

    with Client(app, project_dir=project_dir, stage_name='prod') as client:
        assert client.lambda_.invoke('foo', {}).payload == {
            'myvalue': 'TOP LEVEL'
        }
        assert client.lambda_.invoke('bar', {}).payload == {
            'myvalue': 'OVERRIDE'
        }
    assert 'MY_ENV_VAR' not in os.environ


def test_can_invoke_event_handler():
    app = Chalice('lambda-only')

    @app.on_sns_message(topic='mytopic')
    def foo(event):
        return {'message': event.message,
                'subject': event.subject}

    with Client(app) as client:
        event = client.events.generate_sns_event(message='my message',
                                                 subject='hello')
        response = client.lambda_.invoke('foo', event)
        assert response.payload == {'message': 'my message',
                                    'subject': 'hello'}


def test_can_generate_s3_event():
    app = Chalice('lambda-only')

    @app.on_s3_event(bucket='mybucket')
    def foo(event):
        return {'bucket': event.bucket,
                'key': event.key}

    with Client(app) as client:
        event = client.events.generate_s3_event(
            bucket='mybucket', key='mykey')
        response = client.lambda_.invoke('foo', event)
        assert response.payload == {'bucket': 'mybucket',
                                    'key': 'mykey'}


def test_can_generate_sqs_event():
    app = Chalice('lambda-only')

    @app.on_sqs_message(queue='myqueue')
    def foo(event):
        return [record.body for record in event]

    with Client(app) as client:
        event = client.events.generate_sqs_event(
            message_bodies=['foo', 'bar', 'baz'])
        response = client.lambda_.invoke('foo', event)
        assert response.payload == ['foo', 'bar', 'baz']


def test_can_generate_cloudwatch_event():
    app = Chalice('lambda-only')

    @app.on_cw_event({'source': ['aws.ec2']})
    def foo(event):
        return {'detail': event.detail}

    with Client(app) as client:
        event = client.events.generate_cw_event(
            source='aws.ec2', detail_type='EC2 State-change',
            resources=['arn:aws:ec2:...:instance/i-abc'],
            detail={'instance-id': 'i-1234', 'state': 'pending'}
        )
        response = client.lambda_.invoke('foo', event)
        assert response.payload == {'detail': {'instance-id': 'i-1234',
                                               'state': 'pending'}}


def test_can_generate_kinesis_event():
    app = Chalice('kinesis')

    @app.on_kinesis_record(stream='mystream')
    def foo(event):
        return [record.data for record in event]

    with Client(app) as client:
        event = client.events.generate_kinesis_event(
            message_bodies=[b'foo', b'bar', b'baz'])
        response = client.lambda_.invoke('foo', event)
        assert response.payload == [b'foo', b'bar', b'baz']


def test_can_mix_pure_lambda_and_event_handlers():
    app = Chalice('lambda-only')

    @app.on_sns_message(topic='mytopic')
    def foo(event):
        return {'message': event.message,
                'subject': event.subject}

    @app.lambda_function()
    def bar(event, context):
        return {'event': event}

    @app.route('/')
    def index():
        return {'hello': 'restapi'}

    with Client(app) as client:
        assert client.lambda_.invoke(
            'foo',
            client.events.generate_sns_event(
                message='my message', subject='hello')
        ).payload == {'message': 'my message', 'subject': 'hello'}
        assert client.lambda_.invoke(
            'bar', {'hello': 'world'}
        ).payload == {'event': {'hello': 'world'}}
        assert client.http.get('/').json_body == {'hello': 'restapi'}


def test_can_invoke_handler_from_blueprint():
    bp = Blueprint('testblueprint')

    @bp.lambda_function()
    def my_foo(event, context):
        return {'event': event}

    app = Chalice('myapp')
    app.register_blueprint(bp)

    with Client(app) as client:
        response = client.lambda_.invoke('my_foo', {'hello': 'world'})
        assert response.payload == {'event': {'hello': 'world'}}


def test_can_invoke_handler_with_blueprint_prefix():
    bp = Blueprint('testblueprint')

    @bp.lambda_function()
    def my_foo(event, context):
        return {'event': event}

    app = Chalice('myapp')
    app.register_blueprint(bp, name_prefix='bp_prefix_')

    with Client(app) as client:
        response = client.lambda_.invoke('bp_prefix_my_foo',
                                         {'hello': 'world'})
        assert response.payload == {'event': {'hello': 'world'}}


def test_lambda_function_with_custom_name():
    app = Chalice('lambda-only')

    @app.lambda_function(name='my-custom-name')
    def foo(event, context):
        return {'event': event}

    with Client(app) as client:
        response = client.lambda_.invoke('my-custom-name', {'hello': 'world'})
        assert response.payload == {'event': {'hello': 'world'}}
