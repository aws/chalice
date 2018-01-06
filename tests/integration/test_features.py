import json
import os
import sys
import time
import shutil
import uuid

import botocore.session
import pytest
import requests

from chalice.cli.factory import CLIFactory
from chalice.utils import record_deployed_values, OSUtils
from chalice.deploy.deployer import ChaliceDeploymentError


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(CURRENT_DIR, 'testapp')
APP_FILE = os.path.join(PROJECT_DIR, 'app.py')
RANDOM_APP_NAME = 'smoketest-%s' % str(uuid.uuid4())


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


class SmokeTestApplication(object):

    # Number of seconds to wait after redeploy before starting
    # to poll for successful 200.
    _REDEPLOY_SLEEP = 20
    # Seconds to wait between poll attempts after redeploy.
    _POLLING_DELAY = 5

    def __init__(self, url, deployed_values, stage_name, app_name,
                 app_dir):
        if url.endswith('/'):
            url = url[:-1]
        self.url = url
        self._deployed_values = deployed_values
        self.stage_name = stage_name
        self.app_name = app_name
        # The name of the tmpdir where the app is copied.
        self.app_dir = app_dir
        self._has_redeployed = False

    @property
    def rest_api_id(self):
        return self._deployed_values['rest_api_id']

    @property
    def region_name(self):
        return self._deployed_values['region_name']

    @property
    def api_handler_arn(self):
        return self._deployed_values['api_handler_arn']

    def get_json(self, url):
        if not url.startswith('/'):
            url = '/' + url
        response = requests.get(self.url + url)
        response.raise_for_status()
        return response.json()

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
        self._wait_for_stablize()

    @retry(max_attempts=10, delay=5)
    def _wait_for_stablize(self):
        # After a deployment we sometimes need to wait for
        # API Gateway to propagate all of its changes.
        # We're going to give it num_attempts to give us a
        # 200 response before failing.
        try:
            return self.get_json('/')
        except requests.exceptions.HTTPError:
            pass

    def _clear_app_import(self):
        # Now that we're using `import` instead of `exec` we need
        # to clear out sys.modules in order to pick up the new
        # version of the app we just copied over.
        del sys.modules['app']


@pytest.fixture
def apig_client():
    s = botocore.session.get_session()
    return s.create_client('apigateway')


@pytest.fixture(scope='module')
def smoke_test_app(tmpdir_factory):
    # We can't use the monkeypatch fixture here because this is a module scope
    # fixture and monkeypatch is a function scoped fixture.
    os.environ['APP_NAME'] = RANDOM_APP_NAME
    tmpdir = str(tmpdir_factory.mktemp(RANDOM_APP_NAME))
    OSUtils().copytree(PROJECT_DIR, tmpdir)
    _inject_app_name(tmpdir)
    application = _deploy_app(tmpdir)
    yield application
    _delete_app(application)
    os.environ.pop('APP_NAME')


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
    d = factory.create_default_deployer(
        factory.create_botocore_session(), None)
    deployed_stages = _deploy_with_retries(d, config)
    deployed = deployed_stages['dev']
    url = (
        "https://{rest_api_id}.execute-api.{region}.amazonaws.com/"
        "{api_gateway_stage}/".format(**deployed))
    application = SmokeTestApplication(
        url=url,
        deployed_values=deployed,
        stage_name='dev',
        app_name=RANDOM_APP_NAME,
        app_dir=temp_dirname,
    )
    record_deployed_values(
        deployed_stages,
        os.path.join(temp_dirname, '.chalice', 'deployed.json')
    )
    return application


@retry(max_attempts=10, delay=20)
def _deploy_with_retries(deployer, config):
    try:
        deployed_stages = deployer.deploy(config)
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


def _delete_app(application):
    s = botocore.session.get_session()
    lambda_client = s.create_client('lambda')
    # You can use either the function name of the function ARN
    # for this argument, despite the name being FunctionName.
    lambda_client.delete_function(FunctionName=application.api_handler_arn)

    iam = s.create_client('iam')
    role_name = application.app_name + '-' + application.stage_name
    policies = iam.list_role_policies(RoleName=role_name)
    for name in policies['PolicyNames']:
        iam.delete_role_policy(RoleName=role_name, PolicyName=name)
    iam.delete_role(RoleName=role_name)

    apig = s.create_client('apigateway')
    apig.delete_rest_api(restApiId=application.rest_api_id)


def test_returns_simple_response(smoke_test_app):
    assert smoke_test_app.get_json('/') == {'hello': 'world'}


def test_can_have_nested_routes(smoke_test_app):
    assert smoke_test_app.get_json('/a/b/c/d/e/f/g') == {'nested': True}


def test_supports_path_params(smoke_test_app):
    assert smoke_test_app.get_json('/path/foo') == {'path': 'foo'}
    assert smoke_test_app.get_json('/path/bar') == {'path': 'bar'}


