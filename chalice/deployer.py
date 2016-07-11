"""Deploy module for chalice apps.

Handles Lambda and API Gateway deployments.

"""
import os
import uuid
import shutil
import json
import subprocess
import zipfile
import hashlib
import inspect
import time

from typing import Any, Tuple, Callable, Optional  # noqa
import botocore.session
import botocore.exceptions

import chalice
from chalice import app
from chalice import policy


LAMBDA_TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "",
        "Effect": "Allow",
        "Principal": {
            "Service": "lambda.amazonaws.com"
        },
        "Action": "sts:AssumeRole"}
    ]
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


FULL_PASSTHROUGH = """
#set($allParams = $input.params())
{
"body-json" : $input.json('$'),
"base64-body": "$util.base64Encode($input.body)",
"params" : {
#foreach($type in $allParams.keySet())
  #set($params = $allParams.get($type))
"$type" : {
  #foreach($paramName in $params.keySet())
  "$paramName" : "$util.escapeJavaScript($params.get($paramName))"
      #if($foreach.hasNext),#end
  #end
}
  #if($foreach.hasNext),#end
#end
},
"stage-variables" : {
#foreach($key in $stageVariables.keySet())
"$key" : "$util.escapeJavaScript($stageVariables.get($key))"
  #if($foreach.hasNext),#end
#end
},
"context" : {
  "account-id": "$context.identity.accountId",
  "api-id": "$context.apiId",
  "api-key": "$context.identity.apiKey",
  "authorizer-principal-id": "$context.authorizer.principalId",
  "caller": "$context.identity.caller",
  "cognito-authentication-provider": \
    "$context.identity.cognitoAuthenticationProvider",
  "cognito-authentication-type": "$context.identity.cognitoAuthenticationType",
  "cognito-identity-id": "$context.identity.cognitoIdentityId",
  "cognito-identity-pool-id": "$context.identity.cognitoIdentityPoolId",
  "http-method": "$context.httpMethod",
  "stage": "$context.stage",
  "source-ip": "$context.identity.sourceIp",
  "user": "$context.identity.user",
  "user-agent": "$context.identity.userAgent",
  "user-arn": "$context.identity.userArn",
  "request-id": "$context.requestId",
  "resource-id": "$context.resourceId",
  "resource-path": "$context.resourcePath"
  }
}
"""


ERROR_MAPPING = (
    "#set($inputRoot = $input.path('$'))"
    "{"
    '"Code": "$inputRoot.errorType",'
    '"Message": "$inputRoot.errorMessage"'
    "}"
)


def build_url_trie(routes):
    # type: (Dict[str, app.RouteEntry]) -> Dict[str, Any]
    """Create a URL trie based on request routes.

    :type routes: dict
    :param routes: A dict of routes.  Keys are the uri_pattern,
        values are the ``chalice.app.RouteEntry`` values.

    :rtype: dict
    :return: A prefix trie of URL patterns.

    """
    root = node('', '/')
    for route in routes:
        if route == '/':
            # '/foo'.split('/') == ['', 'foo']
            # '/foo/bar'.split('/') == ['', 'foo', 'bar']
            # '/'.split('/') == ['', ''] <----???
            # So we special case this to return what split('/')
            # should return for "/".
            parts = ['']
        else:
            parts = route.split('/')
        current = root
        for i, part in enumerate(parts):
            if part not in current['children']:
                if part == '':
                    uri_path = '/'
                else:
                    uri_path = '/'.join(parts[:i + 1])
                current['children'][part] = node(part, uri_path)
            current = current['children'][part]
        current['is_route'] = True
        current['route_entry'] = routes[route]
    return root['children'].values()[0]


def node(name, uri_path, is_route=False):
    # type: (str, str, bool) -> Dict[str, Any]
    return {
        'name': name,
        'uri_path': uri_path,
        'children': {},
        'resource_id': None,
        'parent_resource_id': None,
        'is_route': is_route,
        'route_entry': None,
    }


class NoPrompt(object):
    def confirm(self, text, default=False, abort=False):
        return default


