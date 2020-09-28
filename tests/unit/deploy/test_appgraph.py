import pytest

from chalice.app import Chalice
from chalice.config import Config
from chalice.constants import LAMBDA_TRUST_POLICY
from chalice.deploy import models
from chalice.deploy.appgraph import ApplicationGraphBuilder, ChaliceBuildError
from chalice.deploy.deployer import BuildStage, PolicyGenerator
from chalice.utils import serialize_to_json, OSUtils


@pytest.fixture
def websocket_app_without_connect():
    app = Chalice('websocket-event-no-connect')

    @app.on_ws_message()
    def message(event):
        pass

    @app.on_ws_disconnect()
    def disconnect(event):
        pass

    return app


@pytest.fixture
def websocket_app_without_message():
    app = Chalice('websocket-event-no-message')

    @app.on_ws_connect()
    def connect(event):
        pass

    @app.on_ws_disconnect()
    def disconnect(event):
        pass

    return app


@pytest.fixture
def websocket_app_without_disconnect():
    app = Chalice('websocket-event-no-disconnect')

    @app.on_ws_connect()
    def connect(event):
        pass

    @app.on_ws_message()
    def message(event):
        pass

    return app


class TestApplicationGraphBuilder(object):

    def create_config(self, app, app_name='lambda-only',
                      iam_role_arn=None, policy_file=None,
                      api_gateway_stage='api',
                      autogen_policy=False, security_group_ids=None,
                      subnet_ids=None, reserved_concurrency=None, layers=None,
                      automatic_layer=False,
                      api_gateway_endpoint_type=None,
                      api_gateway_endpoint_vpce=None,
                      api_gateway_policy_file=None,
                      api_gateway_custom_domain=None,
                      websocket_api_custom_domain=None,
                      project_dir='.'):
        kwargs = {
            'chalice_app': app,
            'app_name': app_name,
            'project_dir': project_dir,
            'automatic_layer': automatic_layer,
            'api_gateway_stage': api_gateway_stage,
            'api_gateway_policy_file': api_gateway_policy_file,
            'api_gateway_endpoint_type': api_gateway_endpoint_type,
            'api_gateway_endpoint_vpce': api_gateway_endpoint_vpce,
            'api_gateway_custom_domain': api_gateway_custom_domain,
            'websocket_api_custom_domain': websocket_api_custom_domain,
        }
        if iam_role_arn is not None:
            # We want to use an existing role.
            # This will skip all the autogen-policy
            # and role creation.
            kwargs['manage_iam_role'] = False
            kwargs['iam_role_arn'] = 'role:arn'
        elif policy_file is not None:
            # Otherwise this setting is when a user wants us to
            # manage the role, but they've written a policy file
            # they'd like us to use.
            kwargs['autogen_policy'] = False
            kwargs['iam_policy_file'] = policy_file
        elif autogen_policy:
            kwargs['autogen_policy'] = True
        if security_group_ids is not None and subnet_ids is not None:
            kwargs['security_group_ids'] = security_group_ids
            kwargs['subnet_ids'] = subnet_ids
        if reserved_concurrency is not None:
            kwargs['reserved_concurrency'] = reserved_concurrency
        kwargs['layers'] = layers
        config = Config.create(**kwargs)
        return config

    def test_can_build_single_lambda_function_app(self,
                                                  sample_app_lambda_only):
        # This is the simplest configuration we can get.
        builder = ApplicationGraphBuilder()
        config = self.create_config(sample_app_lambda_only,
                                    automatic_layer=False,
                                    iam_role_arn='role:arn')
        application = builder.build(config, stage_name='dev')
        # The top level resource is always an Application.
        assert isinstance(application, models.Application)
        assert len(application.resources) == 1
        assert application.resources[0] == models.LambdaFunction(
            resource_name='myfunction',
            function_name='lambda-only-dev-myfunction',
            environment_variables={},
            runtime=config.lambda_python_version,
            handler='app.myfunction',
            tags=config.tags,
            timeout=None,
            memory_size=None,
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE),
            role=models.PreCreatedIAMRole('role:arn'),
            security_group_ids=[],
            subnet_ids=[],
            layers=[],
            reserved_concurrency=None,
            managed_layer=None,
            xray=None,
        )

    def test_can_build_single_lambda_function_app_with_managed_layer(
            self, sample_app_lambda_only):
        # This is the simplest configuration we can get.
        builder = ApplicationGraphBuilder()
        config = self.create_config(
            sample_app_lambda_only,
            iam_role_arn='role:arn', automatic_layer=True)
        application = builder.build(config, stage_name='dev')
        # The top level resource is always an Application.
        assert isinstance(application, models.Application)
        assert len(application.resources) == 1
        assert application.resources[0] == models.LambdaFunction(
            resource_name='myfunction',
            function_name='lambda-only-dev-myfunction',
            environment_variables={},
            runtime=config.lambda_python_version,
            handler='app.myfunction',
            tags=config.tags,
            timeout=None,
            memory_size=None,
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE),
            role=models.PreCreatedIAMRole('role:arn'),
            security_group_ids=[],
            subnet_ids=[],
            layers=[],
            managed_layer=models.LambdaLayer(
                resource_name='managed-layer',
                layer_name='lambda-only-dev-managed-layer',
                runtime=config.lambda_python_version,
                deployment_package=models.DeploymentPackage(
                    models.Placeholder.BUILD_STAGE,
                )
            ),
            reserved_concurrency=None,
            xray=None,
        )

    def test_all_lambda_functions_share_managed_layer(
            self, sample_app_lambda_only):

        @sample_app_lambda_only.lambda_function()
        def second(event, context):
            pass

        builder = ApplicationGraphBuilder()
        config = self.create_config(
            sample_app_lambda_only,
            iam_role_arn='role:arn', automatic_layer=True)
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 2
        first_layer = application.resources[0].managed_layer
        second_layer = application.resources[1].managed_layer
        assert first_layer == second_layer

    def test_can_build_lambda_function_with_layers(self,
                                                   sample_app_lambda_only):
        # This is the simplest configuration we can get.
        builder = ApplicationGraphBuilder()
        layers = ['arn:aws:lambda:us-east-1:111:layer:test_layer:1']
        config = self.create_config(sample_app_lambda_only,
                                    iam_role_arn='role:arn',
                                    layers=layers)
        application = builder.build(config, stage_name='dev')
        # The top level resource is always an Application.
        assert isinstance(application, models.Application)
        assert len(application.resources) == 1
        assert application.resources[0] == models.LambdaFunction(
            resource_name='myfunction',
            function_name='lambda-only-dev-myfunction',
            environment_variables={},
            runtime=config.lambda_python_version,
            handler='app.myfunction',
            tags=config.tags,
            timeout=None,
            memory_size=None,
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE),
            role=models.PreCreatedIAMRole('role:arn'),
            security_group_ids=[],
            subnet_ids=[],
            layers=layers,
            reserved_concurrency=None,
            xray=None,
        )

    def test_can_build_app_with_domain_name(self, sample_app):
        domain_name = {
            'domain_name': 'example.com',
            'tls_version': 'TLS_1_0',
            'certificate_arn': 'certificate_arn',
            'tags': {
                'some_key1': 'some_value1',
                'some_key2': 'some_value2'
            },
            'url_prefix': '/'
        }
        config = self.create_config(sample_app,
                                    app_name='rest-api-app',
                                    api_gateway_endpoint_type='REGIONAL',
                                    api_gateway_custom_domain=domain_name,
                                    )
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        rest_api = application.resources[0]
        assert isinstance(rest_api, models.RestAPI)
        domain_name = rest_api.domain_name
        api_mapping = domain_name.api_mapping
        assert isinstance(domain_name, models.DomainName)
        assert isinstance(api_mapping, models.APIMapping)
        assert api_mapping.mount_path == '(none)'

    def test_can_build_lambda_function_app_with_vpc_config(
            self, sample_app_lambda_only
    ):
        @sample_app_lambda_only.lambda_function()
        def foo(event, context):
            pass

        builder = ApplicationGraphBuilder()
        config = self.create_config(sample_app_lambda_only,
                                    iam_role_arn='role:arn',
                                    security_group_ids=['sg1', 'sg2'],
                                    subnet_ids=['sn1', 'sn2'])
        application = builder.build(config, stage_name='dev')

        assert application.resources[0] == models.LambdaFunction(
            resource_name='myfunction',
            function_name='lambda-only-dev-myfunction',
            environment_variables={},
            runtime=config.lambda_python_version,
            handler='app.myfunction',
            tags=config.tags,
            timeout=None,
            memory_size=None,
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE),
            role=models.PreCreatedIAMRole('role:arn'),
            security_group_ids=['sg1', 'sg2'],
            subnet_ids=['sn1', 'sn2'],
            layers=[],
            reserved_concurrency=None,
            xray=None,
        )

    def test_vpc_trait_added_when_vpc_configured(self, sample_app_lambda_only):
        @sample_app_lambda_only.lambda_function()
        def foo(event, context):
            pass

        builder = ApplicationGraphBuilder()
        config = self.create_config(sample_app_lambda_only,
                                    autogen_policy=True,
                                    security_group_ids=['sg1', 'sg2'],
                                    subnet_ids=['sn1', 'sn2'])
        application = builder.build(config, stage_name='dev')

        policy = application.resources[0].role.policy
        assert policy == models.AutoGenIAMPolicy(
            document=models.Placeholder.BUILD_STAGE,
            traits=set([models.RoleTraits.VPC_NEEDED]),
        )

    def test_exception_raised_when_missing_vpc_params(self,
                                                      sample_app_lambda_only):
        @sample_app_lambda_only.lambda_function()
        def foo(event, context):
            pass

        builder = ApplicationGraphBuilder()
        config = self.create_config(sample_app_lambda_only,
                                    iam_role_arn='role:arn',
                                    security_group_ids=['sg1', 'sg2'],
                                    subnet_ids=[])
        with pytest.raises(ChaliceBuildError):
            builder.build(config, stage_name='dev')

    def test_can_build_lambda_function_app_with_reserved_concurrency(
            self, sample_app_lambda_only):
        # This is the simplest configuration we can get.
        builder = ApplicationGraphBuilder()
        config = self.create_config(sample_app_lambda_only,
                                    iam_role_arn='role:arn',
                                    reserved_concurrency=5)
        application = builder.build(config, stage_name='dev')
        # The top level resource is always an Application.
        assert isinstance(application, models.Application)
        assert len(application.resources) == 1
        assert application.resources[0] == models.LambdaFunction(
            resource_name='myfunction',
            function_name='lambda-only-dev-myfunction',
            environment_variables={},
            runtime=config.lambda_python_version,
            handler='app.myfunction',
            tags=config.tags,
            timeout=None,
            memory_size=None,
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE),
            role=models.PreCreatedIAMRole('role:arn'),
            security_group_ids=[],
            subnet_ids=[],
            layers=[],
            reserved_concurrency=5,
            xray=None,
        )

    def test_multiple_lambda_functions_share_role_and_package(
            self, sample_app_lambda_only):
        # We're going to add another lambda_function to our app.
        @sample_app_lambda_only.lambda_function()
        def bar(event, context):
            return {}

        builder = ApplicationGraphBuilder()
        config = self.create_config(sample_app_lambda_only,
                                    iam_role_arn='role:arn')
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 2
        # The lambda functions by default share the same role
        assert application.resources[0].role == application.resources[1].role
        # Not just in equality but the exact same role objects.
        assert application.resources[0].role is application.resources[1].role
        # And all lambda functions share the same deployment package.
        assert (application.resources[0].deployment_package ==
                application.resources[1].deployment_package)

    def test_autogen_policy_for_function(self, sample_app_lambda_only):
        # This test is just a sanity test that verifies all the params
        # for an ManagedIAMRole.  The various combinations for role
        # configuration is all tested via RoleTestCase.
        config = self.create_config(sample_app_lambda_only,
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        function = application.resources[0]
        role = function.role
        # We should have linked a ManagedIAMRole
        assert isinstance(role, models.ManagedIAMRole)
        assert role == models.ManagedIAMRole(
            resource_name='default-role',
            role_name='lambda-only-dev',
            trust_policy=LAMBDA_TRUST_POLICY,
            policy=models.AutoGenIAMPolicy(models.Placeholder.BUILD_STAGE),
        )

    def test_cloudwatch_event_models(self, sample_cloudwatch_event_app):
        config = self.create_config(sample_cloudwatch_event_app,
                                    app_name='cloudwatch-event',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        event = application.resources[0]
        assert isinstance(event, models.CloudWatchEvent)
        assert event.resource_name == 'foo-event'
        assert event.rule_name == 'cloudwatch-event-dev-foo-event'
        assert isinstance(event.lambda_function, models.LambdaFunction)
        assert event.lambda_function.resource_name == 'foo'

    def test_scheduled_event_models(self, sample_app_schedule_only):
        config = self.create_config(sample_app_schedule_only,
                                    app_name='scheduled-event',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        event = application.resources[0]
        assert isinstance(event, models.ScheduledEvent)
        assert event.resource_name == 'cron-event'
        assert event.rule_name == 'scheduled-event-dev-cron-event'
        assert isinstance(event.lambda_function, models.LambdaFunction)
        assert event.lambda_function.resource_name == 'cron'

    def test_can_build_private_rest_api(self, sample_app):
        config = self.create_config(sample_app,
                                    app_name='sample-app',
                                    api_gateway_endpoint_type='PRIVATE',
                                    api_gateway_endpoint_vpce='vpce-abc123')
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        rest_api = application.resources[0]
        assert isinstance(rest_api, models.RestAPI)
        assert rest_api.policy.document == {
            'Version': '2012-10-17',
            'Statement': [
                {'Action': 'execute-api:Invoke',
                 'Effect': 'Allow',
                 'Principal': '*',
                 'Resource': 'arn:*:execute-api:*:*:*',
                 'Condition': {
                     'StringEquals': {
                         'aws:SourceVpce': 'vpce-abc123'}}},
            ]
        }

    def test_can_build_private_rest_api_custom_policy(
            self, tmpdir, sample_app):
        config = self.create_config(sample_app,
                                    app_name='rest-api-app',
                                    api_gateway_policy_file='foo.json',
                                    api_gateway_endpoint_type='PRIVATE',
                                    project_dir=str(tmpdir))
        tmpdir.mkdir('.chalice').join('foo.json').write(
            serialize_to_json({'Version': '2012-10-17', 'Statement': []}))
        application_builder = ApplicationGraphBuilder()
        build_stage = BuildStage(
            steps=[
                PolicyGenerator(osutils=OSUtils(), policy_gen=None)
            ]
         )
        application = application_builder.build(config, stage_name='dev')
        build_stage.execute(config, application.resources)
        rest_api = application.resources[0]
        assert rest_api.policy.document == {
                'Version': '2012-10-17', 'Statement': []
            }

    def test_can_build_rest_api(self, sample_app):
        config = self.create_config(sample_app,
                                    app_name='sample-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        rest_api = application.resources[0]
        assert isinstance(rest_api, models.RestAPI)
        assert rest_api.resource_name == 'rest_api'
        assert rest_api.api_gateway_stage == 'api'
        assert rest_api.lambda_function.resource_name == 'api_handler'
        assert rest_api.lambda_function.function_name == 'sample-app-dev'
        # The swagger document is validated elsewhere so we just
        # make sure it looks right.
        assert rest_api.swagger_doc == models.Placeholder.BUILD_STAGE

    def test_can_build_rest_api_with_authorizer(self, sample_app_with_auth):
        config = self.create_config(sample_app_with_auth,
                                    app_name='rest-api-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        rest_api = application.resources[0]
        assert len(rest_api.authorizers) == 1
        assert isinstance(rest_api.authorizers[0], models.LambdaFunction)

    def test_can_create_s3_event_handler(self, sample_s3_event_app):
        # TODO: don't require app name, get it from app obj.
        config = self.create_config(sample_s3_event_app,
                                    app_name='s3-event-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        s3_event = application.resources[0]
        assert isinstance(s3_event, models.S3BucketNotification)
        assert s3_event.resource_name == 'handler-s3event'
        assert s3_event.bucket == 'mybucket'
        assert s3_event.events == ['s3:ObjectCreated:*']
        lambda_function = s3_event.lambda_function
        assert lambda_function.resource_name == 'handler'
        assert lambda_function.handler == 'app.handler'

    def test_can_create_sns_event_handler(self, sample_sns_event_app):
        config = self.create_config(sample_sns_event_app,
                                    app_name='s3-event-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        sns_event = application.resources[0]
        assert isinstance(sns_event, models.SNSLambdaSubscription)
        assert sns_event.resource_name == 'handler-sns-subscription'
        assert sns_event.topic == 'mytopic'
        lambda_function = sns_event.lambda_function
        assert lambda_function.resource_name == 'handler'
        assert lambda_function.handler == 'app.handler'

    def test_can_create_sqs_event_handler(self, sample_sqs_event_app):
        config = self.create_config(sample_sqs_event_app,
                                    app_name='sqs-event-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        sqs_event = application.resources[0]
        assert isinstance(sqs_event, models.SQSEventSource)
        assert sqs_event.resource_name == 'handler-sqs-event-source'
        assert sqs_event.queue == 'myqueue'
        lambda_function = sqs_event.lambda_function
        assert lambda_function.resource_name == 'handler'
        assert lambda_function.handler == 'app.handler'

    def test_can_create_kinesis_event_handler(self, sample_kinesis_event_app):
        config = self.create_config(sample_kinesis_event_app,
                                    app_name='kinesis-event-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        kinesis_event = application.resources[0]
        assert isinstance(kinesis_event, models.KinesisEventSource)
        assert kinesis_event.resource_name == 'handler-kinesis-event-source'
        assert kinesis_event.stream == 'mystream'
        lambda_function = kinesis_event.lambda_function
        assert lambda_function.resource_name == 'handler'
        assert lambda_function.handler == 'app.handler'

    def test_can_create_ddb_event_handler(self, sample_ddb_event_app):
        config = self.create_config(sample_ddb_event_app,
                                    app_name='ddb-event-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        ddb_event = application.resources[0]
        assert isinstance(ddb_event, models.DynamoDBEventSource)
        assert ddb_event.resource_name == 'handler-dynamodb-event-source'
        assert ddb_event.stream_arn == 'arn:aws:...:stream'
        lambda_function = ddb_event.lambda_function
        assert lambda_function.resource_name == 'handler'
        assert lambda_function.handler == 'app.handler'

    def test_can_create_websocket_event_handler(self, sample_websocket_app):
        config = self.create_config(sample_websocket_app,
                                    app_name='websocket-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        websocket_api = application.resources[0]
        assert isinstance(websocket_api, models.WebsocketAPI)
        assert websocket_api.resource_name == 'websocket_api'
        assert sorted(websocket_api.routes) == sorted(
            ['$connect', '$default', '$disconnect'])
        assert websocket_api.api_gateway_stage == 'api'

        connect_function = websocket_api.connect_function
        assert connect_function.resource_name == 'websocket_connect'
        assert connect_function.handler == 'app.connect'

        message_function = websocket_api.message_function
        assert message_function.resource_name == 'websocket_message'
        assert message_function.handler == 'app.message'

        disconnect_function = websocket_api.disconnect_function
        assert disconnect_function.resource_name == 'websocket_disconnect'
        assert disconnect_function.handler == 'app.disconnect'

    def test_can_create_websocket_api_with_domain_name(self,
                                                       sample_websocket_app):
        domain_name = {
            'domain_name': 'example.com',
            'tls_version': 'TLS_1_2',
            'certificate_arn': 'certificate_arn',
            'tags': {
                'tag_key1': 'tag_value1',
                'tag_key2': 'tag_value2'
            }
        }
        config = self.create_config(sample_websocket_app,
                                    app_name='websocket-app',
                                    autogen_policy=True,
                                    websocket_api_custom_domain=domain_name)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        websocket_api = application.resources[0]
        assert isinstance(websocket_api, models.WebsocketAPI)

        domain_name = websocket_api.domain_name
        assert isinstance(domain_name, models.DomainName)
        assert isinstance(domain_name.api_mapping, models.APIMapping)
        assert domain_name.api_mapping.mount_path == '(none)'

    def test_can_create_websocket_app_missing_connect(
            self, websocket_app_without_connect):
        config = self.create_config(websocket_app_without_connect,
                                    app_name='websocket-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        websocket_api = application.resources[0]
        assert isinstance(websocket_api, models.WebsocketAPI)
        assert websocket_api.resource_name == 'websocket_api'
        assert sorted(websocket_api.routes) == sorted(
            ['$default', '$disconnect'])
        assert websocket_api.api_gateway_stage == 'api'

        connect_function = websocket_api.connect_function
        assert connect_function is None

        message_function = websocket_api.message_function
        assert message_function.resource_name == 'websocket_message'
        assert message_function.handler == 'app.message'

        disconnect_function = websocket_api.disconnect_function
        assert disconnect_function.resource_name == 'websocket_disconnect'
        assert disconnect_function.handler == 'app.disconnect'

    def test_can_create_websocket_app_missing_message(
            self, websocket_app_without_message):
        config = self.create_config(websocket_app_without_message,
                                    app_name='websocket-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        websocket_api = application.resources[0]
        assert isinstance(websocket_api, models.WebsocketAPI)
        assert websocket_api.resource_name == 'websocket_api'
        assert sorted(websocket_api.routes) == sorted(
            ['$connect', '$disconnect'])
        assert websocket_api.api_gateway_stage == 'api'

        connect_function = websocket_api.connect_function
        assert connect_function.resource_name == 'websocket_connect'
        assert connect_function.handler == 'app.connect'

        disconnect_function = websocket_api.disconnect_function
        assert disconnect_function.resource_name == 'websocket_disconnect'
        assert disconnect_function.handler == 'app.disconnect'

    def test_can_create_websocket_app_missing_disconnect(
            self, websocket_app_without_disconnect):
        config = self.create_config(websocket_app_without_disconnect,
                                    app_name='websocket-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        websocket_api = application.resources[0]
        assert isinstance(websocket_api, models.WebsocketAPI)
        assert websocket_api.resource_name == 'websocket_api'
        assert sorted(websocket_api.routes) == sorted(
            ['$connect', '$default'])
        assert websocket_api.api_gateway_stage == 'api'

        connect_function = websocket_api.connect_function
        assert connect_function.resource_name == 'websocket_connect'
        assert connect_function.handler == 'app.connect'

        message_function = websocket_api.message_function
        assert message_function.resource_name == 'websocket_message'
        assert message_function.handler == 'app.message'
