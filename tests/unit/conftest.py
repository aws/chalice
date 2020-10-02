import json
import os

from pytest import fixture
from hypothesis import settings, HealthCheck

from chalice.app import Chalice

# From:
# http://hypothesis.readthedocs.io/en/latest/settings.html#settings-profiles
# On travis we'll have it run through more iterations.
from chalice.deploy import models

settings.register_profile(
    'ci', settings(max_examples=2000,
                   suppress_health_check=[HealthCheck.too_slow]),
)
# When you're developing locally, we'll only run a few examples
# to keep unit tests fast.  If you want to run more iterations
# locally just set HYPOTHESIS_PROFILE=ci.
settings.register_profile('dev', settings(max_examples=10))
settings.load_profile(os.getenv('HYPOTHESIS_PROFILE', 'dev'))

print("HYPOTHESIS PROFILE: %s" % os.environ.get("HYPOTHESIS_PROFILE"))


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
def sample_app_schedule_only():
    app = Chalice('schedule_only')

    @app.schedule('rate(5 minutes)')
    def cron(event):
        pass

    return app


@fixture
def sample_sqs_event_app():
    app = Chalice('sqs-event')

    @app.on_sqs_message(queue='myqueue')
    def handler(event):
        pass

    return app


@fixture
def sample_kinesis_event_app():
    app = Chalice('kinesis-event')

    @app.on_kinesis_record(stream='mystream')
    def handler(event):
        pass

    return app


@fixture
def sample_ddb_event_app():
    app = Chalice('ddb-event')

    @app.on_dynamodb_record(stream_arn='arn:aws:...:stream')
    def handler(event):
        pass

    return app


@fixture
def sample_app_lambda_only():
    app = Chalice('lambda_only')

    @app.lambda_function()
    def myfunction(event, context):
        pass

    return app


@fixture
def sample_websocket_app():
    app = Chalice('sample')

    @app.on_ws_connect()
    def connect():
        pass

    @app.on_ws_message()
    def message():
        pass

    @app.on_ws_disconnect()
    def disconnect():
        pass

    return app


@fixture
def sample_s3_event_app():
    app = Chalice('s3-event')

    @app.on_s3_event(bucket='mybucket')
    def handler(event):
        pass

    return app


@fixture
def sample_sns_event_app():
    app = Chalice('sns-event')

    @app.on_sns_message(topic='mytopic')
    def handler(event):
        pass

    return app


@fixture
def sample_cloudwatch_event_app():
    app = Chalice('cloudwatch-event')

    @app.on_cw_event({'source': {'source': ['aws.ec2']}})
    def foo(event):
        return event

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
            'multiValueQueryStringParameters': None,
            'body': "",
            'stageVariables': {},
        }
    return create_event_inner


@fixture
def create_websocket_event():
    def create_event_inner(route_key, body=''):
        return {
            'requestContext': {
                'routeKey': route_key,
                'domainName': 'abcd1234.execute-api.us-west-2.amazonaws.com',
                'stage': 'api',
                'connectionId': 'ABCD1234=',
                'apiId': 'abcd1234',
            },
            'body': body,
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
            'multiValueQueryStringParameters': None,
            'body': "",
            'stageVariables': {},
        }
    return create_empty_header_event_inner


@fixture
def create_event_with_body(create_event):
    def create_event_with_body_inner(body, uri='/', method='POST',
                                     content_type='application/json'):
        event = create_event(uri, method, {}, content_type)
        if content_type == 'application/json':
            body = json.dumps(body)
        event['body'] = body
        return event
    return create_event_with_body_inner


@fixture
def lambda_function():
    return models.LambdaFunction(
        resource_name='foo',
        function_name='app-stage-foo',
        deployment_package=None,
        environment_variables={},
        runtime='python2.7',
        handler='app.app',
        tags={},
        timeout=None,
        memory_size=None,
        role=models.PreCreatedIAMRole(role_arn='foobar'),
        security_group_ids=[],
        subnet_ids=[],
        layers=[],
        reserved_concurrency=None,
        xray=None,
    )
