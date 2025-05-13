import copy
import re

from typing import List, Dict, Any, Optional, Callable  # noqa
import yaml

from chalice.config import Config  # noqa
from chalice import constants
from chalice import __version__ as chalice_version


def create_buildspec_v2(pipeline_params):
    # type: (PipelineParameters) -> Dict[str, Any]
    install_commands = [
        "pip install 'chalice%s'" % pipeline_params.chalice_version_range,
        "pip install -r requirements.txt",
    ]
    build_commands = [
        "chalice package /tmp/packaged",
        ("aws cloudformation package --template-file /tmp/packaged/sam.json "
         "--s3-bucket ${APP_S3_BUCKET} "
         "--output-template-file transformed.yaml")
    ]
    buildspec = {
        "version": "0.2",
        "phases": {
            "install": {
                "commands": install_commands,
                "runtime-versions": {
                    "python": pipeline_params.py_major_minor,
                }
            },
            "build": {
                "commands": build_commands,
            }
        },
        "artifacts": {
            "type": "zip",
            "files": [
                "transformed.yaml"
            ]
        }

    }
    return buildspec


def create_buildspec_legacy(pipeline_params):
    # type: (PipelineParameters) -> Dict[str, Any]
    install_commands = [
        'sudo pip install --upgrade awscli',
        'aws --version',
        "sudo pip install 'chalice%s'" % pipeline_params.chalice_version_range,
        'sudo pip install -r requirements.txt',
        'chalice package /tmp/packaged',
        ('aws cloudformation package '
            '--template-file /tmp/packaged/sam.json'
            ' --s3-bucket ${APP_S3_BUCKET} '
            '--output-template-file transformed.yaml'),
    ]
    buildspec = {
        'version': '0.1',
        'phases': {
            'install': {
                'commands': install_commands,
            }
        },
        'artifacts': {
            'type': 'zip',
            'files': ['transformed.yaml']
        }
    }
    return buildspec


class InvalidCodeBuildPythonVersion(Exception):
    def __init__(self, version, msg=None):
        # type: (str, Optional[str]) -> None
        if msg is None:
            msg = 'CodeBuild does not yet support python version %s.' % version
        super(InvalidCodeBuildPythonVersion, self).__init__(msg)


class PipelineParameters(object):

    _PYTHON_VERSION = re.compile('python(.+)')

    def __init__(self, app_name, lambda_python_version,
                 codebuild_image=None, code_source='codecommit',
                 chalice_version_range=None, pipeline_version='v1'):
        # type: (str, str, Optional[str], str, Optional[str], str) -> None
        self.app_name = app_name
        # lambda_python_version is what matches lambda, e.g. 'python3.9'.
        self.lambda_python_version = lambda_python_version
        # py_major_minor is just the version string, e.g. '3.9'
        self.py_major_minor = self._extract_version(lambda_python_version)
        self.codebuild_image = codebuild_image
        self.code_source = code_source
        if chalice_version_range is None:
            chalice_version_range = self._lock_to_minor_version()
        self.chalice_version_range = chalice_version_range
        self.pipeline_version = pipeline_version

    def _extract_version(self, lambda_python_version):
        # type: (str) -> str
        matched = self._PYTHON_VERSION.match(lambda_python_version)
        if matched is None:
            raise InvalidCodeBuildPythonVersion(lambda_python_version)
        return matched.group(1)

    def _lock_to_minor_version(self):
        # type: () -> str
        parts = [int(p) for p in chalice_version.split('.')]
        min_version = '%s.%s.%s' % (parts[0], parts[1], 0)
        max_version = '%s.%s.%s' % (parts[0], parts[1] + 1, 0)
        return '>=%s,<%s' % (min_version, max_version)


class BasePipelineTemplate(object):
    def create_template(self, pipeline_params):
        # type: (PipelineParameters) -> Dict[str, Any]
        raise NotImplementedError("create_template")


