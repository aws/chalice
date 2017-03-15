"""Simplified AWS client.

This module abstracts the botocore session and clients
to provide a simpler interface.  This interface only
contains the API calls needed to work with AWS services
used by chalice.

The interface provided can range from a direct 1-1 mapping
of a method to a method on a botocore client all the way up
to combining API calls across multiple AWS services.

As a side benefit, I can also add type annotations to
this class to get improved type checking across chalice.

"""
import os
import time
import tempfile
import zipfile
import shutil
import json

import botocore.session
import botocore.exceptions
from typing import Any, Optional, Dict, Callable  # noqa


class TypedAWSClient(object):

    # 30 * 5 == 150 seconds or 2.5 minutes for the initial lambda
    # creation + role propagation.
    LAMBDA_CREATE_ATTEMPTS = 30
    DELAY_TIME = 5

    def __init__(self, session, sleep=time.sleep):
        # type: (botocore.session.Session, Callable[[int], None]) -> None
        self._session = session
        self._sleep = sleep
        self._client_cache = {}
        # type: Dict[str, Any]

    def lambda_function_exists(self, name):
        # type: (str) -> bool
        try:
            self._client('lambda').get_function(FunctionName=name)
        except botocore.exceptions.ClientError as e:
            error = e.response['Error']
            if error['Code'] == 'ResourceNotFoundException':
                return False
            raise
        return True

    def create_function(self, function_name, role_arn, zip_contents):
        # type: (str, str, str) -> str
        kwargs = {
            'FunctionName': function_name,
            'Runtime': 'python2.7',
            'Code': {'ZipFile': zip_contents},
            'Handler': 'app.app',
            'Role': role_arn,
            'Timeout': 60,
        }
        client = self._client('lambda')
        attempts = 0
        while True:
            try:
                response = client.create_function(**kwargs)
            except botocore.exceptions.ClientError as e:
                code = e.response['Error'].get('Code')
                if code == 'InvalidParameterValueException':
                    # We're assuming that if we receive an
                    # InvalidParameterValueException, it's because
                    # the role we just created can't be used by
                    # Lambda.
                    self._sleep(self.DELAY_TIME)
                    attempts += 1
                    if attempts >= self.LAMBDA_CREATE_ATTEMPTS:
                        raise
                    continue
                raise
            return response['FunctionArn']

    def update_function_code(self, function_name, zip_contents):
        # type: (str, str) -> None
        self._client('lambda').update_function_code(
            FunctionName=function_name, ZipFile=zip_contents)

    def get_role_arn_for_name(self, name):
        # type: (str) -> str
        try:
            role = self._client('iam').get_role(RoleName=name)
        except botocore.exceptions.ClientError as e:
            error = e.response['Error']
            if error['Code'] == 'NoSuchEntity':
                raise ValueError("No role ARN found for: %s" % name)
            raise
        return role['Role']['Arn']

    def delete_role_policy(self, role_name, policy_name):
        # type: (str, str) -> None
        self._client('iam').delete_role_policy(RoleName=role_name,
                                               PolicyName=policy_name)

    def put_role_policy(self, role_name, policy_name, policy_document):
        # type: (str, str, Dict[str, Any]) -> None
        # Note: policy_document is not JSON encoded.
        self._client('iam').put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document, indent=2))

    def create_role(self, name, trust_policy, policy):
        # type: (str, Dict[str, Any], Dict[str, Any]) -> str
        client = self._client('iam')
        response = client.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
        role_arn = response['Role']['Arn']
        self.put_role_policy(role_name=name, policy_name=name,
                             policy_document=policy)
        return role_arn

    def get_rest_api_id(self, name):
        # type: (str) -> Optional[str]
        """Get rest api id associated with an API name.

        :type name: str
        :param name: The name of the rest api.

        :rtype: str
        :return: If the rest api exists, then the restApiId
            is returned, otherwise None.

        """
        rest_apis = self._client('apigateway').get_rest_apis()['items']
        for api in rest_apis:
            if api['name'] == name:
                return api['id']
        return None

    def create_rest_api(self, name):
        # type: (str) -> str
        response = self._client('apigateway').create_rest_api(name=name)
        return response['id']

    def get_root_resource_for_api(self, rest_api_id):
        # type: (str) -> Dict[str, Any]
        resources = [r for r in self.get_resources_for_api(rest_api_id)
                     if r['path'] == '/']
        root_resource = resources[0]
        return root_resource

    def get_resources_for_api(self, rest_api_id):
        # type: (str) -> List[Dict[str, Any]]
        client = self._client('apigateway')
        paginator = client.get_paginator('get_resources')
        pages = paginator.paginate(restApiId=rest_api_id)
        return pages.build_full_result()['items']

    def delete_methods_from_root_resource(self, rest_api_id, root_resource):
        # type: (str, Dict[str, Any]) -> None
        client = self._client('apigateway')
        methods = list(root_resource.get('resourceMethods', []))
        for method in methods:
            client.delete_method(restApiId=rest_api_id,
                                 resourceId=root_resource['id'],
                                 httpMethod=method)

    def delete_resource_for_api(self, rest_api_id, resource_id):
        # type: (str, str) -> None
        client = self._client('apigateway')
        client.delete_resource(restApiId=rest_api_id,
                               resourceId=resource_id)

    def deploy_rest_api(self, rest_api_id, stage_name):
        # type: (str, str) -> None
        client = self._client('apigateway')
        client.create_deployment(
            restApiId=rest_api_id,
            stageName=stage_name,
        )

    def create_rest_resource(self, rest_api_id, parent_id, path_part):
        # type: (str, str, str) -> Dict[str, Any]
        client = self._client('apigateway')
        response = client.create_resource(
            restApiId=rest_api_id,
            parentId=parent_id,
            pathPart=path_part,
        )
        return response

    def add_permission_for_apigateway_if_needed(self, function_name,
                                                region_name, account_id,
                                                rest_api_id, random_id):
        # type: (str, str, str, str, str) -> None
        """Authorize API gateway to invoke a lambda function is needed.

        This method will first check if API gateway has permission to call
        the lambda function, and only if necessary will it invoke
        ``self.add_permission_for_apigateway(...).

        """
        has_necessary_permissions = False
        try:
            policy = self.get_function_policy(function_name)
        except botocore.exceptions.ClientError as e:
            error = e.response['Error']
            if error['Code'] == 'ResourceNotFoundException':
                pass
        else:
            source_arn = self._build_source_arn_str(region_name, account_id,
                                                    rest_api_id)
            # Here's what a sample policy looks like after add_permission()
            # has been previously called:
            # {
            #  "Id": "default",
            #  "Statement": [
            #   {
            #    "Action": "lambda:InvokeFunction",
            #    "Condition": {
            #     "ArnLike": {
            #       "AWS:SourceArn": <source_arn>
            #     }
            #    },
            #    "Effect": "Allow",
            #    "Principal": {
            #     "Service": "apigateway.amazonaws.com"
            #    },
            #    "Resource": "arn:aws:lambda:us-west-2:aid:function:name",
            #    "Sid": "e4755709-067e-4254-b6ec-e7f9639e6f7b"
            #   }
            #  ],
            #  "Version": "2012-10-17"
            # }
            # So we need to check if there's a policy that looks like this.
            for statement in policy.get('Statement', []):
                if self._gives_apigateway_access(statement, function_name,
                                                 source_arn):
                    has_necessary_permissions = True
                    break
        if not has_necessary_permissions:
            self.add_permission_for_apigateway(
                function_name, region_name, account_id, rest_api_id, random_id)

    def _gives_apigateway_access(self, statement, function_name, source_arn):
        # type: (Dict[str, Any], str, str) -> bool
        if not statement['Action'] == 'lambda:InvokeFunction':
            return False
        if statement.get('Condition', {}).get('ArnLike',
                                              {}).get('AWS:SourceArn',
                                                      '') != source_arn:
            return False
        if statement.get('Principal', {}).get('Service', '') != \
                'apigateway.amazonaws.com':
            return False
        # We're not checking the "Resource" key because we're assuming
        # that lambda.get_policy() is returning the policy for the particular
        # resource in question.
        return True

    def get_function_policy(self, function_name):
        # type: (str) -> Dict[str, Any]
        """Return the function policy for a lambda function.

        This function will extract the policy string as a json document
        and return the json.loads(...) version of the policy.

        """
        client = self._client('lambda')
        policy = client.get_policy(FunctionName=function_name)
        return json.loads(policy['Policy'])

    def get_sdk_download_stream(self, rest_api_id, stage='dev',
                                sdk_type='javascript'):
        # type: (str, str, str) -> file
        """Generate an SDK for a given SDK.

        Returns a file like object that streams a zip contents for the
        generated SDK.

        """
        response = self._client('apigateway').get_sdk(
            restApiId=rest_api_id, stageName=stage, sdkType=sdk_type)
        return response['body']

    def download_sdk(self, rest_api_id, output_dir, stage='dev',
                     sdk_type='javascript'):
        # type: (str, str, str, str) -> None
        """Download an SDK to a directory.

        This will generate an SDK and download it to the provided
        ``output_dir``.  If you're using ``get_sdk_download_stream()``,
        you have to handle downloading the stream and unzipping the
        contents yourself.  This method handles that for you.

        """
        zip_stream = self.get_sdk_download_stream(
            rest_api_id, stage=stage, sdk_type=sdk_type)
        tmpdir = tempfile.mkdtemp()
        with open(os.path.join(tmpdir, 'sdk.zip'), 'wb') as f:
            f.write(zip_stream.read())
        tmp_extract = os.path.join(tmpdir, 'extracted')
        with zipfile.ZipFile(os.path.join(tmpdir, 'sdk.zip')) as z:
            z.extractall(tmp_extract)
        # The extract zip dir will have a single directory:
        #  ['apiGateway-js-sdk']
        dirnames = os.listdir(tmp_extract)
        if len(dirnames) == 1:
            full_dirname = os.path.join(tmp_extract, dirnames[0])
            if os.path.isdir(full_dirname):
                final_dirname = 'chalice-%s-sdk' % sdk_type
                full_renamed_name = os.path.join(tmp_extract, final_dirname)
                os.rename(full_dirname, full_renamed_name)
                shutil.move(full_renamed_name, output_dir)
                return
        raise RuntimeError(
            "The downloaded SDK had an unexpected directory structure: %s" %
            (', '.join(dirnames)))

    def add_permission_for_apigateway(self, function_name, region_name,
                                      account_id, rest_api_id, random_id):
        # type: (str, str, str, str, str) -> None
        """Authorize API gateway to invoke a lambda function."""
        client = self._client('lambda')
        source_arn = self._build_source_arn_str(region_name, account_id,
                                                rest_api_id)
        client.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName=function_name,
            StatementId=random_id,
            Principal='apigateway.amazonaws.com',
            SourceArn=source_arn,
        )

    def _build_source_arn_str(self, region_name, account_id, rest_api_id):
        # type: (str, str, str) -> str
        source_arn = (
            'arn:aws:execute-api:'
            '{region_name}:{account_id}:{rest_api_id}/*').format(
                region_name=region_name,
                # Assuming same account id for lambda function and API gateway.
                account_id=account_id,
                rest_api_id=rest_api_id)
        return source_arn

    @property
    def region_name(self):
        # type: () -> str
        return self._client('apigateway').meta.region_name

    def _client(self, service_name):
        # type: (str) -> Any
        if service_name not in self._client_cache:
            self._client_cache[service_name] = self._session.create_client(
                service_name)
        return self._client_cache[service_name]
