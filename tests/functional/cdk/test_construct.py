import os
import sys
import json

import pytest
from click.testing import CliRunner

from chalice.cli import newproj


try:
    from aws_cdk import core as cdk
except Exception:
    pytestmark = pytest.mark.skip(
        "aws_cdk package needed to run CDK tests.")


@pytest.fixture
def runner():
    return CliRunner()


def load_chalice_construct(dirname, stack_name='testcdk'):
    try:
        sys.path.append(dirname)
        sys.modules.pop('stacks.chaliceapp', None)
        sys.modules.pop('stacks', None)
        import stacks.chaliceapp
        app = cdk.App()
        chalice_app = stacks.chaliceapp.ChaliceApp(app, stack_name)
        return app, chalice_app.chalice
    finally:
        sys.modules.pop('app', None)
        sys.modules.pop('stacks', None)
        sys.path.pop()


def filter_resources(template, resource_type):
    return [(name, props) for name, props in template['Resources'].items()
            if props['Type'] == resource_type]


def test_cdk_construct_api(runner):
    # The CDK loading/synth can take a while so we're testing the
    # various APIs out in one test to cut down on test time.
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton(
            'testcdk', project_type='cdk-ddb')
        dirname = os.path.abspath(os.path.join('testcdk', 'infrastructure'))
        os.chdir(dirname)
        cdk_app, chalice_app = load_chalice_construct(dirname, 'testcdk')
        api_handler = chalice_app.get_function('APIHandler')
        assert api_handler == chalice_app.get_function('APIHandler')
        role = chalice_app.get_role('DefaultRole')
        assert hasattr(role, 'role_name')


def test_can_package_as_cdk_app(runner):
    # The CDK loading/synth can take a while so we're testing the
    # various APIs out in one test to cut down on test time.
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton(
            'testcdkpackage', project_type='cdk-ddb')
        dirname = os.path.abspath(os.path.join('testcdkpackage',
                                               'infrastructure'))
        os.chdir(dirname)
        cdk_app, chalice_app = load_chalice_construct(
            dirname, 'testcdkpackage')
        assembly = cdk_app.synth()
        stack = assembly.get_stack_by_name('testcdkpackage')
        cfn_template = stack.template
        resources = cfn_template['Resources']
        # Sanity check that we have the resources from Chalice as well as the
        # resources from the ChaliceApp construct.
        assert 'APIHandler' in resources
        assert 'DefaultRole' in resources
        ddb_tables = filter_resources(cfn_template, 'AWS::DynamoDB::Table')[0]
        # CDK adds a random suffix to our resource name so we verify that
        # the name starts with our provided name "AppTable".
        assert ddb_tables[0].startswith('AppTable')
        # We also need to verify that we've replaces the CodUri with the
        # CDK specific assets.
        functions = filter_resources(
            cfn_template, 'AWS::Serverless::Function')[0]
        bucket_ref = functions[1]['Properties']['CodeUri']['Bucket']['Ref']
        assert bucket_ref.startswith('AssetParameters')


@pytest.mark.xfail(reason=("Expected fail due to invalid schema in "
                           "CDK sam.json file."))
def test_can_package_managed_layer(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton(
            'testcdklayers', project_type='cdk-ddb')
        project_dir = os.path.abspath('testcdklayers')
        config_file = os.path.join(project_dir, 'runtime',
                                   '.chalice', 'config.json')
        with open(config_file) as f:
            config = json.load(f)
            config['automatic_layer'] = True
        with open(config_file, 'w') as f:
            f.write(json.dumps(config))
        infrastructure_dir = os.path.join(project_dir, 'infrastructure')
        os.chdir(infrastructure_dir)
        cdk_app, chalice_app = load_chalice_construct(infrastructure_dir,
                                                      'testcdklayers')
        assembly = cdk_app.synth()
        stack = assembly.get_stack_by_name('testcdklayers')
        cfn_template = stack.template
        layers = filter_resources(
            cfn_template, 'AWS::Serverless::LayerVersion')[0]
        bucket_ref = layers[1]['Properties']['ContentUri']['Bucket']['Ref']
        assert bucket_ref.startswith('AssetParameters')
