import zipfile

import botocore.session
from botocore.stub import Stubber
from pytest import fixture


class FakeSdistBuilder(object):
    _SETUP_PY = (
        'from setuptools import setup\n'
        'setup(\n'
        '    name="%s",\n'
        '    version="%s"\n'
        ')\n'
    )

    def write_fake_sdist(self, directory, name, version):
        filename = '%s-%s.zip' % (name, version)
        path = '%s/%s' % (directory, filename)
        with zipfile.ZipFile(path, 'w',
                             compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('sdist/setup.py', self._SETUP_PY % (name, version))
        return directory, filename


@fixture
def sdist_builder():
    s = FakeSdistBuilder()
    return s


def pytest_addoption(parser):
    parser.addoption('--skip-slow', action='store_true',
                     help='Skip slow tests')


class StubbedSession(botocore.session.Session):
    def __init__(self, *args, **kwargs):
        super(StubbedSession, self).__init__(*args, **kwargs)
        self._cached_clients = {}
        self._client_stubs = {}

    def create_client(self, service_name, *args, **kwargs):
        if service_name not in self._cached_clients:
            client = self._create_stubbed_client(service_name, *args, **kwargs)
            self._cached_clients[service_name] = client
        return self._cached_clients[service_name]

    def _create_stubbed_client(self, service_name, *args, **kwargs):
        client = super(StubbedSession, self).create_client(
            service_name, *args, **kwargs)
        stubber = StubBuilder(ChaliceStubber(client))
        self._client_stubs[service_name] = stubber
        return client

    def stub(self, service_name):
        if service_name not in self._client_stubs:
            self.create_client(service_name)
        return self._client_stubs[service_name]

    def activate_stubs(self):
        for stub in self._client_stubs.values():
            stub.activate()

    def verify_stubs(self):
        for stub in self._client_stubs.values():
            stub.assert_no_pending_responses()


class StubBuilder(object):
    def __init__(self, stub):
        self.stub = stub
        self.activated = False
        self.pending_args = {}

    def __getattr__(self, name):
        if self.activated:
            # I want to be strict here to guide common test behavior.
            # This helps encourage the "record" "replay" "verify"
            # idiom in traditional mock frameworks.
            raise RuntimeError("Stub has already been activated: %s, "
                               "you must set up your stub calls before "
                               "calling .activate()" % self.stub)
        if not name.startswith('_'):
            # Assume it's an API call.
            self.pending_args['operation_name'] = name
            return self

    def assert_no_pending_responses(self):
        self.stub.assert_no_pending_responses()

    def activate(self):
        self.activated = True
        self.stub.activate()

    def returns(self, response):
        self.pending_args['service_response'] = response
        # returns() is essentially our "build()" method and triggers
        # creations of a stub response creation.
        p = self.pending_args
        self.stub.add_response(p['operation_name'],
                               expected_params=p['expected_params'],
                               service_response=p['service_response'])
        # And reset the pending_args for the next stub creation.
        self.pending_args = {}

    def raises_error(self, error_code=None, message=None, error=None):
        p = self.pending_args
        if error_code is not None and message is not None:
            self.stub.add_client_error(p['operation_name'],
                                       service_error_code=error_code,
                                       service_message=message)
        elif error is not None:
            self.stub.add_response_error(p['operation_name'],
                                         error)
        else:
            raise ValueError(
                'Either error_code and message must be provided or '
                'error must be provided'
            )
        # Reset pending args for next expectation.
        self.pending_args = {}

    def __call__(self, **kwargs):
        self.pending_args['expected_params'] = kwargs
        return self


# TODO: Port this functionality to inject non-ClientErrors back to botocore
class ChaliceStubber(Stubber):
    def add_response_error(self, method, error, expected_params=None):
        """Adds a custom exception to the response queue

        :type method: str
        :param method: Thhe name of the service method to raise the error
            on.

        :type error: Exception
        :param error: The customer exception to raise

        :type expected_params: dict
        :param expected_params: A dictionary of the expected parameters to
            be called for the provided service response. The parameters match
            the names of keyword arguments passed to that client call. If
            any of the parameters differ a ``StubResponseError`` is thrown.
            You can use stub.ANY to indicate a particular parameter to ignore
            in validation. stub.ANY is only valid for top level params.
        """
        operation_name = self.client.meta.method_to_api_mapping.get(method)
        response = {
            'operation_name': operation_name,
            'response': error,
            'expected_params': expected_params,
        }
        self._queue.append(response)

    def _get_response_handler(self, model, params, **kwargs):
        response = super(ChaliceStubber, self)._get_response_handler(
            model, params, **kwargs)
        if isinstance(response, Exception):
            raise response
        return response


@fixture
def stubbed_session():
    s = StubbedSession()
    return s


@fixture
def no_local_config(monkeypatch):
    """Ensure no local AWS configuration is used.

    This is useful for unit/functional tests so we
    can ensure that local configuration does not affect
    the results of the test.

    """
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-west-2')
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'foo')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'bar')
    monkeypatch.delenv('AWS_PROFILE', raising=False)
    monkeypatch.delenv('AWS_DEFAULT_PROFILE', raising=False)
    # Ensure that the existing ~/.aws/{config,credentials} file
    # don't influence test results.
    monkeypatch.setenv('AWS_CONFIG_FILE', '/tmp/asdfasdfaf/does/not/exist')
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE',
                       '/tmp/asdfasdfaf/does/not/exist2')
