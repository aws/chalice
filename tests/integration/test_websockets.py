import os
import sys
import json
import uuid
import threading
import shutil
import time

import pytest
import websocket

from chalice.cli.factory import CLIFactory
from chalice.utils import OSUtils, UI
from chalice.deploy.deployer import ChaliceDeploymentError
from chalice.config import DeployedResources


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(CURRENT_DIR, 'testwebsocketapp')
APP_FILE = os.path.join(PROJECT_DIR, 'app.py')
RANDOM_APP_NAME = 'smoketest-%s' % str(uuid.uuid4())[:13]


def retry(max_attempts, delay):
    def _create_wrapped_retry_function(function):
        def _wrapped_with_retry(*args, **kwargs):
            for _ in range(max_attempts):
                result = function(*args, **kwargs)
                if result is not None:
                    return result
                time.sleep(delay)
            raise RuntimeError("Exhausted max retries of %s for function: %s"
                               % (max_attempts, function))
        return _wrapped_with_retry
    return _create_wrapped_retry_function


def _inject_app_name(dirname):
    config_filename = os.path.join(dirname, '.chalice', 'config.json')
    with open(config_filename) as f:
        data = json.load(f)
    data['app_name'] = RANDOM_APP_NAME
    data['stages']['dev']['environment_variables']['APP_NAME'] = \
        RANDOM_APP_NAME
    with open(config_filename, 'w') as f:
        f.write(json.dumps(data, indent=2))


def _deploy_app(temp_dirname):
    factory = CLIFactory(temp_dirname)
    config = factory.create_config_obj(
        chalice_stage_name='dev',
        autogen_policy=True
    )
    session = factory.create_botocore_session()
    d = factory.create_default_deployer(session, config, UI())
    region = session.get_config_variable('region')
    deployed = _deploy_with_retries(d, config)
    application = SmokeTestApplication(
        region=region,
        deployed_values=deployed,
        stage_name='dev',
        app_name=RANDOM_APP_NAME,
        app_dir=temp_dirname,
    )
    return application


@retry(max_attempts=10, delay=20)
def _deploy_with_retries(deployer, config):
    try:
        deployed_stages = deployer.deploy(config, 'dev')
        return deployed_stages
    except ChaliceDeploymentError as e:
        # API Gateway aggressively throttles deployments.
        # If we run into this case, we just wait and try
        # again.
        error_code = _get_error_code_from_exception(e)
        if error_code != 'TooManyRequestsException':
            raise


def _get_error_code_from_exception(exception):
    error_response = getattr(exception.original_error, 'response', None)
    if error_response is None:
        return None
    return error_response.get('Error', {}).get('Code')


def _delete_app(application, temp_dirname):
    factory = CLIFactory(temp_dirname)
    config = factory.create_config_obj(
        chalice_stage_name='dev',
        autogen_policy=True
    )
    session = factory.create_botocore_session()
    d = factory.create_deletion_deployer(session, UI())
    _deploy_with_retries(d, config)


class SmokeTestApplication(object):

    # Number of seconds to wait after redeploy before starting
    # to poll for successful 200.
    _REDEPLOY_SLEEP = 20
    # Seconds to wait between poll attempts after redeploy.
    _POLLING_DELAY = 5

    def __init__(self, deployed_values, stage_name, app_name,
                 app_dir, region):
        self._deployed_resources = DeployedResources(deployed_values)
        self.stage_name = stage_name
        self.app_name = app_name
        # The name of the tmpdir where the app is copied.
        self.app_dir = app_dir
        self._has_redeployed = False
        self._region = region

    @property
    def websocket_api_id(self):
        return self._deployed_resources.resource_values(
            'websocket_api')['websocket_api_id']

    @property
    def websocket_connect_url(self):
        return (
            "wss://{websocket_api_id}.execute-api.{region}.amazonaws.com/"
            "{api_gateway_stage}".format(
                websocket_api_id=self.websocket_api_id,
                region=self._region,
                api_gateway_stage='api',
            )
        )

    @property
    def websocket_message_handler_arn(self):
        return self._deployed_resources.resource_values(
            'websocket_message')['lambda_arn']

    @property
    def region(self):
        return self._region

    def redeploy_once(self):
        # Redeploy the application once.  If a redeploy
        # has already happened, this function is a noop.
        if self._has_redeployed:
            return
        new_file = os.path.join(self.app_dir, 'app-redeploy.py')
        original_app_py = os.path.join(self.app_dir, 'app.py')
        shutil.move(original_app_py, original_app_py + '.bak')
        shutil.copy(new_file, original_app_py)
        self._clear_app_import()
        _deploy_app(self.app_dir)
        self._has_redeployed = True
        # Give it settling time before running more tests.
        time.sleep(self._REDEPLOY_SLEEP)

    def _clear_app_import(self):
        # Now that we're using `import` instead of `exec` we need
        # to clear out sys.modules in order to pick up the new
        # version of the app we just copied over.
        del sys.modules['app']


@pytest.fixture(scope='module')
def smoke_test_app_ws(tmpdir_factory):
    sys.modules.pop('app', None)
    # We can't use the monkeypatch fixture here because this is a module scope
    # fixture and monkeypatch is a function scoped fixture.
    os.environ['APP_NAME'] = RANDOM_APP_NAME
    tmpdir = str(tmpdir_factory.mktemp(RANDOM_APP_NAME))
    _create_dynamodb_table(RANDOM_APP_NAME, tmpdir)
    OSUtils().copytree(PROJECT_DIR, tmpdir)
    _inject_app_name(tmpdir)
    application = _deploy_app(tmpdir)
    yield application
    _delete_app(application, tmpdir)
    _delete_dynamodb_table(RANDOM_APP_NAME, tmpdir)
    os.environ.pop('APP_NAME')