class CreatePipelineTemplateV2(BasePipelineTemplate):
    _BASE_TEMPLATE = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": {
            "ApplicationName": {
                "Default": "ChaliceApp",
                "Type": "String",
                "Description": "Enter the name of your application"
            },
            "CodeBuildImage": {
                "Default": "aws/codebuild/amazonlinux2-x86_64-standard:3.0",
                "Type": "String",
                "Description": "Name of codebuild image to use."
            }
        },
        "Resources": {},
        "Outputs": {},
    }

    def create_template(self, pipeline_params):
        # type: (PipelineParameters) -> Dict[str, Any]
        self._validate_python_version(pipeline_params.py_major_minor)
        t = copy.deepcopy(self._BASE_TEMPLATE)  # type: Dict[str, Any]
        params = t['Parameters']
        params['ApplicationName']['Default'] = pipeline_params.app_name
        resources = []  # type: List[BaseResource]
        if pipeline_params.code_source == 'github':
            resources.append(GithubSource())
        else:
            resources.append(CodeCommitSourceRepository())
        resources.extend([CodeBuild(create_buildspec_v2), CodePipeline()])
        for resource in resources:
            resource.add_to_template(t, pipeline_params)
        return t

    def _validate_python_version(self, python_version):
        # type: (str) -> None
        major, minor = [
            int(v) for v in python_version.split('.')
        ]
        if (major, minor) < (3, 9):
            raise InvalidCodeBuildPythonVersion(
                python_version,
                'This CodeBuild image does not support python version: %s' % (
                    python_version
                )
            )


class CreatePipelineTemplateLegacy(BasePipelineTemplate):

    _CODEBUILD_IMAGE = {
        'python2.7': 'python:2.7.12',
        'python3.6': 'python:3.6.5',
        'python3.7': 'python:3.7.1',
    }

    _BASE_TEMPLATE = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": {
            "ApplicationName": {
                "Default": "ChaliceApp",
                "Type": "String",
                "Description": "Enter the name of your application"
            },
            "CodeBuildImage": {
                "Default": "aws/codebuild/python:2.7.12",
                "Type": "String",
                "Description": "Name of codebuild image to use."
            }
        },
        "Resources": {},
        "Outputs": {},
    }

    def create_template(self, pipeline_params):
        # type: (PipelineParameters) -> Dict[str, Any]
        t = copy.deepcopy(self._BASE_TEMPLATE)  # type: Dict[str, Any]
        params = t['Parameters']
        params['ApplicationName']['Default'] = pipeline_params.app_name
        params['CodeBuildImage']['Default'] = self._get_codebuild_image(
            pipeline_params)

        resources = []  # type: List[BaseResource]
        if pipeline_params.code_source == 'github':
            resources.append(GithubSource())
        else:
            resources.append(CodeCommitSourceRepository())
        resources.extend([CodeBuild(create_buildspec_legacy), CodePipeline()])
        for resource in resources:
            resource.add_to_template(t, pipeline_params)
        return t

    def _get_codebuild_image(self, params):
        # type: (PipelineParameters) -> str
        if params.codebuild_image is not None:
            return params.codebuild_image
        try:
            image_suffix = self._CODEBUILD_IMAGE[params.lambda_python_version]
            return 'aws/codebuild/%s' % image_suffix
        except KeyError as e:
            raise InvalidCodeBuildPythonVersion(str(e))


class BaseResource(object):
    def add_to_template(self, template, pipeline_params):
        # type: (Dict[str, Any], PipelineParameters) -> None
        raise NotImplementedError("add_to_template")


class CodeCommitSourceRepository(BaseResource):
    def add_to_template(self, template, pipeline_params):
        # type: (Dict[str, Any], PipelineParameters) -> None
        resources = template.setdefault('Resources', {})
        resources['SourceRepository'] = {
            "Type": "AWS::CodeCommit::Repository",
            "Properties": {
                "RepositoryName": {
                    "Ref": "ApplicationName"
                },
                "RepositoryDescription": {
                    "Fn::Sub": "Source code for ${ApplicationName}"
                }
            }
        }
        template.setdefault('Outputs', {})['SourceRepoURL'] = {
            "Value": {
                "Fn::GetAtt": "SourceRepository.CloneUrlHttp"
            }
        }


