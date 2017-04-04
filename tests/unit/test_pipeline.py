import pytest

from chalice import pipeline


@pytest.fixture
def pipeline_gen():
    return pipeline.CreatePipelineTemplate()


def test_app_name_in_param_default(pipeline_gen):
    template = pipeline_gen.create_template('appname')
    assert template['Parameters']['ApplicationName']['Default'] == 'appname'


def test_source_repo_resource(pipeline_gen):
    template = {}
    pipeline.SourceRepository().add_to_template(template)
    assert template == {
        "Resources": {
            "SourceRepository": {
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
        },
        "Outputs": {
            "SourceRepoURL": {
                "Value": {
                    "Fn::GetAtt": "SourceRepository.CloneUrlHttp"
                }
            }
        }
    }


def test_codebuild_resource(pipeline_gen):
    template = {}
    pipeline.CodeBuild().add_to_template(template)
    resources = template['Resources']
    assert 'ApplicationBucket' in resources
    assert 'CodeBuildRole' in resources
    assert 'CodeBuildPolicy' in resources
    assert 'AppPackageBuild' in resources
    assert resources['ApplicationBucket'] == {'Type': 'AWS::S3::Bucket'}
    assert template['Outputs']['CodeBuildRoleArn'] == {
        'Value': {'Fn::GetAtt': 'CodeBuildRole.Arn'}
    }


def test_codepipeline_resource(pipeline_gen):
    template = {}
    pipeline.CodePipeline().add_to_template(template)
    resources = template['Resources']
    assert 'AppPipeline' in resources
    assert 'ArtifactBucketStore' in resources
    assert 'CodePipelineRole' in resources
    assert 'CFNDeployRole' in resources
    # Some basic sanity checks
    resources['AppPipeline']['Type'] == 'AWS::CodePipeline::Pipeline'
    resources['ArtifactBucketStore']['Type'] == 'AWS::S3::Bucket'
    resources['CodePipelineRole']['Type'] == 'AWS::IAM::Role'
    resources['CFNDeployRole']['Type'] == 'AWS::IAM::Role'