class Deployer(object):

    LAMBDA_CREATE_ATTEMPTS = 5
    DELAY_TIME = 3

    def __init__(self, session=None, prompter=None):
        # type: (botocore.session.Session) -> None
        if session is None:
            session = botocore.session.get_session()
        if prompter is None:
            prompter = NoPrompt()
        self._session = session
        self._prompter = prompter
        self._client_cache = {}
        # type: Dict[str, Any]
        # Note: I'm using "Any" for clients until we figure out
        # a way to have concrete types for botocore clients.
        self._packager = LambdaDeploymentPackager()
        self._query = ResourceQuery(
            self._client('lambda'),
            self._client('apigateway'),
        )

    def _client(self, service_name):
        # type: (str) -> Any
        if service_name not in self._client_cache:
            self._client_cache[service_name] = self._session.create_client(
                service_name)
        return self._client_cache[service_name]

    def deploy(self, config):
        # type: (Dict[str, Any]) -> str
        """Deploy chalice application to AWS.

        :type config: dict
        :param config: A dictionary of config values including:

            * project_dir - The directory containing the project
            * config - A dictionary of config values loaded from the
                project config file.

        """
        self._deploy_lambda(config)
        rest_api_id, region_name, stage = self._deploy_api_gateway(config)
        print (
            "https://{api_id}.execute-api.{region}.amazonaws.com/{stage}/"
            .format(api_id=rest_api_id, region=region_name, stage=stage)
        )

    def _deploy_lambda(self, config):
        # type: (Dict[str, Any]) -> None
        app_config = config['config']
        app_name = app_config['app_name']
        if self._query.lambda_function_exists(app_name):
            self._get_or_create_lambda_role_arn(config)
            self._update_lambda_function(config)
        else:
            function_arn = self._first_time_lambda_create(config)
            # Record the lambda_arn for later use.
            config['config']['lambda_arn'] = function_arn
            self._write_config_to_disk(config)
        print "Lambda deploy done."

    def _update_lambda_function(self, config):
        # type: (Dict[str, Any]) -> None
        print "Updating lambda function..."
        project_dir = config['project_dir']
        packager = self._packager
        deployment_package_filename = packager.deployment_package_filename(
            project_dir)
        if os.path.isfile(deployment_package_filename):
            packager.inject_latest_app(deployment_package_filename,
                                       project_dir)
        else:
            deployment_package_filename = packager.create_deployment_package(
                project_dir)
        with open(deployment_package_filename, 'rb') as f:
            zip_contents = f.read()
            client = self._client('lambda')
            print "Sending changes to lambda."
            client.update_function_code(
                FunctionName=config['config']['app_name'],
                ZipFile=zip_contents)

    def _write_config_to_disk(self, config):
        # type: (Dict[str, Any]) -> None
        config_filename = os.path.join(config['project_dir'],
                                       '.chalice', 'config.json')
        with open(config_filename, 'w') as f:
            f.write(json.dumps(config['config'], indent=2))

    def _first_time_lambda_create(self, config):
        # type: (Dict[str, Any]) -> str
        # Creates a lambda function and returns the
        # function arn.
        # First we need to create a deployment package.
        print "Initial creation of lambda function."
        app_name = config['config']['app_name']
        role_arn = self._get_or_create_lambda_role_arn(config)
        zip_filename = self._packager.create_deployment_package(
            config['project_dir'])
        with open(zip_filename, 'rb') as f:
            zip_contents = f.read()
        return self._create_function(app_name, role_arn, zip_contents)

    def _create_function(self, app_name, role_arn, zip_contents):
        # type: (str, str, str) -> str
        # The first time we create a role, there's a delay between
        # role creation and being able to use the role in the
        # creat_function call.  If we see this error, we'll retry
        # a few times.
        client = self._client('lambda')
        current = 0
        while True:
            try:
                response = client.create_function(
                    FunctionName=app_name,
                    Runtime='python2.7',
                    Code={'ZipFile': zip_contents},
                    Handler='app.app',
                    Role=role_arn,
                    Timeout=60
                )
            except botocore.exceptions.ClientError as e:
                code = e.response['Error'].get('Code')
                if code == 'InvalidParameterValueException':
                    # We're assuming that if we receive an
                    # InvalidParameterValueException, it's because
                    # the role we just created can't be used by
                    # Lambda.
                    time.sleep(self.DELAY_TIME)
                    current += 1
                    if current >= self.LAMBDA_CREATE_ATTEMPTS:
                        raise
                    continue
                raise
            return response['FunctionArn']

    def _get_or_create_lambda_role_arn(self, config):
        # type: (Dict[str, Any]) -> str
        app_name = config['config']['app_name']
        try:
            role_arn = self._find_role_arn(app_name)
            self._update_role_with_latest_policy(app_name, config)
        except ValueError:
            print "Creating role"
            role_arn = self._create_role_from_source_code(config)
        return role_arn

    def _update_role_with_latest_policy(self, app_name, config):
        # type: (str, Dict[str, Any]) -> None
        print "Updating IAM policy."
        app_policy = self._get_policy_from_source_code(config)
        previous = self._load_last_policy(config)
        diff = policy.diff_policies(previous, app_policy)
        if diff:
            if diff.get('added', []):
                print ("\nThe following actions will be added to "
                       "the execution policy:\n")
                for action in diff['added']:
                    print action
            if diff.get('removed', []):
                print ("\nThe following action will be removed from "
                       "the execution policy:\n")
                for action in diff['removed']:
                    print action
            self._prompter.confirm("\nWould you like to continue? ",
                                   default=True, abort=True)
        iam = self._client('iam')
        iam.delete_role_policy(RoleName=app_name,
                               PolicyName=app_name)
        iam.put_role_policy(RoleName=app_name,
                            PolicyName=app_name,
                            PolicyDocument=json.dumps(app_policy, indent=2))
        self._record_policy(config, app_policy)

    def _get_policy_from_source_code(self, config):
        app_py = os.path.join(config['project_dir'], 'app.py')
        assert os.path.isfile(app_py)
        with open(app_py) as f:
            app_policy = policy.policy_from_source_code(f.read())
            app_policy['Statement'].append(CLOUDWATCH_LOGS)
            return app_policy

    def _create_role_from_source_code(self, config):
        # type: (Dict[str, Any]) -> str
        app_name = config['config']['app_name']
        app_policy = self._get_policy_from_source_code(config)
        if len(app_policy['Statement']) > 1:
            print "The following execution policy will be used:"
            print json.dumps(app_policy, indent=2)
            self._prompter.confirm("Would you like to continue? ",
                                   default=True, abort=True)
        iam = self._client('iam')
        role_arn = iam.create_role(
            RoleName=app_name,
            AssumeRolePolicyDocument=json.dumps(
                LAMBDA_TRUST_POLICY))['Role']['Arn']
        iam.put_role_policy(RoleName=app_name,
                            PolicyName=app_name,
                            PolicyDocument=json.dumps(app_policy, indent=2))
        self._record_policy(config, app_policy)
        return role_arn

    def _load_last_policy(self, config):
        policy_file = os.path.join(config['project_dir'],
                                   '.chalice', 'policy.json')
        if not os.path.isfile(policy_file):
            return {}
        with open(policy_file, 'r') as f:
            return json.loads(f.read())

    def _record_policy(self, config, policy):
        policy_file = os.path.join(config['project_dir'],
                                   '.chalice', 'policy.json')
        with open(policy_file, 'w') as f:
            f.write(json.dumps(policy, indent=2))

    def _find_role_arn(self, role_name):
        # type: (str) -> str
        response = self._client('iam').list_roles()
        for role in response.get('Roles', []):
            if role['RoleName'] == role_name:
                return role['Arn']
        raise ValueError("No role ARN found for: %s" % role_name)

    def _deploy_api_gateway(self, config):
        # type: (Dict[str, Any]) -> Tuple[str, str, str]
        # Perhaps move this into APIGatewayResourceCreator.
        app_name = config['config']['app_name']
        rest_api_id = self._query.get_rest_api_id(app_name)
        if rest_api_id is None:
            print "Initiating first time deployment..."
            return self._first_time_deploy(config)
        else:
            print "API Gateway rest API already found."
            self._remove_all_resources(rest_api_id)
            return self._create_resources_for_api(config, rest_api_id)

    def _remove_all_resources(self, rest_api_id):
        # type: (str) -> None
        client = self._client('apigateway')
        all_resources = client.get_resources(restApiId=rest_api_id)['items']
        first_tier_ids = [r['id'] for r in all_resources
                          if r['path'].count('/') == 1 and r['path'] != '/']
        print "Deleting root resource id"
        for resource_id in first_tier_ids:
            client.delete_resource(restApiId=rest_api_id,
                                   resourceId=resource_id)
        root_resource = [r for r in all_resources if r['path'] == '/'][0]
        # We can't delete the root resource, but we need to remove all the
        # existing methods otherwise we'll get 4xx from API gateway when we
        # try to add methods to the root resource on a redeploy.
        self._delete_root_methods(rest_api_id, root_resource)
        print "Done deleting existing resources."

    def _delete_root_methods(self, rest_api_id, root_resource):
        # type: (str, Dict[str, Any]) -> None
        client = self._client('apigateway')
        methods = list(root_resource.get('resourceMethods', []))
        for method in methods:
            client.delete_method(restApiId=rest_api_id,
                                 resourceId=root_resource['id'],
                                 httpMethod=method)

    def _lambda_uri(self, lambda_function_arn):
        # type: (str) -> str
        region_name = self._client('apigateway').meta.region_name
        api_version = '2015-03-31'
        return (
            "arn:aws:apigateway:{region_name}:lambda:path/{api_version}"
            "/functions/{lambda_arn}/invocations".format(
                region_name=region_name,
                api_version=api_version,
                lambda_arn=lambda_function_arn)
        )

    def _first_time_deploy(self, config):
        # type: (Dict[str, Any]) -> Tuple[str, str, str]
        app_name = config['config']['app_name']
        client = self._client('apigateway')
        rest_api_id = client.create_rest_api(name=app_name)['id']
        return self._create_resources_for_api(config, rest_api_id)

    def _create_resources_for_api(self, config, rest_api_id):
        # type: (Dict[str, Any], str) -> Tuple[str, str, str]
        client = self._client('apigateway')
        url_trie = build_url_trie(config['chalice_app'].routes)
        root_resource = client.get_resources(restApiId=rest_api_id)['items'][0]
        assert root_resource['path'] == u'/'
        resource_id = root_resource['id']
        route_builder = APIGatewayResourceCreator(
            client, self._client('lambda'), rest_api_id,
            config['config']['lambda_arn'])
        # This is a little confusing.  You need to specify the parent
        # resource to create a subresource, but you can't create the root
        # resource because you have to specify a parent id.  So API Gateway
        # automatically creates the root "/" resource for you. So we have
        # to query that via get_resources() and inject that into the
        # url_trie to indicate the builder shouldn't try to create the
        # resource.
        url_trie['resource_id'] = resource_id
        for child in url_trie['children']:
            url_trie['children'][child]['parent_resource_id'] = resource_id
        route_builder.build_resources(url_trie)
        # And finally, you need an actual deployment to deploy the changes to
        # API gateway.
        stage = config['config'].get('stage', 'dev')
        print "Deploying to:", stage
        client.create_deployment(
            restApiId=rest_api_id,
            stageName=stage,
        )
        return rest_api_id, client.meta.region_name, stage


