import logging

from chalice.cli import utils


def assert_has_no_request_body_filter(log_name):
    log = logging.getLogger(log_name)
    assert not any(
        isinstance(f, utils.LargeRequestBodyFilter) for f in log.filters)


def assert_request_body_filter_in_log(log_name):
    log = logging.getLogger(log_name)
    assert any(
        isinstance(f, utils.LargeRequestBodyFilter) for f in log.filters)


def test_can_create_botocore_session():
    session = utils.create_botocore_session()
    assert session.user_agent().startswith('aws-chalice/')


def test_can_create_botocore_session_debug():
    log_name = 'botocore.endpoint'
    assert_has_no_request_body_filter(log_name)

    utils.create_botocore_session(debug=True)

    assert_request_body_filter_in_log(log_name)
    assert logging.getLogger('').level == logging.DEBUG
