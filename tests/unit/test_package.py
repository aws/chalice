import mock

import pytest
from chalice.config import Config
from chalice import package
from chalice import __version__ as chalice_version
from chalice.deploy.deployer import ApplicationPolicyHandler
from chalice.deploy.swagger import SwaggerGenerator


@pytest.fixture
def mock_swagger_generator():
    swagger = mock.Mock(spec=SwaggerGenerator)
    swagger.generate_swagger.return_value = {
        'swagger': 'document'
    }
    return swagger


@pytest.fixture
def mock_policy_generator():
    return mock.Mock(spec=ApplicationPolicyHandler)


@pytest.fixture
def cfn_gen(mock_swagger_generator, mock_policy_generator):
    p = package.SAMTemplateGenerator(mock_swagger_generator,
                                     mock_policy_generator)
    return p


def test_can_create_app_packager():
    config = Config()
    packager = package.create_app_packager(config)
    assert isinstance(packager, package.AppPackager)


def test_can_create_app_packager_with_no_autogen():
    # We can't actually observe a change here, but we want
    # to make sure the function can handle this param being
    # False.
    config = Config.create(autogen_policy=False)
    packager = package.create_app_packager(config)
    assert isinstance(packager, package.AppPackager)


def test_preconfigured_policy_proxies():
    policy_gen = mock.Mock(spec=ApplicationPolicyHandler)
    config = Config.create(project_dir='project_dir', autogen_policy=False)
    policy_gen.generate_policy_from_app_source.return_value = {
        'policy': True}
    policy = policy_gen.generate_policy_from_app_source(config)
    assert policy == {'policy': True}


def test_sam_generates_sam_template_basic(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app,
                           api_gateway_stage='dev')
    template = cfn_gen.generate_sam_template(config, 'code-uri')
    # Verify the basic structure is in place.  The specific parts
    # are validated in other tests.
    assert template['AWSTemplateFormatVersion'] == '2010-09-09'
    assert template['Transform'] == 'AWS::Serverless-2016-10-31'
    assert 'Outputs' in template
    assert 'Resources' in template


def test_sam_injects_policy(sample_app,
                            mock_swagger_generator,
                            mock_policy_generator):
    p = package.SAMTemplateGenerator(mock_swagger_generator,
                                     mock_policy_generator)

    mock_policy_generator.generate_policy_from_app_source.return_value = {
        'iam': 'policy',
    }
    config = Config.create(chalice_app=sample_app,
                           api_gateway_stage='dev')
    template = p.generate_sam_template(config)
    assert template['Resources']['APIHandler']['Properties']['Policies'] == [{
        'iam': 'policy',
    }]
    assert 'Role' not in template['Resources']['APIHandler']['Properties']


def test_sam_injects_swagger_doc(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app,
                           api_gateway_stage='dev')
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['RestAPI']['Properties']
    assert properties['DefinitionBody'] == {'swagger': 'document'}


def test_can_inject_environment_vars(sample_app, cfn_gen):
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
        environment_variables={
            'FOO': 'BAR'
        }
    )
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert 'Environment' in properties
    assert properties['Environment']['Variables'] == {'FOO': 'BAR'}


def test_can_extract_env_vars_as_cfn_params(sample_app, cfn_gen):
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
        environment_variables={
            'MY_ENV_VAR': 'BAR'
        }
    )
    template = cfn_gen.generate_sam_template(config, map_env_to_params=True)
    props = template['Resources']['APIHandler']['Properties']
    env = props['Environment']['Variables']
    assert env == {'MY_ENV_VAR': {'Ref': 'ApiHandlerMyEnvVar'}}

    params = template['Parameters']
    assert params == {
        'ApiHandlerMyEnvVar': {'Default': 'BAR', 'Type': 'String'}
    }


def test_error_when_dupe_env_var_found(sample_app, cfn_gen):
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
        # Both of these will transform to MyEnvVar
        environment_variables={
            'MY_ENV_VAR': 'BAR',
            'MY___ENV___VAR': 'BAR2',
        }
    )
    with pytest.raises(package.DuplicateEnvVarParameter):
        cfn_gen.generate_sam_template(config, map_env_to_params=True)


def test_extract_env_vars_for_other_lambda_functions(sample_app, cfn_gen):
    @sample_app.authorizer()
    def custom_auth(auth_request):
        pass

    @sample_app.route('/authorized', authorizer=custom_auth)
    def foo():
        return {}

    config = Config(
        user_provided_params={'chalice_app': sample_app},
        config_from_disk={
            'stages': {
                'dev': {
                    'lambda_functions': {
                        'custom_auth': {
                            'environment_variables': {
                                'MY_VAR': 'BAR',
                            }
                        }
                    }
                }
            }
        }
    )
    template = cfn_gen.generate_sam_template(config, map_env_to_params=True)

    props = template['Resources']['customauth8767']['Properties']
    env = props['Environment']['Variables']
    assert env == {'MY_VAR': {'Ref': 'CustomAuthMyVar'}}

    params = template['Parameters']
    assert params == {
        'CustomAuthMyVar': {'Default': 'BAR', 'Type': 'String'}
    }


