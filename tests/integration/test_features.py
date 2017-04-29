import json
import os
import shutil

import botocore.session
import pytest
import requests

from chalice.cli.factory import CLIFactory


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(CURRENT_DIR, 'testapp')
CHALICE_DIR = os.path.join(PROJECT_DIR, '.chalice')


class SmokeTestApplication(object):
    def __init__(self, url, deployed_values, stage_name, app_name):
        if url.endswith('/'):
            url = url[:-1]
        self.url = url
        self._deployed_values = deployed_values
        self.stage_name = stage_name
        self.app_name = app_name

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


@pytest.fixture(scope='module')
def smoke_test_app():
    application = _deploy_app()
    yield application
    _delete_app(application)


def _deploy_app():
    if not os.path.isdir(CHALICE_DIR):
        os.makedirs(CHALICE_DIR)
    with open(os.path.join(CHALICE_DIR, 'config.json'), 'w') as f:
        f.write('{"app_name": "smoketestapp"}\n')
    factory = CLIFactory(PROJECT_DIR)
    config = factory.create_config_obj(
        chalice_stage_name='dev',
        autogen_policy=True
    )
    d = factory.create_default_deployer(
        factory.create_botocore_session(), None)
    deployed = d.deploy(config)['dev']
    url = (
        "https://{rest_api_id}.execute-api.{region}.amazonaws.com/"
        "{api_gateway_stage}/".format(**deployed))
    application = SmokeTestApplication(
        url=url,
        deployed_values=deployed,
        stage_name='dev',
        app_name='smoketestapp',
    )
    return application


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
    chalice_dir = os.path.join(PROJECT_DIR, '.chalice')
    shutil.rmtree(chalice_dir)
    os.makedirs(chalice_dir)


def test_returns_simple_response(smoke_test_app):
    assert smoke_test_app.get_json('/') == {'hello': 'world'}


def test_can_have_nested_routes(smoke_test_app):
    assert smoke_test_app.get_json('/a/b/c/d/e/f/g') == {'nested': True}


def test_supports_path_params(smoke_test_app):
    assert smoke_test_app.get_json('/path/foo') == {'path': 'foo'}
    assert smoke_test_app.get_json('/path/bar') == {'path': 'bar'}


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
    assert headers['Access-Control-Allow-Methods'] == 'GET,POST,PUT,OPTIONS'


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
    assert headers['Access-Control-Allow-Methods'] == 'GET,POST,PUT,OPTIONS'
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