class GithubSource(BaseResource):
    def add_to_template(self, template, pipeline_params):
        # type: (Dict[str, Any], PipelineParameters) -> None
        # For the github source, we don't create a github repo,
        # we just wire it up in the code pipeline.  The
        # only thing we add to the template are parameters
        # we reference in other resources later.
        p = template.setdefault('Parameters', {})
        p['GithubOwner'] = {
            'Type': 'String',
            'Description': 'The github owner or org name of the repository.',
        }
        p['GithubRepoName'] = {
            'Type': 'String',
            'Description': 'The name of the github repository.',
        }
        if pipeline_params.pipeline_version == 'v1':
            p['GithubPersonalToken'] = {
                'Type': 'String',
                'Description': 'Personal access token for the github repo.',
                'NoEcho': True,
            }
        else:
            p['GithubRepoSecretId'] = {
                'Type': 'String',
                'Default': 'GithubRepoAccess',
                'Description': (
                    'The name/ID of the SecretsManager secret that '
                    'contains the personal access token for the github repo.'
                )
            }
            p['GithubRepoSecretJSONKey'] = {
                'Type': 'String',
                'Default': 'OAuthToken',
                'Description': (
                    'The name of the JSON key in the SecretsManager secret '
                    'that contains the personal access token for the '
                    'github repo.'
                )
            }


class CodeBuild(BaseResource):
    def __init__(self, buildspec_generator=create_buildspec_legacy):
        # type: (Callable[[PipelineParameters], Dict[str, Any]]) -> None
        self._buildspec_generator = buildspec_generator

    def add_to_template(self, template, pipeline_params):
        # type: (Dict[str, Any], PipelineParameters) -> None
        resources = template.setdefault('Resources', {})
        outputs = template.setdefault('Outputs', {})
        # Used to store the application source when the SAM
        # template is packaged.
        self._add_s3_bucket(resources, outputs)
        self._add_codebuild_role(resources, outputs)
        self._add_codebuild_policy(resources)
        self._add_package_build(resources, pipeline_params)

    def _add_package_build(self, resources, pipeline_params):
        # type: (Dict[str, Any], PipelineParameters) -> None
        resources['AppPackageBuild'] = {
            "Type": "AWS::CodeBuild::Project",
            "Properties": {
                "Artifacts": {
                    "Type": "CODEPIPELINE"
                },
                "Environment": {
                    "ComputeType": "BUILD_GENERAL1_SMALL",
                    "Image": {
                        "Ref": "CodeBuildImage"
                    },
                    "Type": "LINUX_CONTAINER",
                    "EnvironmentVariables": [
                        {
                            "Name": "APP_S3_BUCKET",
                            "Value": {
                                "Ref": "ApplicationBucket"
                            }
                        }
                    ]
                },
                "Name": {
                    "Fn::Sub": "${ApplicationName}Build"
                },
                "ServiceRole": {
                    "Fn::GetAtt": "CodeBuildRole.Arn"
                },
                "Source": {
                    "Type": "CODEPIPELINE",
                    "BuildSpec": yaml.dump(
                        self._buildspec_generator(pipeline_params),
                    ),
                }
            }
        }

    def _add_s3_bucket(self, resources, outputs):
        # type: (Dict[str, Any], Dict[str, Any]) -> None
        resources['ApplicationBucket'] = {'Type': 'AWS::S3::Bucket'}
        outputs['S3ApplicationBucket'] = {
            'Value': {'Ref': 'ApplicationBucket'}
        }

    def _add_codebuild_role(self, resources, outputs):
        # type: (Dict[str, Any], Dict[str, Any]) -> None
        resources['CodeBuildRole'] = {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Action": [
                                "sts:AssumeRole"
                            ],
                            "Effect": "Allow",
                            "Principal": {
                                "Service": [
                                    {'Fn::Sub': 'codebuild.${AWS::URLSuffix}'}
                                ]
                            }
                        }
                    ]
                }
            }
        }
        outputs['CodeBuildRoleArn'] = {
            "Value": {
                "Fn::GetAtt": "CodeBuildRole.Arn"
            }
        }

    def _add_codebuild_policy(self, resources):
        # type: (Dict[str, Any]) -> None
        resources['CodeBuildPolicy'] = {
            "Type": "AWS::IAM::Policy",
            "Properties": {
                "PolicyName": "CodeBuildPolicy",
                "PolicyDocument": constants.CODEBUILD_POLICY,
                "Roles": [
                    {
                        "Ref": "CodeBuildRole"
                    }
                ]
            }
        }


