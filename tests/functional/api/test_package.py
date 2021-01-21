import os
import json

import pytest
from click.testing import CliRunner

from chalice.cli import newproj
from chalice.api import package_app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.mark.parametrize('package_format,template_format,expected_filename', [
    ('cloudformation', 'json', 'sam.json'),
    ('cloudformation', 'yaml', 'sam.yaml'),
    ('terraform', 'json', 'chalice.tf.json'),
])
def test_can_package_different_formats(runner, package_format,
                                       template_format,
                                       expected_filename):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        package_app('testproject', output_dir='packagedir', stage='dev',
                    package_format=package_format,
                    template_format=template_format)
        app_contents = os.listdir('packagedir')
        assert expected_filename in app_contents
        assert 'deployment.zip' in app_contents


def test_can_override_chalice_config(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        chalice_config = {
            'environment_variables': {
                'FOO': 'BAR',
            }
        }
        package_app('testproject', output_dir='packagedir', stage='dev',
                    chalice_config=chalice_config)
        app_contents = os.listdir('packagedir')
        assert 'sam.json' in app_contents
        with open(os.path.join('packagedir', 'sam.json')) as f:
            data = json.loads(f.read())
        properties = data['Resources']['APIHandler']['Properties']
        assert properties['Environment'] == {
            'Variables': {
                'FOO': 'BAR',
            }
        }
