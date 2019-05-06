import copy

from typing import List, Dict, Any, Optional  # noqa

from chalice.config import Config  # noqa
from chalice import constants
from chalice import __version__ as chalice_version


class InvalidCodeBuildPythonVersion(Exception):
    def __init__(self, version):
        # type: (str) -> None
        super(InvalidCodeBuildPythonVersion, self).__init__(
            'CodeBuild does not yet support python version %s.' % version
        )


class PipelineParameters(object):
    def __init__(self, app_name, lambda_python_version,
                 codebuild_image=None, code_source='codecommit',
                 chalice_version_range=None):
        # type: (str, str, Optional[str], str, Optional[str]) -> None
        self.app_name = app_name
        self.lambda_python_version = lambda_python_version
        self.codebuild_image = codebuild_image
        self.code_source = code_source
        if chalice_version_range is None:
            chalice_version_range = self._lock_to_minor_version()
        self.chalice_version_range = chalice_version_range

    def _lock_to_minor_version(self):
        # type: () -> str
        parts = [int(p) for p in chalice_version.split('.')]
        min_version = '%s.%s.%s' % (parts[0], parts[1], 0)
        max_version = '%s.%s.%s' % (parts[0], parts[1] + 1, 0)
        return '>=%s,<%s' % (min_version, max_version)


class CreatePipelineTemplate(object):

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
        resources.extend([CodeBuild(), CodePipeline()])
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
        p['GithubPersonalToken'] = {
            'Type': 'String',
            'Description': 'Personal access token for the github repo.',
            'NoEcho': True,
        }


class CodeBuild(BaseResource):
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
                    "BuildSpec": self._get_default_buildspec(pipeline_params),
                }
            }
        }

    def _get_default_buildspec(self, pipeline_params):
        # type: (PipelineParameters) -> str
        return (
            "version: 0.1\n"
            "phases:\n"
            "  install:\n"
            "    commands:\n"
            "      - sudo pip install --upgrade awscli\n"
            "      - aws --version\n"
            "      - sudo pip install 'chalice%s'\n"
            "      - sudo pip install -r requirements.txt\n"
            "      - chalice package /tmp/packaged\n"
            "      - aws cloudformation package"
            " --template-file /tmp/packaged/sam.json"
            " --s3-bucket ${APP_S3_BUCKET}"
            " --output-template-file transformed.yaml\n"
            "artifacts:\n"
            "  type: zip\n"
            "  files:\n"
            "    - transformed.yaml\n"
        ) % pipeline_params.chalice_version_range

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
                                    "codebuild.amazonaws.com"
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
                                    "cloudformation.amazonaws.com"
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
        return self._github_source()

    def _github_source(self):
        # type: () -> Dict[str, Any]
        return {
            'Name': 'Source',
            'Actions': [{
                "ActionTypeId": {
                    "Category": "Source",
                    "Owner": "ThirdParty",
                    "Version": 1,
                    "Provider": "GitHub"
                },
                'RunOrder': 1,
                'OutputArtifacts': {
                    'Name': 'SourceRepo',
                },
                'Configuration': {
                    'Owner': {'Ref': 'GithubOwner'},
                    'Repo': {'Ref': 'GithubRepoName'},
                    'OAuthToken': {'Ref': 'GithubPersonalToken'},
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
                        "Version": 1,
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
                        "Version": 1,
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
                        "Version": 1,
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
                                    "codepipeline.amazonaws.com"
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
