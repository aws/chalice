import pytest

from chalice import pipeline
from chalice.pipeline import InvalidCodeBuildPythonVersion


@pytest.fixture
def pipeline_gen():
    return pipeline.CreatePipelineTemplate()


class TestPipelineGen(object):

    def setup_method(self):
        self.pipeline_gen = pipeline.CreatePipelineTemplate()

    def generate_template(self, app_name='appname',
                          lambda_python_version='python2.7',
                          codebuild_image=None):
        template = self.pipeline_gen.create_template(
            app_name, lambda_python_version, codebuild_image)
        return template

    def test_app_name_in_param_default(self):
        template = self.generate_template(app_name='appname')
        assert template['Parameters']['ApplicationName']['Default'] == 'appname'

    def test_python_version_in_param_default(self):
        template = self.generate_template(lambda_python_version='python2.7')
        assert template['Parameters']['CodeBuildImage']['Default'] == \
            'aws/codebuild/python:2.7.12'

    def test_py3_throws_error(self):
        # This test can be removed when there is a 3.6 codebuild image available
        with pytest.raises(InvalidCodeBuildPythonVersion):
            self.generate_template('app', 'python3.6')

    def test_nonsense_py_version_throws_error(self):
        with pytest.raises(InvalidCodeBuildPythonVersion):
            self.generate_template('app', 'foobar')

    def test_can_provide_codebuild_image(self):
        template = self.generate_template('appname', 'python2.7',
                                          codebuild_image='python:3.6.1')
        default_image = template['Parameters']['CodeBuildImage']['Default']
        assert default_image == 'python:3.6.1'


def test_source_repo_resource():
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


def test_codebuild_resource():
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


def test_codepipeline_resource():
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


def test_install_requirements_in_buildspec():
    template = {}
    pipeline.CodeBuild().add_to_template(template)
    build = template['Resources']['AppPackageBuild']
    build_spec = build['Properties']['Source']['BuildSpec']
    assert 'pip install -r requirements.txt' in build_spec
