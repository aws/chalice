import mock

import pytest
from chalice.config import Config
from chalice import package
from chalice import __version__ as chalice_version
from chalice.deploy.deployer import ApplicationPolicyHandler
from chalice.deploy.swagger import SwaggerGenerator


@pytest.fixture
def mock_swagger_generator():
    return mock.Mock(spec=SwaggerGenerator)


@pytest.fixture
def mock_policy_generator():
    return mock.Mock(spec=package.PreconfiguredPolicyGenerator)


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
    generator = package.PreconfiguredPolicyGenerator(
        config, policy_gen=policy_gen)
    policy_gen.generate_policy_from_app_source.return_value = {
        'policy': True}
    policy = generator.generate_policy_from_app_source()
    policy_gen.generate_policy_from_app_source.assert_called_with(config)
    assert policy == {'policy': True}


def test_sam_generates_sam_template_basic(sample_app,
                                          mock_swagger_generator,
                                          mock_policy_generator):
    p = package.SAMTemplateGenerator(mock_swagger_generator,
                                     mock_policy_generator)
    config = Config.create(chalice_app=sample_app,
                           api_gateway_stage='dev')
    template = p.generate_sam_template(config, 'code-uri')
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


def test_sam_injects_swagger_doc(sample_app,
                                 mock_swagger_generator,
                                 mock_policy_generator):
    p = package.SAMTemplateGenerator(mock_swagger_generator,
                                      mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(chalice_app=sample_app,
                           api_gateway_stage='dev')
    template = p.generate_sam_template(config)
    properties = template['Resources']['RestAPI']['Properties']
    assert properties['DefinitionBody'] == {'swagger': 'document'}


def test_can_inject_environment_vars(sample_app,
                                     mock_swagger_generator,
                                     mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
        environment_variables={
            'FOO': 'BAR'
        }
    )
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert 'Environment' in properties
    assert properties['Environment']['Variables'] == {'FOO': 'BAR'}


def test_chalice_tag_added_to_function(sample_app,
                                       mock_swagger_generator,
                                       mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp')
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Tags'] == {
        'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version}


def test_custom_tags_added_to_function(sample_app,
                                       mock_swagger_generator,
                                       mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp', tags={'mykey': 'myvalue'})
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Tags'] == {
        'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version,
        'mykey': 'myvalue'
    }


def test_default_function_timeout(sample_app,
                                  mock_swagger_generator,
                                  mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev')
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Timeout'] == 60


def test_timeout_added_to_function(sample_app,
                                   mock_swagger_generator,
                                   mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp', lambda_timeout=240)
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Timeout'] == 240


def test_default_function_memory_size(sample_app,
                                      mock_swagger_generator,
                                      mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev')
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['MemorySize'] == 128


def test_memory_size_added_to_function(sample_app,
                                       mock_swagger_generator,
                                       mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(chalice_app=sample_app, api_gateway_stage='dev',
                           app_name='myapp', lambda_memory_size=256)
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['MemorySize'] == 256


def test_endpoint_url_reflects_apig_stage(sample_app,
                                          mock_swagger_generator,
                                          mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='prod',
    )
    template = p.generate_sam_template(config)
    endpoint_url = template['Outputs']['EndpointURL']['Value']['Fn::Sub']
    assert endpoint_url == (
        'https://${RestAPI}.execute-api.${AWS::Region}.amazonaws.com/prod/')


def test_maps_python_version(sample_app,
                             mock_swagger_generator,
                             mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(
        chalice_app=sample_app,
        api_gateway_stage='dev',
    )
    template = p.generate_sam_template(config)
    expected = config.lambda_python_version
    actual = template['Resources']['APIHandler']['Properties']['Runtime']
    assert actual == expected


def test_role_arn_added_to_function(sample_app,
                                    mock_swagger_generator,
                                    mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(
        chalice_app=sample_app, api_gateway_stage='dev', app_name='myapp',
        manage_iam_role=False, iam_role_arn='role-arn')
    template = p.generate_sam_template(config)
    properties = template['Resources']['APIHandler']['Properties']
    assert properties['Role'] == 'role-arn'
    assert 'Policies' not in properties


def test_fails_with_custom_auth(sample_app_with_auth,
                                mock_swagger_generator,
                                mock_policy_generator):
    p = package.SAMTemplateGenerator(
        mock_swagger_generator, mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    config = Config.create(
        chalice_app=sample_app_with_auth, api_gateway_stage='dev', app_name='myapp',
        manage_iam_role=False, iam_role_arn='role-arn')
    with pytest.raises(package.UnsupportedFeatureError):
        p.generate_sam_template(config)
