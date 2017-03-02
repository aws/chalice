"""Deploy module for chalice apps.

Handles Lambda and API Gateway deployments.

"""
import json
import os
import uuid

import botocore.session  # noqa
from typing import Any, Tuple, Callable, List, Dict  # noqa

from chalice import app  # noqa
from chalice import policy
from chalice.awsclient import TypedAWSClient
from chalice.config import Config  # noqa
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.swagger import SwaggerGenerator
from chalice.utils import OSUtils

LAMBDA_TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "",
        "Effect": "Allow",
        "Principal": {
            "Service": "lambda.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
    }]
}


CLOUDWATCH_LOGS = {
    "Effect": "Allow",
    "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
    ],
    "Resource": "arn:aws:logs:*:*:*"
}


NULLARY = Callable[[], str]


def create_default_deployer(session, prompter=None):
    # type: (botocore.session.Session, NoPrompt) -> Deployer
    if prompter is None:
        prompter = NoPrompt()
    aws_client = TypedAWSClient(session)
    api_gateway_deploy = APIGatewayDeployer(aws_client)

    packager = LambdaDeploymentPackager()
    osutils = OSUtils()
    lambda_deploy = LambdaDeployer(
        aws_client, packager, prompter, osutils,
        ApplicationPolicyHandler(osutils))
    return Deployer(api_gateway_deploy, lambda_deploy)


def validate_configuration(config):
    # type: (Config) -> None
    """Validate app configuration.

    The purpose of this method is to provide a fail fast mechanism
    for anything we know is going to fail deployment.
    We can detect common error cases and provide the user with helpful
    error messages.

    """
    routes = config.chalice_app.routes
    validate_routes(routes)
    _validate_manage_iam_role(config)


def validate_routes(routes):
    # type: (Dict[str, Any]) -> None
    # We're trying to validate any kind of route that will fail
    # when we send the request to API gateway.
    # We check for:
    #
    # * any routes that end with a trailing slash.
    for route_name, route_entry in routes.items():
        if route_name != '/' and route_name.endswith('/'):
            raise ValueError("Route cannot end with a trailing slash: %s"
                             % route_name)
        if route_entry is not None:
            # This 'is not None' check is not strictly needed.
            # It's used because some of the tests don't populate
            # a route_entry when creating test routes.
            # This should be cleaned up.
            _validate_route_entry(route_name, route_entry)


def _validate_route_entry(route_url, route_entry):
    # type: (str, app.RouteEntry) -> None
    if route_entry.cors:
        # If the user has enabled CORS, they can't also have an OPTIONS method
        # because we'll create one for them.  API gateway will raise an error
        # about duplicate methods.
        if 'OPTIONS' in route_entry.methods:
            raise ValueError(
                "Route entry cannot have both cors=True and "
                "methods=['OPTIONS', ...] configured.  When "
                "CORS is enabled, an OPTIONS method is automatically "
                "added for you.  Please remove 'OPTIONS' from the list of "
                "configured HTTP methods for: %s" % route_url)


def _validate_manage_iam_role(config):
    # type: (Config) -> None
    # We need to check if manage_iam_role is None because that's the value
    # it the user hasn't specified this value.
    # However, if the manage_iam_role value is not None, the user set it
    # to something, in which case we care if they set it to False.
    if not config.manage_iam_role:
        # If they don't want us to manage the role, they
        # have to specify an iam_role_arn.
        if not config.iam_role_arn:
            raise ValueError(
                "When 'manage_iam_role' is set to false, you "
                "must provide an 'iam_role_arn' in config.json."
            )


class NoPrompt(object):
    def confirm(self, text, default=False, abort=False):
        # type: (str, bool, bool) -> bool
        return default


class Deployer(object):
    def __init__(self, apigateway_deploy, lambda_deploy):
        # type: (APIGatewayDeployer, LambdaDeployer) -> None
        self._apigateway_deploy = apigateway_deploy
        self._lambda_deploy = lambda_deploy

    def deploy(self, config):
        # type: (Config) -> Tuple[str, str, str]
        """Deploy chalice application to AWS.

        :type config: dict
        :param config: A dictionary of config values including:

            * project_dir - The directory containing the project
            * config - A dictionary of config values loaded from the
                project config file.

        """
        validate_configuration(config)
        self._lambda_deploy.deploy(config)
        rest_api_id, region_name, stage = self._apigateway_deploy.deploy(
            config)
        print (
            "https://{api_id}.execute-api.{region}.amazonaws.com/{stage}/"
            .format(api_id=rest_api_id, region=region_name, stage=stage)
        )
        return rest_api_id, region_name, stage