def test_chalice_tag_added_to_function(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp')
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Tags'] == {
        'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version}


def test_custom_tags_added_to_function(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp', tags={'mykey': 'myvalue'})
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Tags'] == {
        'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version,
        'mykey': 'myvalue'
    }


def test_default_function_timeout(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev')
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Timeout'] == 60


def test_timeout_added_to_function(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp', lambda_timeout=240)
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Timeout'] == 240


def test_default_function_memory_size(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev')
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['MemorySize'] == 128


def test_memory_size_added_to_function(sample_app, cfn_gen):
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp', lambda_memory_size=256)
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['MemorySize'] == 256


def test_endpoint_url_reflects_apig_stage(sample_app, cfn_gen):
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='prod',
    )
    template = cfn_gen.generate_sam_template(config)
    endpoint_url = template['Outputs']['EndpointURL']['Value']['Fn::Sub']
    assert endpoint_url == (
        'https://${RestAPI}.execute-api.${AWS::Region}.amazonaws.com/prod/')


def test_maps_python_version(sample_app, cfn_gen):
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
    )
    template = cfn_gen.generate_sam_template(config)
    expected = config.lambda_python_version
    actual = template['Resources']['APIHandler']['Properties']['Runtime']
    assert actual == expected


def test_role_arn_added_to_function(sample_app, cfn_gen):
    config = Config.create(
        chalice_app=sample_app, api_gateway_stage='dev', app_name='myapp',
        manage_iam_role=False, iam_role_arn='role-arn')
    template = cfn_gen.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Role'] == 'role-arn'
    assert 'Policies' not in properties


def test_app_incompatible_with_cf(sample_app, cfn_gen):

    @sample_app.route('/foo')
    def foo_invalid():
        return {}

    config = Config.create(chalice_app=sample_app,
                           api_gateway_stage='dev',
                           app_name='sample_invalid_cf')
    template = cfn_gen.generate_sam_template(config)
    events = template['Resources']['APIHandler']['Properties']['Events']
    # The underscore should be removed from the event name.
    assert 'fooinvalidget4cee' in events


def test_app_with_auth(sample_app, cfn_gen):

    @sample_app.authorizer('myauth')
    def myauth(auth_request):
        pass

    @sample_app.route('/authorized', authorizer=myauth)
    def foo():
        return {}
    # The last four digits come from the hash of the auth name
    cfn_auth_name = 'myauthdb6d'

    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
    )
    template = cfn_gen.generate_sam_template(config)
    assert cfn_auth_name in template['Resources']
    auth_function = template['Resources'][cfn_auth_name]
    assert auth_function['Type'] == 'AWS::Serverless::Function'
    assert auth_function['Properties']['Handler'] == 'app.myauth'

    # Assert that the invoke permsissions were added as well.
    assert cfn_auth_name + 'InvokePermission' in template['Resources']
    assert template['Resources'][cfn_auth_name + 'InvokePermission'] == {
        'Type': 'AWS::Lambda::Permission',
        'Properties': {
            'Action': 'lambda:InvokeFunction',
            'FunctionName': {
                'Fn::GetAtt': [
                    cfn_auth_name,
                    'Arn'
                ]
            },
            'Principal': 'apigateway.amazonaws.com'
        }
    }


def test_app_with_auth_but_invalid_cfn_name(sample_app, cfn_gen):
    # Underscores are not allowed for CFN resource names
    # This instead should be referred to as customauth in CFN templates
    # where the underscore is removed.
    @sample_app.authorizer('custom_auth')
    def custom_auth(auth_request):
        pass

    @sample_app.route('/authorized', authorizer=custom_auth)
    def foo():
        return {}

    # The last four digits come from the hash of the auth name
    cfn_auth_name = 'customauth8767'
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
    )
    template = cfn_gen.generate_sam_template(config)
    assert cfn_auth_name in template['Resources']
    auth_function = template['Resources'][cfn_auth_name]
    assert auth_function['Type'] == 'AWS::Serverless::Function'
    assert auth_function['Properties']['Handler'] == 'app.custom_auth'

    # Assert that the invoke permsissions were added as well.
    assert cfn_auth_name + 'InvokePermission' in template['Resources']
    assert template['Resources'][cfn_auth_name + 'InvokePermission'] == {
        'Type': 'AWS::Lambda::Permission',
        'Properties': {
            'Action': 'lambda:InvokeFunction',
            'FunctionName': {
                'Fn::GetAtt': [
                    cfn_auth_name,
                    'Arn'
                ]
            },
            'Principal': 'apigateway.amazonaws.com'
        }
    }
