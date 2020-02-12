import datetime
import time
from contextlib import closing
from multiprocessing import Process, Queue

import botocore
import mock
import pytest
from botocore import stub
from botocore.stub import Stubber, StubResponseError, UnStubbedResponseError
from six import StringIO

from chalice import logs
from chalice.awsclient import TypedAWSClient


@pytest.fixture
def session():
    return botocore.session.get_session()


@pytest.fixture
def logs_client(session):
    client = session.create_client('logs')
    stubber = Stubber(client)
    yield client, stubber
    stubber.deactivate()


def message(log_message, log_stream_name='logStreamName'):
    return {
        'logStreamName': log_stream_name,
        'message': log_message,
    }


def test_can_retrieve_all_logs():
    client = mock.Mock(spec=TypedAWSClient)
    log_message = message('first')
    client.iter_log_events.return_value = [log_message]
    retriever = logs.LogRetriever(client, 'loggroup')
    messages = list(retriever.retrieve_logs())
    expected = log_message.copy()
    # We also inject a logShortId.
    expected['logShortId'] = 'logStreamName'
    assert messages == [expected]


def test_can_support_max_entries():
    client = mock.Mock(spec=TypedAWSClient)
    client.iter_log_events.return_value = [message('first'), message('second')]
    retriever = logs.LogRetriever(client, 'loggroup')
    messages = list(retriever.retrieve_logs(max_entries=1))
    assert len(messages) == 1
    assert messages[0]['message'] == 'first'


def test_can_exclude_lambda_messages():
    client = mock.Mock(spec=TypedAWSClient)
    client.iter_log_events.return_value = [
        message('START RequestId: id Version: $LATEST'),
        message('END RequestId: id'),
        message('REPORT RequestId: id Duration: 0.42 ms   '
                'Billed Duration: 100 ms     '
                'Memory Size: 128 MB Max Memory Used: 19 MB'),
        message('Not a lambda message'),
    ]
    retriever = logs.LogRetriever(client, 'loggroup')
    messages = list(retriever.retrieve_logs(include_lambda_messages=False))
    assert len(messages) == 1
    assert messages[0]['message'] == 'Not a lambda message'


def test_can_parse_short_id():
    log_message = message(
        'Log Message',
        '2017/04/28/[$LATEST]fc219a0d613b40e9b5c58e6b8fd2320c'
    )
    client = mock.Mock(spec=TypedAWSClient)
    client.iter_log_events.return_value = [log_message]
    retriever = logs.LogRetriever(client, 'loggroup')
    messages = list(retriever.retrieve_logs(include_lambda_messages=False))
    assert len(messages) == 1
    assert messages[0]['logShortId'] == 'fc219a'


def test_can_create_from_arn():
    retriever = logs.LogRetriever.create_from_lambda_arn(
        mock.sentinel.client,
        'arn:aws:lambda:us-east-1:123:function:my-function'
    )
    assert isinstance(retriever, logs.LogRetriever)


def test_can_display_logs():
    retriever = mock.Mock(spec=logs.LogRetriever)
    retriever.retrieve_logs.return_value = [
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'One'},
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'Two'},
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'Three'},
    ]
    stream = StringIO()
    logs.display_logs(retriever, max_entries=None,
                      include_lambda_messages=True,
                      stream=stream, follow=False)
    assert stream.getvalue().splitlines() == [
        'NOW shortId One',
        'NOW shortId Two',
        'NOW shortId Three',
    ]


def test_follow(session, logs_client):
    '''
    Test follow option

    - Test that follow doesn't display duplicates
    - Test that follow doesn't skip messages
    '''

    client, stubber = logs_client
    log_stream_name = 'loggroup'

    # retrieve_logs should yield logs with the same timestamp from separate
    # filter_log_events invocations granted that they don't have the same
    # eventId
    message1 = {
        'timestamp': 123,
        'ingestionTime': 123,
        'eventId': 'abc',
        'logStreamName': log_stream_name,
    }
    message2 = {
        'timestamp': 123,
        'ingestionTime': 123,
        'eventId': 'bcd',
        'logStreamName': log_stream_name,
    }

    params_1 = {
        'startTime': stub.ANY,
        'interleaved': stub.ANY,
        'logGroupName': stub.ANY,
    }
    response_1 = {'events': [dict(message1)]}

    params_2 = {
        'startTime': 123,
        'interleaved': stub.ANY,
        'logGroupName': stub.ANY,
    }
    response_2 = {'events': [dict(message1), dict(message2)]}

    stubber.add_response('filter_log_events', response_1, params_1)
    stubber.add_response('filter_log_events', response_2, params_2)
    stubber.activate()

    # retrieve_logs with follow=True will run indefinitely unless terminated,
    # so we run it in a seperate process.
    # Stubber will raise StubResponseError if the parameterss or response do
    # not match. We catch it here so we can pass it to the main thread.
    def proc(queue):
        awsclient = TypedAWSClient(session)
        awsclient._client_cache = {'logs': client}
        retriever = logs.LogRetriever(awsclient, 'loggroup')
        try:
            for log in retriever.retrieve_logs(follow=True):
                queue.put({'message': log})
        except UnStubbedResponseError:
            # It's possible that filter_log_events will be called more than
            # twice before the main thread can exit
            pass
        except StubResponseError as e:
            queue.put({'error': e})

    messages = []
    queue = Queue()
    try:
        with closing(Process(target=proc, args=(queue,))) as p:
            p.start()
            while len(messages) < 2:
                message = queue.get()
                if message.get('error') is not None:
                    raise message['error']
                messages.append(message['message'])
                time.sleep(1)
            p.terminate()
            p.join(2)
    except AttributeError:
        # Process doesn't have a close method in Python < 3.7
        pass

    def convert(message):
        # retreive_logs converts timestamps from ints to datetimes and adds a
        # logShortId field
        message = dict(message)
        message['logShortId'] = log_stream_name
        message['timestamp'] = datetime.datetime.fromtimestamp(
            message['timestamp'] / 1000.0
        )
        message['ingestionTime'] = datetime.datetime.fromtimestamp(
            message['ingestionTime'] / 1000.0
        )
        return message

    assert messages == [convert(message1), convert(message2)]