class ApplicationPolicyHandler(object):
    """Manages the IAM policy for an application."""

    _EMPTY_POLICY = {
        'Version': '2012-10-17',
        'Statement': [],
    }

    def __init__(self, osutils):
        # type: (OSUtils) -> None
        self._osutils = osutils

    def generate_policy_from_app_source(self, config):
        # type: (Config) -> Dict[str, Any]
        """Generate a policy from application source code.

        If the ``autogen_policy`` config option is set to false, then
        the .chalice/policy.json file will be used instead of generating
        the policy from the source code.

        """
        if config.autogen_policy:
            app_policy = self._do_generate_from_source(config)
        else:
            app_policy = self.load_last_policy(config)
        return app_policy

    def _do_generate_from_source(self, config):
        # type: (Config) -> Dict[str, Any]
        app_py = os.path.join(config.project_dir, 'app.py')
        assert self._osutils.file_exists(app_py)
        app_source = self._osutils.get_file_contents(app_py, binary=False)
        app_policy = policy.policy_from_source_code(app_source)
        app_policy['Statement'].append(CLOUDWATCH_LOGS)
        return app_policy

    def load_last_policy(self, config):
        # type: (Config) -> Dict[str, Any]
        """Load the last recorded policy file for the app.

        Whenever a policy is generated, the file is written to
        .chalice/policy.json.  This method will load that file
        and return the IAM policy.

        If the file does not exist, an empty policy is returned.

        """
        policy_file = self._app_policy_file(config)
        if not self._osutils.file_exists(policy_file):
            return self._EMPTY_POLICY
        return json.loads(
            self._osutils.get_file_contents(policy_file, binary=False)
        )

    def record_policy(self, config, policy):
        # type: (Config, Dict[str, Any]) -> None
        policy_file = self._app_policy_file(config)
        self._osutils.set_file_contents(
            policy_file,
            json.dumps(policy, indent=2, separators=(',', ': ')),
            binary=False
        )

    def _app_policy_file(self, config):
        # type: (Config) -> str
        policy_file = os.path.join(config.project_dir,
                                   '.chalice', 'policy.json')
        return policy_file


