import pytest
import mock

from chalice.app import Chalice
from chalice.config import Config
from chalice import CORSConfig
from chalice.constants import MIN_COMPRESSION_SIZE
from chalice.constants import MAX_COMPRESSION_SIZE
from chalice.deploy.validate import validate_configuration
from chalice.deploy.validate import validate_routes
from chalice.deploy.validate import validate_python_version
from chalice.deploy.validate import validate_route_content_types
from chalice.deploy.validate import validate_unique_function_names
from chalice.deploy.validate import validate_feature_flags
from chalice.deploy.validate import validate_endpoint_type
from chalice.deploy.validate import validate_resource_policy
from chalice.deploy.validate import ExperimentalFeatureError


def test_trailing_slash_routes_result_in_error():
    app = Chalice('appname')
    app.routes = {'/trailing-slash/': None}
    config = Config.create(chalice_app=app)
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_empty_route_results_in_error():
    app = Chalice('appname')
    app.routes = {'': {}}
    config = Config.create(chalice_app=app)
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_validate_python_version_invalid():
    config = mock.Mock(spec=Config)
    config.lambda_python_version = 'python1.0'
    with pytest.warns(UserWarning):
        validate_python_version(config)


def test_python_version_invalid_from_real_config():
    config = Config.create()
    with pytest.warns(UserWarning):
        validate_python_version(config, 'python1.0')


def test_python_version_is_valid():
    config = Config.create()
    with pytest.warns(None) as record:
        validate_python_version(config, config.lambda_python_version)
    assert len(record) == 0


def test_manage_iam_role_false_requires_role_arn(sample_app):
    config = Config.create(chalice_app=sample_app, manage_iam_role=False,
                           iam_role_arn='arn:::foo')
    assert validate_configuration(config) is None


def test_validation_error_if_no_role_provided_when_manage_false(sample_app):
    # We're indicating that we should not be managing the
    # IAM role, but we're not giving a role ARN to use.
    # This is a validation error.
    config = Config.create(chalice_app=sample_app, manage_iam_role=False)
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_validate_unique_lambda_function_names(sample_app):
    @sample_app.lambda_function()
    def foo(event, context):
        pass

    # This will cause a validation error because
    # 'foo' is already registered as a lambda function.
    @sample_app.lambda_function(name='foo')
    def bar(event, context):
        pass

    config = Config.create(chalice_app=sample_app, manage_iam_role=False)
    with pytest.raises(ValueError):
        validate_unique_function_names(config)


def test_validate_names_across_function_types(sample_app):
    @sample_app.lambda_function()
    def foo(event, context):
        pass

    @sample_app.schedule('rate(1 hour)', name='foo')
    def bar(event):
        pass

    config = Config.create(chalice_app=sample_app, manage_iam_role=False)
    with pytest.raises(ValueError):
        validate_unique_function_names(config)


def test_validate_names_using_name_kwarg(sample_app):
    @sample_app.authorizer(name='duplicate')
    def foo(auth_request):
        pass

    @sample_app.lambda_function(name='duplicate')
    def bar(event):
        pass

    config = Config.create(chalice_app=sample_app, manage_iam_role=False)
    with pytest.raises(ValueError):
        validate_unique_function_names(config)


class TestValidateCORS(object):
    def test_cant_have_options_with_cors(self, sample_app):
        @sample_app.route('/badcors', methods=['GET', 'OPTIONS'], cors=True)
        def badview():
            pass

        with pytest.raises(ValueError):
            validate_routes(sample_app.routes)

    def test_cant_have_differing_cors_configurations(self, sample_app):
        custom_cors = CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )

        @sample_app.route('/cors', methods=['GET'], cors=True)
        def cors():
            pass

        @sample_app.route('/cors', methods=['PUT'], cors=custom_cors)
        def different_cors():
            pass

        with pytest.raises(ValueError):
            validate_routes(sample_app.routes)

    def test_can_have_same_cors_configurations(self, sample_app):
        @sample_app.route('/cors', methods=['GET'], cors=True)
        def cors():
            pass

        @sample_app.route('/cors', methods=['PUT'], cors=True)
        def same_cors():
            pass

        try:
            validate_routes(sample_app.routes)
        except ValueError:
            pytest.fail(
                'A ValueError was unexpectedly thrown. Applications '
                'may have multiple view functions that share the same '
                'route and CORS configuration.'
            )

    def test_can_have_same_custom_cors_configurations(self, sample_app):
        custom_cors = CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )

        @sample_app.route('/cors', methods=['GET'], cors=custom_cors)
        def cors():
            pass

        same_custom_cors = CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )

        @sample_app.route('/cors', methods=['PUT'], cors=same_custom_cors)
        def same_cors():
            pass

        try:
            validate_routes(sample_app.routes)
        except ValueError:
            pytest.fail(
                'A ValueError was unexpectedly thrown. Applications '
                'may have multiple view functions that share the same '
                'route and CORS configuration.'
            )

    def test_can_have_one_cors_configured_and_others_not(self, sample_app):
        @sample_app.route('/cors', methods=['GET'], cors=True)
        def cors():
            pass

        @sample_app.route('/cors', methods=['PUT'])
        def no_cors():
            pass

        try:
            validate_routes(sample_app.routes)
        except ValueError:
            pytest.fail(
                'A ValueError was unexpectedly thrown. Applications '
                'may have multiple view functions that share the same '
                'route but only one is configured for CORS.'
            )


