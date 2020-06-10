import time
import mock
from datetime import datetime, timedelta

from chalice import logs
from chalice.awsclient import TypedAWSClient
from six import StringIO


NO_OPTIONS = logs.LogRetrieveOptions()


def message(log_message, log_stream_name='logStreamName'):
    return {
        'logStreamName': log_stream_name,
        'message': log_message,
    }


def test_can_convert_since_to_start_time():
    options = logs.LogRetrieveOptions.create(
        follow=True, since='2020-01-01T00:00:00',
        include_lambda_messages=False)
    assert options.max_entries is None
    assert options.start_time == datetime(2020, 1, 1, 0, 0, 0)
    assert not options.include_lambda_messages


def test_can_retrieve_all_logs():
    client = mock.Mock(spec=TypedAWSClient)
    log_message = message('first')
    client.iter_log_events.return_value = [log_message]
    retriever = logs.LogRetriever(client, 'loggroup')
    messages = list(retriever.retrieve_logs(NO_OPTIONS))
    expected = log_message.copy()
    # We also inject a logShortId.
    expected['logShortId'] = 'logStreamName'
    assert messages == [expected]


def test_can_support_max_entries():
    client = mock.Mock(spec=TypedAWSClient)
    client.iter_log_events.return_value = [message('first'), message('second')]
    retriever = logs.LogRetriever(client, 'loggroup')
    messages = list(
        retriever.retrieve_logs(logs.LogRetrieveOptions(max_entries=1)))
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
    messages = list(retriever.retrieve_logs(
        logs.LogRetrieveOptions(include_lambda_messages=False)))
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
    messages = list(retriever.retrieve_logs(
        logs.LogRetrieveOptions(include_lambda_messages=False)))
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
    logs.display_logs(retriever, retrieve_options=NO_OPTIONS, stream=stream)
    assert stream.getvalue().splitlines() == [
        'NOW shortId One',
        'NOW shortId Two',
        'NOW shortId Three',
    ]


def test_can_iterate_through_all_log_events():
    client = mock.Mock(spec=TypedAWSClient)
    client.iter_log_events.return_value = [
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'One'},
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'Two'},
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'Three'},
    ]
    event_gen = logs.LogEventGenerator(client)
    assert list(event_gen.iter_log_events(
        log_group_name='mygroup', options=NO_OPTIONS)) == [
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'One'},
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'Two'},
        {'timestamp': 'NOW', 'logShortId': 'shortId', 'message': 'Three'},
    ]


def test_can_follow_log_events():
    sleep = mock.Mock(spec=time.sleep)
    client = mock.Mock(spec=TypedAWSClient)
    client.filter_log_events.side_effect = [
        # First page of results has nextToken indicating there's
        # more results.
        {'events': [{'eventId': '1', 'timestamp': 1},
                    {'eventId': '2', 'timestamp': 2},
                    {'eventId': '3', 'timestamp': 3}],
         'nextToken': 'nextToken1'},
        # Second page with no more results, also note the
        # timestamps are out of order.
        {'events': [{'eventId': '4', 'timestamp': 4},
                    {'eventId': '6', 'timestamp': 6},
                    {'eventId': '5', 'timestamp': 5}]},
        # We then poll again with no new results for timestamp=6.
        {'events': [{'eventId': '6', 'timestamp': 6}]},
        # And now we get new results.
        {'events': [{'eventId': '6', 'timestamp': 6},
                    # Same timestamp we're querying (6) but a new event.
                    {'eventId': '6NEW', 'timestamp': 6},
                    {'eventId': '7', 'timestamp': 7},
                    {'eventId': '8', 'timestamp': 8}]},
        KeyboardInterrupt(),
    ]
    event_gen = logs.FollowLogEventGenerator(client, sleep)
    options = logs.LogRetrieveOptions(start_time=1)
    assert list(event_gen.iter_log_events(
        log_group_name='mygroup', options=options)) == [
        {'eventId': '1', 'timestamp': 1},
        {'eventId': '2', 'timestamp': 2},
        {'eventId': '3', 'timestamp': 3},
        {'eventId': '4', 'timestamp': 4},
        # Note we don't try to sort these entries.
        {'eventId': '6', 'timestamp': 6},
        {'eventId': '5', 'timestamp': 5},
        {'eventId': '6NEW', 'timestamp': 6},
        {'eventId': '7', 'timestamp': 7},
        {'eventId': '8', 'timestamp': 8},
    ]
    assert client.filter_log_events.call_args_list == [
        mock.call(log_group_name='mygroup', start_time=1),
        mock.call(log_group_name='mygroup', start_time=1,
                  next_token='nextToken1'),
        mock.call(log_group_name='mygroup', start_time=6),
        mock.call(log_group_name='mygroup', start_time=6),
        mock.call(log_group_name='mygroup', start_time=8),
    ]