class CodePipeline(BaseResource):
    def add_to_template(self, template, pipeline_params):
        # type: (Dict[str, Any], PipelineParameters) -> None
        resources = template.setdefault('Resources', {})
        outputs = template.setdefault('Outputs', {})
        self._add_pipeline(resources, pipeline_params)
        self._add_bucket_store(resources, outputs)
        self._add_codepipeline_role(resources, outputs)
        self._add_cfn_deploy_role(resources, outputs)

    def _add_cfn_deploy_role(self, resources, outputs):
        # type: (Dict[str, Any], Dict[str, Any]) -> None
        outputs['CFNDeployRoleArn'] = {
            'Value': {'Fn::GetAtt': 'CFNDeployRole.Arn'}
        }
        resources['CFNDeployRole'] = {
            'Type': 'AWS::IAM::Role',
            'Properties': {
                "Policies": [
                    {
                        "PolicyName": "DeployAccess",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Action": "*",
                                    "Resource": "*",
                                    "Effect": "Allow"
                                }
                            ]
                        }
                    }
                ],
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Action": [
                                "sts:AssumeRole"
                            ],
                            "Effect": "Allow",
                            "Principal": {
                                "Service": [
                                    {'Fn::Sub':
                                     'cloudformation.${AWS::URLSuffix}'}
                                ]
                            }
                        }
                    ]
                }
            }
        }

    def _add_pipeline(self, resources, pipeline_params):
        # type: (Dict[str, Any], PipelineParameters) -> None
        properties = {
            'Name': {
                'Fn::Sub': '${ApplicationName}Pipeline'
            },
            'ArtifactStore': {
                'Type': 'S3',
                'Location': {'Ref': 'ArtifactBucketStore'},
            },
            'RoleArn': {
                'Fn::GetAtt': 'CodePipelineRole.Arn',
            },
            'Stages': self._create_pipeline_stages(pipeline_params),
        }
        resources['AppPipeline'] = {
            'Type': 'AWS::CodePipeline::Pipeline',
            'Properties': properties
        }

    def _create_pipeline_stages(self, pipeline_params):
        # type: (PipelineParameters) -> List[Dict[str, Any]]
        # The goal is to eventually allow a user to configure
        # the various stages they want created. For now, there's
        # a fixed list.
        stages = []
        source = self._create_source_stage(pipeline_params)
        if source:
            stages.append(source)
        stages.extend([self._create_build_stage(), self._create_beta_stage()])
        return stages

    def _code_commit_source(self):
        # type: () -> Dict[str, Any]
        return {
            "Name": "Source",
            "Actions": [
                {
                    "ActionTypeId": {
                        "Category": "Source",
                        "Owner": "AWS",
                        "Version": 1,
                        "Provider": "CodeCommit"
                    },
                    "Configuration": {
                        "BranchName": "master",
                        "RepositoryName": {
                            "Fn::GetAtt": "SourceRepository.Name"
                        }
                    },
                    "OutputArtifacts": [
                        {
                            "Name": "SourceRepo"
                        }
                    ],
                    "RunOrder": 1,
                    "Name": "Source"
                }
            ]
        }

    def _create_source_stage(self, pipeline_params):
        # type: (PipelineParameters) -> Dict[str, Any]
        if pipeline_params.code_source == 'codecommit':
            return self._code_commit_source()
        return self._github_source(pipeline_params.pipeline_version)

    def _github_source(self, pipeline_version):
        # type: (str) -> Dict[str, Any]
        oauth_token = {'Ref': 'GithubPersonalToken'}  # type: Dict[str, Any]
        if pipeline_version == 'v2':
            oauth_token = {
                "Fn::Join": [
                    "", ["{{resolve:secretsmanager:",
                         {"Ref": "GithubRepoSecretId"},
                         ":SecretString:",
                         {"Ref": "GithubRepoSecretJSONKey"},
                         "}}"]
                ]
            }
        return {
            'Name': 'Source',
            'Actions': [{
                "Name": "Source",
                "ActionTypeId": {
                    "Category": "Source",
                    "Owner": "ThirdParty",
                    "Version": "1",
                    "Provider": "GitHub"
                },
                'RunOrder': 1,
                'OutputArtifacts': [{
                    'Name': 'SourceRepo',
                }],
                'Configuration': {
                    'Owner': {'Ref': 'GithubOwner'},
                    'Repo': {'Ref': 'GithubRepoName'},
                    'OAuthToken': oauth_token,
                    'Branch': 'master',
                    'PollForSourceChanges': True,
                }
            }],
        }

    def _create_build_stage(self):
        # type: () -> Dict[str, Any]
        return {
            "Name": "Build",
            "Actions": [
                {
                    "InputArtifacts": [
                        {
                            "Name": "SourceRepo"
                        }
                    ],
                    "Name": "CodeBuild",
                    "ActionTypeId": {
                        "Category": "Build",
                        "Owner": "AWS",
                        "Version": "1",
                        "Provider": "CodeBuild"
                    },
                    "OutputArtifacts": [
                        {
                            "Name": "CompiledCFNTemplate"
                        }
                    ],
                    "Configuration": {
                        "ProjectName": {
                            "Ref": "AppPackageBuild"
                        }
                    },
                    "RunOrder": 1
                }
            ]
        }

    def _create_beta_stage(self):
        # type: () -> Dict[str, Any]
        return {
            "Name": "Beta",
            "Actions": [
                {
                    "ActionTypeId": {
                        "Category": "Deploy",
                        "Owner": "AWS",
                        "Version": "1",
                        "Provider": "CloudFormation"
                    },
                    "InputArtifacts": [
                        {
                            "Name": "CompiledCFNTemplate"
                        }
                    ],
                    "Name": "CreateBetaChangeSet",
                    "Configuration": {
                        "ActionMode": "CHANGE_SET_REPLACE",
                        "ChangeSetName": {
                            "Fn::Sub": "${ApplicationName}ChangeSet"
                        },
                        "RoleArn": {
                            "Fn::GetAtt": "CFNDeployRole.Arn"
                        },
                        "Capabilities": "CAPABILITY_IAM",
                        "StackName": {
                            "Fn::Sub": "${ApplicationName}BetaStack"
                        },
                        "TemplatePath": "CompiledCFNTemplate::transformed.yaml"
                    },
                    "RunOrder": 1
                },
                {
                    "RunOrder": 2,
                    "ActionTypeId": {
                        "Category": "Deploy",
                        "Owner": "AWS",
                        "Version": "1",
                        "Provider": "CloudFormation"
                    },
                    "Configuration": {
                        "StackName": {
                            "Fn::Sub": "${ApplicationName}BetaStack"
                        },
                        "ActionMode": "CHANGE_SET_EXECUTE",
                        "ChangeSetName": {
                            "Fn::Sub": "${ApplicationName}ChangeSet"
                        },
                        "OutputFileName": "StackOutputs.json"
                    },
                    "Name": "ExecuteChangeSet",
                    "OutputArtifacts": [
                        {
                            "Name": "AppDeploymentValues"
                        }
                    ]
                }
            ]
        }

    def _add_bucket_store(self, resources, outputs):
        # type: (Dict[str, Any], Dict[str, Any]) -> None
        resources['ArtifactBucketStore'] = {
            'Type': 'AWS::S3::Bucket',
            'Properties': {
                'VersioningConfiguration': {
                    'Status': 'Enabled'
                }
            }
        }
        outputs['S3PipelineBucket'] = {
            'Value': {'Ref': 'ArtifactBucketStore'}
        }

    def _add_codepipeline_role(self, resources, outputs):
        # type: (Dict[str, Any], Dict[str, Any]) -> None
        outputs['CodePipelineRoleArn'] = {
            'Value': {'Fn::GetAtt': 'CodePipelineRole.Arn'}
        }
        resources['CodePipelineRole'] = {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "Policies": [
                    {
                        "PolicyName": "DefaultPolicy",
                        "PolicyDocument": constants.CODEPIPELINE_POLICY,
                    }
                ],
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Action": [
                                "sts:AssumeRole"
                            ],
                            "Effect": "Allow",
                            "Principal": {
                                "Service": [
                                    {'Fn::Sub': 'codepipeline'
                                                '.${AWS::URLSuffix}'}
                                ]
                            }
                        }
                    ]
                }
            }
        }


class BuildSpecExtractor(object):
    def extract_buildspec(self, template):
        # type: (Dict[str, Any]) -> str
        source = template['Resources']['AppPackageBuild'][
            'Properties']['Source']
        buildspec = source.pop('BuildSpec')
        return buildspec
