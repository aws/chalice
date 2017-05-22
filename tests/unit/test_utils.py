from chalice import __version__ as chalice_version
from chalice import utils
from chalice.config import Config


class TestGetApplicationTags(object):
    def test_no_tags_configured(self):
        c = Config.create(chalice_stage='dev', app_name='myapp')
        assert utils.get_application_tags(c) == {
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version}

    def test_tags_specified(self):
        c = Config.create(
            chalice_stage='dev', app_name='myapp', tags={'mykey': 'myvalue'})
        assert utils.get_application_tags(c) == {
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version,
            'mykey': 'myvalue'
        }

    def test_tags_specified_does_not_override_chalice_tag(self):
        c = Config.create(
            chalice_stage='dev', app_name='myapp',
            tags={'aws-chalice': 'attempted-override'})
        assert utils.get_application_tags(c) == {
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version,
        }