def test_cant_have_mixed_content_types(sample_app):
    @sample_app.route('/index', content_types=['application/octet-stream',
                                               'text/plain'])
    def index():
        return {'hello': 'world'}

    with pytest.raises(ValueError):
        validate_route_content_types(sample_app.routes,
                                     sample_app.api.binary_types)


def test_can_validate_updated_custom_binary_types(sample_app):
    sample_app.api.binary_types.extend(['text/plain'])

    @sample_app.route('/index', content_types=['application/octet-stream',
                                               'text/plain'])
    def index():
        return {'hello': 'world'}

    assert validate_route_content_types(sample_app.routes,
                                        sample_app.api.binary_types) is None


def test_can_validate_resource_policy(sample_app):
    config = Config.create(
        chalice_app=sample_app, api_gateway_endpoint_type='PRIVATE')
    with pytest.raises(ValueError):
        validate_resource_policy(config)

    config = Config.create(
        chalice_app=sample_app,
        api_gateway_endpoint_vpce='vpce-abc123',
        api_gateway_endpoint_type='PRIVATE')
    validate_resource_policy(config)

    config = Config.create(
        chalice_app=sample_app,
        api_gateway_endpoint_vpce='vpce-abc123',
        api_gateway_endpoint_type='REGIONAL')
    with pytest.raises(ValueError):
        validate_resource_policy(config)

    config = Config.create(
        chalice_app=sample_app,
        api_gateway_policy_file='xyz.json',
        api_gateway_endpoint_type='PRIVATE')
    validate_resource_policy(config)

    config = Config.create(
        chalice_app=sample_app,
        api_gateway_endpoint_vpce=['vpce-abc123', 'vpce-bdef'],
        api_gateway_policy_file='bar.json',
        api_gateway_endpoint_type='PRIVATE')
    with pytest.raises(ValueError):
        validate_resource_policy(config)


def test_can_validate_endpoint_type(sample_app):
    config = Config.create(
        chalice_app=sample_app, api_gateway_endpoint_type='EDGE2')
    with pytest.raises(ValueError):
        validate_endpoint_type(config)

    config = Config.create(
        chalice_app=sample_app, api_gateway_endpoint_type='REGIONAL')
    validate_endpoint_type(config)


def test_can_validate_feature_flags(sample_app):
    # The _features_used is marked internal because we don't want
    # chalice users to access it, but this attribute is intended to be
    # accessed by anything within the chalice codebase.
    sample_app._features_used.add('SOME_NEW_FEATURE')
    with pytest.raises(ExperimentalFeatureError):
        validate_feature_flags(sample_app)
    # Now if we opt in, validation is fine.
    sample_app.experimental_feature_flags.add('SOME_NEW_FEATURE')
    try:
        validate_feature_flags(sample_app)
    except ExperimentalFeatureError:
        raise AssertionError("App was not suppose to raise an error when "
                             "opting in to features via a feature flag.")


def test_validation_error_if_minimum_compression_size_not_int(sample_app):
    config = Config.create(chalice_app=sample_app,
                           minimum_compression_size='not int')
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_validation_error_if_minimum_compression_size_invalid_int(sample_app):
    config = Config.create(chalice_app=sample_app,
                           minimum_compression_size=MIN_COMPRESSION_SIZE-1)
    with pytest.raises(ValueError):
        validate_configuration(config)

    config = Config.create(chalice_app=sample_app,
                           minimum_compression_size=MAX_COMPRESSION_SIZE+1)
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_valid_minimum_compression_size(sample_app):
    config = Config.create(chalice_app=sample_app,
                           minimum_compression_size=1)
    assert validate_configuration(config) is None


def test_validate_sqs_queue_name(sample_app):

    @sample_app.on_sqs_message(
        queue='https://sqs.us-west-2.amazonaws.com/12345/myqueue')
    def handler(event):
        pass

    config = Config.create(chalice_app=sample_app)
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_validate_environment_variables_value_type_not_str(sample_app):
    config = Config.create(chalice_app=sample_app,
                           environment_variables={"ENV_KEY": 1})
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_validate_unicode_is_valid_env_var(sample_app):
    config = Config.create(chalice_app=sample_app,
                           environment_variables={"ENV_KEY": u'unicode-val'})
    assert validate_configuration(config) is None


def test_validate_env_var_is_string_for_lambda_functions(sample_app):
    @sample_app.lambda_function()
    def foo(event, context):
        pass

    config = Config(
        chalice_stage='dev',
        config_from_disk={
            'stages': {
                'dev': {
                    'lambda_functions': {
                        'foo': {'environment_variables': {'BAR': 2}}}
                }
            }
        },
        user_provided_params={'chalice_app': sample_app}
    )
    with pytest.raises(ValueError):
        validate_configuration(config)