def test_path_params_mapped_in_api(smoke_test_app, apig_client):
    # Use the API Gateway API to ensure that path parameters
    # are modeled as such.  Otherwise this will break
    # SDK generation and any future features that depend
    # on params.  We could try to verify the generated
    # javascript SDK looks ok.  Instead we're going to
    # query the resources we've created in API gateway
    # and make sure requestParameters are present.
    rest_api_id = smoke_test_app.rest_api_id
    resource_id = _get_resource_id(apig_client, rest_api_id)
    method_config = apig_client.get_method(
        restApiId=rest_api_id,
        resourceId=resource_id,
        httpMethod='GET'
    )
    assert 'requestParameters' in method_config
    assert method_config['requestParameters'] == {
        'method.request.path.name': True
    }


@retry(max_attempts=18, delay=10)
def _get_resource_id(apig_client, rest_api_id):
    # This is the resource id for the '/path/{name}'
    # route.  As far as I know this is the best way to get
    # this id.
    matches = [
        resource for resource in
        apig_client.get_resources(restApiId=rest_api_id)['items']
        if resource['path'] == '/path/{name}'
    ]
    if matches:
        return matches[0]['id']


def test_supports_post(smoke_test_app):
    app_url = smoke_test_app.url
    response = requests.post(app_url + '/post')
    response.raise_for_status()
    assert response.json() == {'success': True}
    with pytest.raises(requests.HTTPError):
        # Only POST is supported.
        response = requests.get(app_url + '/post')
        response.raise_for_status()


def test_supports_put(smoke_test_app):
    app_url = smoke_test_app.url
    response = requests.put(app_url + '/put')
    response.raise_for_status()
    assert response.json() == {'success': True}
    with pytest.raises(requests.HTTPError):
        # Only PUT is supported.
        response = requests.get(app_url + '/put')
        response.raise_for_status()


def test_supports_shared_routes(smoke_test_app):
    app_url = smoke_test_app.url
    response = requests.get(app_url + '/shared')
    assert response.json() == {'method': 'GET'}
    response = requests.post(app_url + '/shared')
    assert response.json() == {'method': 'POST'}


def test_can_read_json_body_on_post(smoke_test_app):
    app_url = smoke_test_app.url
    response = requests.post(
        app_url + '/jsonpost', data=json.dumps({'hello': 'world'}),
        headers={'Content-Type': 'application/json'})
    response.raise_for_status()
    assert response.json() == {'json_body': {'hello': 'world'}}


def test_can_raise_bad_request(smoke_test_app):
    response = requests.get(smoke_test_app.url + '/badrequest')
    assert response.status_code == 400
    assert response.json()['Code'] == 'BadRequestError'
    assert response.json()['Message'] == 'BadRequestError: Bad request.'


def test_can_raise_not_found(smoke_test_app):
    response = requests.get(smoke_test_app.url + '/notfound')
    assert response.status_code == 404
    assert response.json()['Code'] == 'NotFoundError'


def test_unexpected_error_raises_500_in_prod_mode(smoke_test_app):
    response = requests.get(smoke_test_app.url + '/arbitrary-error')
    assert response.status_code == 500
    assert response.json()['Code'] == 'InternalServerError'
    assert 'internal server error' in response.json()['Message']


def test_can_route_multiple_methods_in_one_view(smoke_test_app):
    response = requests.get(smoke_test_app.url + '/multimethod')
    response.raise_for_status()
    assert response.json()['method'] == 'GET'

    response = requests.post(smoke_test_app.url + '/multimethod')
    response.raise_for_status()
    assert response.json()['method'] == 'POST'


def test_form_encoded_content_type(smoke_test_app):
    response = requests.post(smoke_test_app.url + '/formencoded',
                             data={'foo': 'bar'})
    response.raise_for_status()
    assert response.json() == {'parsed': {'foo': ['bar']}}


def test_can_round_trip_binary(smoke_test_app):
    # xde xed xbe xef will fail unicode decoding because xbe is an invalid
    # start byte in utf-8.
    bin_data = b'\xDE\xAD\xBE\xEF'
    response = requests.post(smoke_test_app.url + '/binary',
                             headers={
                                 'Content-Type': 'application/octet-stream',
                                 'Accept': 'application/octet-stream',
                             },
                             data=bin_data)
    response.raise_for_status()
    assert response.content == bin_data


def test_can_round_trip_binary_custom_content_type(smoke_test_app):
    bin_data = b'\xDE\xAD\xBE\xEF'
    response = requests.post(smoke_test_app.url + '/custom-binary',
                             headers={
                                 'Content-Type': 'application/binary',
                                 'Accept': 'application/binary',
                             },
                             data=bin_data)
    assert response.content == bin_data


def _assert_contains_access_control_allow_methods(headers, methods):
    actual_methods = headers['Access-Control-Allow-Methods'].split(',')
    assert sorted(methods) == sorted(actual_methods), (
        'The expected allowed methods does not match the actual allowed '
        'methods for CORS.')


def test_can_support_cors(smoke_test_app):
    response = requests.get(smoke_test_app.url + '/cors')
    response.raise_for_status()
    assert response.headers['Access-Control-Allow-Origin'] == '*'

    # Should also have injected an OPTIONs request.
    response = requests.options(smoke_test_app.url + '/cors')
    response.raise_for_status()
    headers = response.headers
    assert headers['Access-Control-Allow-Origin'] == '*'
    assert headers['Access-Control-Allow-Headers'] == (
        'Authorization,Content-Type,X-Amz-Date,X-Amz-Security-Token,'
        'X-Api-Key')
    _assert_contains_access_control_allow_methods(
        headers, ['GET', 'POST', 'PUT', 'OPTIONS'])


