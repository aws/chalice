import mock

from chalice import logs
from chalice.awsclient import TypedAWSClient
from six import StringIO


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
                      stream=stream)
    assert stream.getvalue().splitlines() == [
        'NOW shortId One',
        'NOW shortId Two',
        'NOW shortId Three',
    ]