class APIGatewayResourceCreator(object):
    """Create hierarchical resources in API gateway from chalice routes."""
    def __init__(self, client, lambda_client, rest_api_id, lambda_arn,
                 random_id_generator=lambda: str(uuid.uuid4())):
        # type: (Any, Any, str, str, Callable[[], str]) -> None
        #: botocore client for API gateway.
        self.client = client
        self.region_name = self.client.meta.region_name
        self.lambda_client = lambda_client
        self.rest_api_id = rest_api_id
        self.lambda_arn = lambda_arn
        self._random_id = random_id_generator

    def build_resources(self, chalice_trie):
        """Create API gateway resources from chalice routes.

        :type chalice_trie: dict
        :param chalice_trie: The trie of URLs from ``build_url_trie()``.

        """
        # type: Dict[str, Any] -> None
        # We need to create the parent resource before we can create
        # child resources, so we'll do a pre-order depth first traversal.
        stack = [chalice_trie]
        while stack:
            current = stack.pop()
            # If there's no resource_id we need to create it.
            if current['resource_id'] is None:
                assert current['parent_resource_id'] is not None, current
                response = self.client.create_resource(
                    restApiId=self.rest_api_id,
                    parentId=current['parent_resource_id'],
                    pathPart=current['name']
                )
                new_resource_id = response['id']
                current['resource_id'] = new_resource_id
                for child in current['children']:
                    current['children'][child]['parent_resource_id'] = \
                        new_resource_id
            if current['is_route']:
                assert current['route_entry'] is not None, current
                for http_method in current['route_entry'].methods:
                    self._configure_resource_route(current, http_method)
            for child in current['children']:
                stack.append(current['children'][child])
        # Add a catch all auth that says anything in this rest API can call
        # the lambda function.
        self.lambda_client.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName=self.lambda_arn.split(':')[-1],
            StatementId=self._random_id(),
            Principal='apigateway.amazonaws.com',
            SourceArn=('arn:aws:execute-api:{region_name}:{account_id}'
                       ':{rest_api_id}/*').format(
                region_name=self.region_name,
                # Assuming same account id for lambda function and API gateway.
                account_id=self.lambda_arn.split(':')[4],
                rest_api_id=self.rest_api_id),
        )

    def _configure_resource_route(self, node, http_method):
        # type: (Dict[str, Any], str) -> None
        c = self.client
        c.put_method(
            restApiId=self.rest_api_id,
            resourceId=node['resource_id'],
            httpMethod=http_method,
            authorizationType='NONE'
        )
        c.put_integration(
            restApiId=self.rest_api_id,
            resourceId=node['resource_id'],
            type='AWS',
            httpMethod=http_method,
            integrationHttpMethod='POST',
            # Request body will never be passed through to
            # the integration, if the Content-Type header
            # is not application/json.
            passthroughBehavior="NEVER",
            requestTemplates={
                'application/json': FULL_PASSTHROUGH,
            },
            uri=self._lambda_uri()
        )
        # Success case.
        c.put_integration_response(
            restApiId=self.rest_api_id,
            resourceId=node['resource_id'],
            httpMethod=http_method,
            statusCode='200',
            responseTemplates={'application/json': ''},
        )
        c.put_method_response(
            restApiId=self.rest_api_id,
            resourceId=node['resource_id'],
            httpMethod=http_method,
            statusCode='200',
            responseModels={'application/json': 'Empty'},
        )
        # And we have to create a pair for each error type.
        for error_cls in app.ALL_ERRORS:
            c.put_integration_response(
                restApiId=self.rest_api_id,
                resourceId=node['resource_id'],
                httpMethod=http_method,
                statusCode=str(error_cls.STATUS_CODE),
                selectionPattern=error_cls.__name__ + '.*',
                responseTemplates={'application/json': ERROR_MAPPING},
            )
            c.put_method_response(
                restApiId=self.rest_api_id,
                resourceId=node['resource_id'],
                httpMethod=http_method,
                statusCode=str(error_cls.STATUS_CODE),
                responseModels={'application/json': 'Empty'},
            )

    def _lambda_uri(self):
        # type: () -> str
        region_name = self.client.meta.region_name
        api_version = '2015-03-31'
        return (
            "arn:aws:apigateway:{region_name}:lambda:path/{api_version}"
            "/functions/{lambda_arn}/invocations".format(
                region_name=region_name,
                api_version=api_version,
                lambda_arn=self.lambda_arn)
        )


