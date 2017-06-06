import copy

from typing import List, Dict, Any, Optional  # noqa

from chalice.config import Config  # noqa
from chalice import constants


def create_pipeline_template(config):
    # type: (Config) -> Dict[str, Any]
    pipeline = CreatePipelineTemplate()
    return pipeline.create_template(config.app_name,
                                    config.lambda_python_version)


class InvalidCodeBuildPythonVersion(Exception):
    def __init__(self, version):
        # type: (str) -> None
        super(InvalidCodeBuildPythonVersion, self).__init__(
            'CodeBuild does not yet support python version %s.' % version
        )


class CreatePipelineTemplate(object):

    _CODEBUILD_IMAGE = {
        'python2.7': 'python:2.7.12',
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
                "Default": "python:2.7.12",
                "Type": "String",
                "Description": "Name of codebuild image to use."
            }
        },
        "Resources": {},
        "Outputs": {},
    }

    def __init__(self):
        # type: () -> None
        pass

    def _codebuild_image(self, lambda_python_version):
        # type: (str) -> str
        try:
            image = self._CODEBUILD_IMAGE[lambda_python_version]
            return image
        except KeyError as e:
            raise InvalidCodeBuildPythonVersion(str(e))

    def create_template(self, app_name, python_lambda_version):
        # type: (str, str) -> Dict[str, Any]
        t = copy.deepcopy(self._BASE_TEMPLATE)  # type: Dict[str, Any]
        t['Parameters']['ApplicationName']['Default'] = app_name
        t['Parameters']['CodeBuildImage']['Default'] = self._codebuild_image(
            python_lambda_version)

        resources = [SourceRepository, CodeBuild, CodePipeline]
        for resource_cls in resources:
            resource_cls().add_to_template(t)
        return t


class BaseResource(object):
    def add_to_template(self, template):
        # type: (Dict[str, Any]) -> None
        raise NotImplementedError("add_to_template")


class SourceRepository(BaseResource):
    def add_to_template(self, template):
        # type: (Dict[str, Any]) -> None
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


class CodeBuild(BaseResource):
    def add_to_template(self, template):
        # type: (Dict[str, Any]) -> None
        resources = template.setdefault('Resources', {})
        outputs = template.setdefault('Outputs', {})
        # Used to store the application source when the SAM
        # template is packaged.
        self._add_s3_bucket(resources, outputs)
        self._add_codebuild_role(resources, outputs)
        self._add_codebuild_policy(resources)
        self._add_package_build(resources)

    def _add_package_build(self, resources):
        # type: (Dict[str, Any]) -> None
        resources['AppPackageBuild'] = {
            "Type": "AWS::CodeBuild::Project",
            "Properties": {
                "Artifacts": {
                    "Type": "CODEPIPELINE"
                },
                "Environment": {
                    "ComputeType": "BUILD_GENERAL1_SMALL",
                    "Image": {
                        "Fn::Join": [
                            "", ["aws/codebuild/", {"Ref": "PythonVersion"}]
                        ]
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
                    "BuildSpec": (
                        "version: 0.1\n"
                        "phases:\n"
                        "  install:\n"
                        "    commands:\n"
                        "      - sudo pip install --upgrade awscli\n"
                        "      - aws --version\n"
                        "      - sudo pip install chalice\n"
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
                    )
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
    def add_to_template(self, template):
        # type: (Dict[str, Any]) -> None
        resources = template.setdefault('Resources', {})
        outputs = template.setdefault('Outputs', {})
        self._add_pipeline(resources)
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

    def _add_pipeline(self, resources):
        # type: (Dict[str, Any]) -> None
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
            'Stages': self._create_pipeline_stages(),
        }
        resources['AppPipeline'] = {
            'Type': 'AWS::CodePipeline::Pipeline',
            'Properties': properties
        }

    def _create_pipeline_stages(self):
        # type: () -> List[Dict[str, Any]]
        # The goal is to eventually allow a user to configure
        # the various stages they want created. For now, there's
        # a fixed list.
        stages = [
            self._create_source_stage(),
            self._create_build_stage(),
            self._create_beta_stage(),
        ]
        return stages

    def _create_source_stage(self):
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