def _create_dynamodb_table(table_name, temp_dirname):
    factory = CLIFactory(temp_dirname)
    session = factory.create_botocore_session()
    ddb = session.create_client('dynamodb')
    ddb.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {
                'AttributeName': 'entry',
                'AttributeType': 'N',
            },
        ],
        KeySchema=[
            {
                'AttributeName': 'entry',
                'KeyType': 'HASH',
            },
        ],
        ProvisionedThroughput={
            'ReadCapacityUnits': 5,
            'WriteCapacityUnits': 5,
        },
    )


def _delete_dynamodb_table(table_name, temp_dirname):
    factory = CLIFactory(temp_dirname)
    session = factory.create_botocore_session()
    ddb = session.create_client('dynamodb')
    ddb.delete_table(
        TableName=table_name,
    )


class Task(threading.Thread):
    def __init__(self, action, delay=0.05):
        threading.Thread.__init__(self)
        self._action = action
        self._done = threading.Event()
        self._delay = delay

    def run(self):
        while not self._done.is_set():
            self._action()
            time.sleep(self._delay)

    def stop(self):
        self._done.set()


def counter():
    """Generator of sequential increasing numbers"""
    yield
    count = 1
    while True:
        yield count
        count += 1


class CountingMessageSender(object):
    """Class to send values from a counter over a websocket."""
    def __init__(self, ws, counter):
        self._ws = ws
        self._counter = counter
        self._last_sent = None

    def send(self):
        value = next(self._counter)
        self._ws.send('%s' % value)
        self._last_sent = value

    @property
    def last_sent(self):
        return self._last_sent


def get_numbers_from_dynamodb(temp_dirname):
    """Get numbers from DynamoDB in the format written by testwebsocketapp.
    """
    factory = CLIFactory(temp_dirname)
    session = factory.create_botocore_session()
    ddb = session.create_client('dynamodb')
    paginator = ddb.get_paginator('scan')
    numbers = sorted([
        int(item['entry']['N'])
        for page in paginator.paginate(
                TableName=RANDOM_APP_NAME,
                ConsistentRead=True,
        )
        for item in page['Items']
    ])
    return numbers


def find_skips_in_seq(numbers):
    """Find non-sequential gaps in a sequence of numbers

    :type numbers: Iterable of ints
    :param numbers: Iterable to check for gaps

    :returns: List of tuples with the gaps in the format
        [(start_of_gap, end_of_gap, ...)]. If the list is empty then there
        are no gaps.
    """
    last = numbers[0] - 1
    skips = []
    for elem in numbers:
        if elem != last + 1:
            skips.append((last, elem))
        last = elem
    return skips


def test_websocket_redployment_does_not_lose_messages(smoke_test_app_ws):
    # This test is to check if one persistant connection is affected by an app
    # redeployment. A connection is made to the app, and a sequence of numbers
    # is sent over the socket and written to a DynamoDB table. The app is
    # redeployed in a seprate thread. After the redeployment we wait a
    # second to ensure more numbers have been sent.
    # All messages we send over the websocket, are echoed back. We record these
    # values to compare against the ones stored in dynamodb to ensure
    # everything can be sent and received. Finally we inspect the DynamoDB
    # table to ensure there are no gaps in the numbers we saw on the server
    # side, and that the first and last number we sent is also present.
    closure_values = {
        'echoed_values': [],
        'pending_echo': None,
        'last_sent': None,
    }

    def on_message(ws, message):
        message = int(message)
        closure_values['echoed_values'].append(message)
        # If the pending_echo value is a set, then we know that we are done
        # sending new values to the server. And we are waiting for some of
        # those values to be echoed back before we are done. We can delete
        # the number we just got from the server from our set of pending_echos.
        # Once that set is empty, we are no longer waiting and can close the
        # websocket.
        if closure_values['pending_echo'] is not None:
            closure_values['pending_echo'].remove(message)
            if not closure_values['pending_echo']:
                ws.close()

    def on_error(ws, error):
        ws.close()

    def on_open(ws):
        # Once the websocket is open, we construct a separate thread
        # to generate and send incrementing numerical messages at
        # a constant rate.
        counter_generator = counter()
        sender = CountingMessageSender(ws, counter_generator)
        ping_endpoint = Task(sender.send)
        ping_endpoint.start()
        smoke_test_app_ws.redeploy_once()
        time.sleep(1)
        ping_endpoint.stop()

        # Once we have stopped sending values and are ready to do
        # our assertions there are a few edge cases to consider. The
        # easiest case is that all values sent, have been echoed back. We can
        # just close the websocket.
        closure_values['last_sent'] = sender.last_sent
        closure_values['pending_echo'] = set(range(1, sender.last_sent + 1)) \
            - set(closure_values['echoed_values'])
        if not closure_values['pending_echo']:
            ws.close()
        # If there are still pending values in the set, then
        # we are still waiting for them to round trip. In this case the
        # on_message handler can close the websocket once it gets the last
        # value. There is stil an edge case where something went wrong and some
        # values are never going to get echoed back. To prevent this we set
        # a 5 second timeout to close the websocket while waiting for the
        # stragglers.
        else:
            threading.Timer(5.0, ws.close).start()

    ws = websocket.WebSocketApp(
        smoke_test_app_ws.websocket_connect_url,
        on_message=on_message,
        on_error=on_error,
        on_open=on_open,
    )
    # This will block until the websocket is closed.
    ws.run_forever()

    echoed = sorted(closure_values['echoed_values'])
    numbers = get_numbers_from_dynamodb(smoke_test_app_ws.app_dir)
    assert echoed == numbers
    assert 1 in numbers
    assert closure_values['last_sent'] in numbers
    skips = find_skips_in_seq(numbers)
    assert skips == []