class LambdaDeploymentPackager(object):
    def __init__(self):
        pass

    def _verify_has_virtualenv(self):
        try:
            subprocess.check_output(['virtualenv', '--version'])
        except subprocess.CalledProcessError:
            raise RuntimeError("You have to have virtualenv installed.  "
                               "You can install virtualenv using: "
                               "'pip install virtualenv'")

    def create_deployment_package(self, project_dir):
        # type: (str) -> str
        print "Creating deployment package."
        # pip install -t doesn't work out of the box with homebrew and
        # python, so we're using virtualenvs instead which works in
        # more cases.
        venv_dir = os.path.join(project_dir, '.chalice', 'venv')
        self._verify_has_virtualenv()
        subprocess.check_output(['virtualenv', venv_dir])
        pip_exe = os.path.join(venv_dir, 'bin', 'pip')
        assert os.path.isfile(pip_exe)
        # Next install any requirements specified by the app.
        requirements_file = os.path.join(project_dir, 'requirements.txt')
        deployment_package_filename = self.deployment_package_filename(
            project_dir)
        if self._has_at_least_one_package(requirements_file) and not \
                os.path.isfile(deployment_package_filename):
            p = subprocess.Popen([pip_exe, 'install', '-r', requirements_file],
                                 stdout=subprocess.PIPE)
            p.communicate()
        python_dir = os.listdir(os.path.join(venv_dir, 'lib'))[0]
        deps_dir = os.path.join(venv_dir, 'lib', python_dir,
                                'site-packages')
        assert os.path.isdir(deps_dir)
        # Now we need to create a zip file and add in the site-packages
        # dir first, followed by the app_dir contents next.
        if not os.path.isdir(os.path.dirname(deployment_package_filename)):
            os.makedirs(os.path.dirname(deployment_package_filename))
        with zipfile.ZipFile(deployment_package_filename, 'w',
                             compression=zipfile.ZIP_DEFLATED) as z:
            self._add_py_deps(z, deps_dir)
            self._add_app_files(z, project_dir)
        return deployment_package_filename

    def _has_at_least_one_package(self, filename):
        # type: (str) -> bool
        if not os.path.isfile(filename):
            return False
        with open(filename, 'r') as f:
            # This is meant to be a best effort attempt.
            # This can return True and still have no packages
            # actually being specified, but those aren't common
            # cases.
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    return True
        return False

    def deployment_package_filename(self, project_dir):
        # type: (str) -> str
        # Computes the name of the deployment package zipfile
        # based on a hash of the requirements file.
        # This is done so that we only "pip install -r requirements.txt"
        # when we know there's new dependencies we need to install.
        requirements_file = os.path.join(project_dir, 'requirements.txt')
        hash_contents = self._hash_requirements_file(requirements_file)
        deployment_package_filename = os.path.join(
            project_dir, '.chalice', 'deployments', hash_contents + '.zip')
        return deployment_package_filename

    def _add_py_deps(self, zip, deps_dir):
        # type: (zipfile.ZipFile, str) -> None
        prefix_len = len(deps_dir) + 1
        for root, dirnames, filenames in os.walk(deps_dir):
            if root == deps_dir and 'chalice' in dirnames:
                # Don't include any chalice deps.  We cherry pick
                # what we want to include in _add_app_files.
                dirnames.remove('chalice')
            for filename in filenames:
                full_path = os.path.join(root, filename)
                zip_path = full_path[prefix_len:]
                zip.write(full_path, zip_path)

    def _add_app_files(self, zip, project_dir):
        # type: (zipfile.ZipFile, str) -> None
        # TODO: This will need to change in the future, but
        # for now we're just supporting an app.py file.
        chalice_router = inspect.getfile(app)
        if chalice_router.endswith('.pyc'):
            chalice_router = chalice_router[:-1]
        zip.write(chalice_router, 'chalice/app.py')

        chalice_init = inspect.getfile(chalice)
        if chalice_init.endswith('.pyc'):
            chalice_init = chalice_init[:-1]
        zip.write(chalice_router, 'chalice/__init__.py')

        zip.write(os.path.join(project_dir, 'app.py'),
                  'app.py')

    def _hash_requirements_file(self, filename):
        # type: (str) -> str
        if not os.path.isfile(filename):
            contents = ''
        else:
            with open(filename) as f:
                contents = f.read()
        return hashlib.md5(contents).hexdigest()

    def inject_latest_app(self, deployment_package_filename, project_dir):
        # type: (str, str) -> None
        """Inject latest version of chalice app into a zip package.

        This method takes a pre-created deployment package and injects
        in the latest chalice app code.  This is useful in the case where
        you have no new package deps but have updated your chalice app code.

        :type deployment_package_filename: str
        :param deployment_package_filename: The zipfile of the
            preexisting deployment package.

        :type project_dir: str
        :param project_dir: Path to chalice project dir.

        """
        # Use the premade zip file and replace the app.py file
        # with the latest version.  Python's zipfile does not have
        # a way to do this efficiently so we need to create a new
        # zip file that has all the same stuff except for the new
        # app file.
        # TODO: support more than just an app.py file.
        print "Regen deployment package..."
        tmpzip = deployment_package_filename + '.tmp.zip'
        with zipfile.ZipFile(deployment_package_filename, 'r') as inzip:
            with zipfile.ZipFile(tmpzip, 'w') as outzip:
                for el in inzip.infolist():
                    if el.filename == 'app.py':
                        continue
                    else:
                        contents = inzip.read(el.filename)
                        outzip.writestr(el, contents)
                # Then at the end, add back the app.py.
                app_py = os.path.join(project_dir, 'app.py')
                assert os.path.isfile(app_py), app_py
                outzip.write(app_py, 'app.py')
        shutil.move(tmpzip, deployment_package_filename)


class ResourceQuery(object):
    def __init__(self, lambda_client, apigateway_client):
        self._lambda_client = lambda_client
        self._apigateway_client = apigateway_client

    def lambda_function_exists(self, name):
        # type: (str) -> bool
        """Check if lambda function exists.

        :type name: str
        :param name: The name of the lambda function

        :rtype: bool
        :return: Returns true if a lambda function with the given
            name exists.

        """
        try:
            self._lambda_client.get_function(FunctionName=name)
        except botocore.exceptions.ClientError as e:
            error = e.response['Error']
            if error['Code'] == 'ResourceNotFoundException':
                return False
            raise
        return True

    def get_rest_api_id(self, name):
        # type: (str) -> Optional[str]
        """Get rest api id associated with an API name.

        :type name: str
        :param name: The name of the rest api.

        :rtype: str
        :return: If the rest api exists, then the restApiId
            is returned, otherwise None.

        """
        rest_apis = self._apigateway_client.get_rest_apis()['items']
        for api in rest_apis:
            if api['name'] == name:
                return api['id']
