import mock

import pytest
from chalice.config import Config
from chalice import package
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
    template = p.generate_sam_template(sample_app, 'code-uri',
                                       api_gateway_stage='dev')
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
    template = p.generate_sam_template(sample_app)
    assert template['Resources']['APIHandler']['Properties']['Policies'] == [{
        'iam': 'policy',
    }]


def test_sam_injects_swagger_doc(sample_app,
                                 mock_swagger_generator,
                                 mock_policy_generator):
    p = package.SAMTemplateGenerator(mock_swagger_generator,
                                      mock_policy_generator)
    mock_swagger_generator.generate_swagger.return_value = {
        'swagger': 'document'
    }
    template = p.generate_sam_template(sample_app)
    properties = template['Resources']['RestAPI']['Properties']
    assert properties['DefinitionBody'] == {'swagger': 'document'}