def test_follow_logs_initially_empty():
    sleep = mock.Mock(spec=time.sleep)
    client = mock.Mock(spec=TypedAWSClient)
    client.filter_log_events.side_effect = [
        {'events': []},
        {'events': []},
        {'events': [{'eventId': '1', 'timestamp': 1},
                    {'eventId': '2', 'timestamp': 2},
                    {'eventId': '3', 'timestamp': 3}]},
        KeyboardInterrupt(),
    ]
    event_gen = logs.FollowLogEventGenerator(client, sleep)
    assert list(event_gen.iter_log_events(
        log_group_name='mygroup', options=NO_OPTIONS)) == [
        {'eventId': '1', 'timestamp': 1},
        {'eventId': '2', 'timestamp': 2},
        {'eventId': '3', 'timestamp': 3},
    ]


def test_follow_logs_single_pages_only():
    sleep = mock.Mock(spec=time.sleep)
    client = mock.Mock(spec=TypedAWSClient)
    client.filter_log_events.side_effect = [
        {'events': [{'eventId': '1', 'timestamp': 1}]},
        {'events': [{'eventId': '2', 'timestamp': 2}]},
        {'events': [{'eventId': '3', 'timestamp': 3}]},
        KeyboardInterrupt(),
    ]
    event_gen = logs.FollowLogEventGenerator(client, sleep)
    assert list(event_gen.iter_log_events(
        log_group_name='mygroup', options=NO_OPTIONS)) == [
        {'eventId': '1', 'timestamp': 1},
        {'eventId': '2', 'timestamp': 2},
        {'eventId': '3', 'timestamp': 3},
    ]


def test_follow_logs_last_page_empty():
    sleep = mock.Mock(spec=time.sleep)
    client = mock.Mock(spec=TypedAWSClient)
    client.filter_log_events.side_effect = [
        {'events': [{'eventId': '1', 'timestamp': 1},
                    {'eventId': '2', 'timestamp': 2},
                    {'eventId': '3', 'timestamp': 3}],
         'nextToken': 'nextToken1'},
        {'events': [{'eventId': '4', 'timestamp': 4},
                    {'eventId': '6', 'timestamp': 6},
                    {'eventId': '5', 'timestamp': 5}],
         'nextToken': 'nextToken2'},
        # You can sometimes get a next token but with no events.
        {'events': [], 'nextToken': 'nextToken3'},
        {'events': []},
        {'events': [{'eventId': '7', 'timestamp': 7}]},
        KeyboardInterrupt(),
    ]
    event_gen = logs.FollowLogEventGenerator(client, sleep)
    options = logs.LogRetrieveOptions(start_time=1)
    assert list(event_gen.iter_log_events(
        log_group_name='mygroup', options=options)) == [
        {'eventId': '1', 'timestamp': 1},
        {'eventId': '2', 'timestamp': 2},
        {'eventId': '3', 'timestamp': 3},
        {'eventId': '4', 'timestamp': 4},
        {'eventId': '6', 'timestamp': 6},
        {'eventId': '5', 'timestamp': 5},
        {'eventId': '7', 'timestamp': 7},
    ]
    assert client.filter_log_events.call_args_list == [
        mock.call(log_group_name='mygroup', start_time=1),
        mock.call(log_group_name='mygroup', start_time=1,
                  next_token='nextToken1'),
        mock.call(log_group_name='mygroup', start_time=1,
                  next_token='nextToken2'),
        mock.call(log_group_name='mygroup', start_time=1,
                  next_token='nextToken3'),
        mock.call(log_group_name='mygroup', start_time=6),
        mock.call(log_group_name='mygroup', start_time=7),
    ]


def test_follow_logs_all_pages_empty_with_pagination():
    sleep = mock.Mock(spec=time.sleep)
    client = mock.Mock(spec=TypedAWSClient)
    client.filter_log_events.side_effect = [
        {'events': [], 'nextToken': 'nextToken1'},
        {'events': [], 'nextToken': 'nextToken2'},
        {'events': [], 'nextToken': 'nextToken3'},
        {'events': []},
        KeyboardInterrupt(),
    ]
    event_gen = logs.FollowLogEventGenerator(client, sleep)
    options = logs.LogRetrieveOptions(start_time=1)
    assert list(event_gen.iter_log_events(
        log_group_name='mygroup', options=options)) == []
    assert client.filter_log_events.call_args_list == [
        mock.call(log_group_name='mygroup', start_time=1),
        mock.call(log_group_name='mygroup', start_time=1,
                  next_token='nextToken1'),
        mock.call(log_group_name='mygroup', start_time=1,
                  next_token='nextToken2'),
        mock.call(log_group_name='mygroup', start_time=1,
                  next_token='nextToken3'),
        # The last call should not use a next token.
        mock.call(log_group_name='mygroup', start_time=1)
    ]


def test_follow_logs_defaults_to_ten_minutes():
    # To avoid having to patch out/pass in utcnow(), we'll just make sure
    # that the start_time used is more recent than 10 minutes from now.
    # This is a safe assumption because we're saving the current time before
    # we invoke iter_log_events().
    ten_minutes = datetime.utcnow() - timedelta(minutes=10)
    options = logs.LogRetrieveOptions.create(follow=True)
    assert options.start_time >= ten_minutes


def test_dont_default_if_explicit_since_is_provided():
    utcnow = datetime.utcnow()
    options = logs.LogRetrieveOptions.create(follow=True, since=str(utcnow))
    assert options.start_time == utcnow