class LambdaDeployer(object):
    def __init__(self,
                 aws_client,   # type: TypedAWSClient
                 packager,     # type: LambdaDeploymentPackager
                 prompter,     # type: NoPrompt
                 osutils,      # type: OSUtils
                 app_policy,   # type: ApplicationPolicyHandler
                 ):
        # type: (...) -> None
        self._aws_client = aws_client
        self._packager = packager
        self._prompter = prompter
        self._osutils = osutils
        self._app_policy = app_policy

    def deploy(self, config):
        # type: (Config) -> None
        app_name = config.app_name
        if self._aws_client.lambda_function_exists(app_name):
            self._get_or_create_lambda_role_arn(config)
            self._update_lambda_function(config)
        else:
            function_arn = self._first_time_lambda_create(config)
            # Record the lambda_arn for later use.
            config.config_from_disk['lambda_arn'] = function_arn
            self._write_config_to_disk(config)
        print "Lambda deploy done."

    def _get_or_create_lambda_role_arn(self, config):
        # type: (Config) -> str
        if not config.manage_iam_role:
            # We've already validated the config, so we know
            # if manage_iam_role==False, then they've provided a
            # an iam_role_arn.
            return config.iam_role_arn

        app_name = config.app_name
        try:
            role_arn = self._aws_client.get_role_arn_for_name(app_name)
            self._update_role_with_latest_policy(app_name, config)
        except ValueError:
            print "Creating role"
            role_arn = self._create_role_from_source_code(config)
        return role_arn

    def _update_role_with_latest_policy(self, app_name, config):
        # type: (str, Config) -> None
        print "Updating IAM policy."
        app_policy = self._app_policy.generate_policy_from_app_source(config)
        previous = self._app_policy.load_last_policy(config)
        diff = policy.diff_policies(previous, app_policy)
        if diff:
            if diff.get('added', set([])):
                print ("\nThe following actions will be added to "
                       "the execution policy:\n")
                for action in diff['added']:
                    print action
            if diff.get('removed', set([])):
                print ("\nThe following action will be removed from "
                       "the execution policy:\n")
                for action in diff['removed']:
                    print action
            self._prompter.confirm("\nWould you like to continue? ",
                                   default=True, abort=True)
        self._aws_client.delete_role_policy(
            role_name=app_name, policy_name=app_name)
        self._aws_client.put_role_policy(role_name=app_name,
                                         policy_name=app_name,
                                         policy_document=app_policy)
        self._app_policy.record_policy(config, app_policy)

    def _first_time_lambda_create(self, config):
        # type: (Config) -> str
        # Creates a lambda function and returns the
        # function arn.
        # First we need to create a deployment package.
        print "Initial creation of lambda function."
        app_name = config.app_name
        role_arn = self._get_or_create_lambda_role_arn(config)
        zip_filename = self._packager.create_deployment_package(
            config.project_dir)
        with open(zip_filename, 'rb') as f:
            zip_contents = f.read()
        return self._aws_client.create_function(
            app_name, role_arn, zip_contents)

    def _update_lambda_function(self, config):
        # type: (Config) -> None
        print "Updating lambda function..."
        project_dir = config.project_dir
        packager = self._packager
        deployment_package_filename = packager.deployment_package_filename(
            project_dir)
        if self._osutils.file_exists(deployment_package_filename):
            packager.inject_latest_app(deployment_package_filename,
                                       project_dir)
        else:
            deployment_package_filename = packager.create_deployment_package(
                project_dir)
        zip_contents = self._osutils.get_file_contents(
            deployment_package_filename, binary=True)
        print "Sending changes to lambda."
        self._aws_client.update_function_code(config.app_name,
                                              zip_contents)

    def _write_config_to_disk(self, config):
        # type: (Config) -> None
        config_filename = os.path.join(config.project_dir,
                                       '.chalice', 'config.json')
        with open(config_filename, 'w') as f:
            f.write(json.dumps(config.config_from_disk, indent=2))

    def _create_role_from_source_code(self, config):
        # type: (Config) -> str
        app_name = config.app_name
        app_policy = self._app_policy.generate_policy_from_app_source(config)
        if len(app_policy['Statement']) > 1:
            print "The following execution policy will be used:"
            print json.dumps(app_policy, indent=2)
            self._prompter.confirm("Would you like to continue? ",
                                   default=True, abort=True)
        role_arn = self._aws_client.create_role(
            name=app_name,
            trust_policy=LAMBDA_TRUST_POLICY,
            policy=app_policy
        )
        self._app_policy.record_policy(config, app_policy)
        return role_arn


class APIGatewayDeployer(object):
    def __init__(self, aws_client):
        # type: (TypedAWSClient) -> None
        self._aws_client = aws_client

    def deploy(self, config):
        # type: (Config) -> Tuple[str, str, str]
        app_name = config.app_name
        rest_api_id = self._aws_client.get_rest_api_id(app_name)
        if rest_api_id is None:
            print "Initiating first time deployment..."
            return self._first_time_deploy(config)
        else:
            print "API Gateway rest API already found."
            return self._create_resources_for_api(config, rest_api_id)

    def _first_time_deploy(self, config):
        # type: (Config) -> Tuple[str, str, str]
        generator = SwaggerGenerator(self._aws_client.region_name,
                                     config.lambda_arn)
        swagger_doc = generator.generate_swagger(config.chalice_app)
        rest_api_id = self._aws_client.import_rest_api(swagger_doc)
        stage = config.stage or 'dev'
        self._deploy_api_to_stage(rest_api_id, stage, config)
        return rest_api_id, self._aws_client.region_name, stage

    def _create_resources_for_api(self, config, rest_api_id):
        # type: (Config, str) -> Tuple[str, str, str]
        generator = SwaggerGenerator(self._aws_client.region_name,
                                     config.lambda_arn)
        swagger_doc = generator.generate_swagger(config.chalice_app)
        self._aws_client.update_api_from_swagger(rest_api_id, swagger_doc)
        stage = config.stage or 'dev'
        self._deploy_api_to_stage(rest_api_id, stage, config)
        return rest_api_id, self._aws_client.region_name, stage

    def _deploy_api_to_stage(self, rest_api_id, stage, config):
        # type: (str, str, Config) -> None
        print "Deploying to:", stage
        self._aws_client.deploy_rest_api(rest_api_id, stage)
        self._aws_client.add_permission_for_apigateway_if_needed(
            config.lambda_arn.split(':')[-1],
            self._aws_client.region_name,
            config.lambda_arn.split(':')[4],
            rest_api_id,
            str(uuid.uuid4()),
        )
