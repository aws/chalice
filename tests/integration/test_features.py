import pytest
import os
import requests
import json
import botocore.session
import shutil

from chalice import deployer
from chalice.cli import load_chalice_app
from chalice.config import Config

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(CURRENT_DIR, 'testapp')
CHALICE_DIR = os.path.join(PROJECT_DIR, '.chalice')


class SmokeTestApplication(object):
    def __init__(self, url, rest_api_id, region_name, name):
        if url.endswith('/'):
            url = url[:-1]
        self.url = url
        self.rest_api_id = rest_api_id
        self.region_name = region_name
        self.name = name

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
    session = botocore.session.get_session()
    config = Config.create(
        project_dir=PROJECT_DIR,
        app_name='smoketestapp',
        stage_name='dev',
        autogen_policy=True,
        chalice_app=load_chalice_app(PROJECT_DIR),
    )
    d = deployer.create_default_deployer(session=session)
    rest_api_id, region_name, stage = d.deploy(config)
    url = (
        "https://{api_id}.execute-api.{region}.amazonaws.com/{stage}/".format(
            api_id=rest_api_id, region=region_name, stage=stage))
    application = SmokeTestApplication(url, rest_api_id, region_name, 'smoketestapp')
    return application


def _delete_app(application):
    s = botocore.session.get_session()
    lambda_client = s.create_client('lambda')
    lambda_client.delete_function(FunctionName=application.name)

    iam = s.create_client('iam')
    policies = iam.list_role_policies(RoleName=application.name)
    for name in policies['PolicyNames']:
        iam.delete_role_policy(RoleName=application.name, PolicyName=name)
    iam.delete_role(RoleName=application.name)

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
        'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token')
    assert headers['Access-Control-Allow-Methods'] == 'GET,POST,PUT,OPTIONS'


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