def test_can_support_custom_cors(smoke_test_app):
    response = requests.get(smoke_test_app.url + '/custom_cors')
    response.raise_for_status()
    expected_allow_origin = 'https://foo.example.com'
    assert response.headers[
        'Access-Control-Allow-Origin'] == expected_allow_origin

    # Should also have injected an OPTIONs request.
    response = requests.options(smoke_test_app.url + '/custom_cors')
    response.raise_for_status()
    headers = response.headers
    assert headers['Access-Control-Allow-Origin'] == expected_allow_origin
    assert headers['Access-Control-Allow-Headers'] == (
        'Authorization,Content-Type,X-Amz-Date,X-Amz-Security-Token,'
        'X-Api-Key,X-Special-Header')
    _assert_contains_access_control_allow_methods(
        headers, ['GET', 'POST', 'PUT', 'OPTIONS'])
    assert headers['Access-Control-Max-Age'] == '600'
    assert headers['Access-Control-Expose-Headers'] == 'X-Special-Header'
    assert headers['Access-Control-Allow-Credentials'] == 'true'


def test_to_dict_is_also_json_serializable(smoke_test_app):
    assert 'headers' in smoke_test_app.get_json('/todict')


def test_multfile_support(smoke_test_app):
    response = smoke_test_app.get_json('/multifile')
    assert response == {'message': 'success'}


def test_custom_response(smoke_test_app):
    url = smoke_test_app.url + '/custom-response'
    response = requests.get(url)
    response.raise_for_status()
    # Custom header
    assert response.headers['Content-Type'] == 'text/plain'
    # Custom status code
    assert response.status_code == 204


def test_api_key_required_fails_with_no_key(smoke_test_app):
    url = smoke_test_app.url + '/api-key-required'
    response = requests.get(url)
    # Request should fail because we're not providing
    # an API key.
    assert response.status_code == 403


def test_can_handle_charset(smoke_test_app):
    url = smoke_test_app.url + '/json-only'
    # Should pass content type validation even with charset specified.
    response = requests.get(
        url, headers={'Content-Type': 'application/json; charset=utf-8'})
    assert response.status_code == 200


def test_can_use_builtin_custom_auth(smoke_test_app):
    url = smoke_test_app.url + '/builtin-auth'
    # First time without an Auth header, we should fail.
    response = requests.get(url)
    assert response.status_code == 401
    # Now with the proper auth header, things should work.
    response = requests.get(url, headers={'Authorization': 'yes'})
    assert response.status_code == 200
    context = response.json()['context']
    assert 'authorizer' in context
    # The keyval context we added shuld also be in the authorizer
    # dict.
    assert context['authorizer']['foo'] == 'bar'


def test_can_use_shared_auth(smoke_test_app):
    url = smoke_test_app.url + '/fake-profile'
    response = requests.get(url)
    # GETs are allowed
    assert response.status_code == 200
    # However, POSTs require auth.
    # This has the same auth config as /builtin-auth,
    # so we're testing the auth handler can be shared.
    assert requests.post(url).status_code == 401
    response = requests.post(url, headers={'Authorization': 'yes'})
    assert response.status_code == 200
    context = response.json()['context']
    assert 'authorizer' in context
    assert context['authorizer']['foo'] == 'bar'


def test_empty_raw_body(smoke_test_app):
    url = smoke_test_app.url + '/repr-raw-body'
    response = requests.post(url)
    response.raise_for_status()
    assert response.json() == {'repr-raw-body': ''}


@pytest.mark.on_redeploy
def test_redeploy_no_change_view(smoke_test_app):
    smoke_test_app.redeploy_once()
    assert smoke_test_app.get_json('/') == {'hello': 'world'}


@pytest.mark.on_redeploy
def test_redeploy_changed_function(smoke_test_app):
    smoke_test_app.redeploy_once()
    assert smoke_test_app.get_json('/a/b/c/d/e/f/g') == {
        'redeployed': True}


@pytest.mark.on_redeploy
def test_redeploy_new_function(smoke_test_app):
    smoke_test_app.redeploy_once()
    assert smoke_test_app.get_json('/redeploy') == {'success': True}


@pytest.mark.on_redeploy
def test_redeploy_change_route_info(smoke_test_app):
    smoke_test_app.redeploy_once()
    url = smoke_test_app.url + '/multimethod'
    # POST is no longer allowed:
    assert requests.post(url).status_code == 403
    # But PUT is now allowed in the redeployed app.py
    assert requests.put(url).status_code == 200


@pytest.mark.on_redeploy
def test_redeploy_view_deleted(smoke_test_app):
    smoke_test_app.redeploy_once()
    url = smoke_test_app.url + '/path/foo'
    response = requests.get(url)
    # Request should fail because it's not in the redeployed
    # app.py
    assert response.status_code == 403
