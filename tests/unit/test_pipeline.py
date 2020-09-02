import pytest

from chalice import pipeline
from chalice import __version__ as chalice_version
from chalice.pipeline import InvalidCodeBuildPythonVersion, PipelineParameters


@pytest.fixture
def pipeline_gen():
    return pipeline.CreatePipelineTemplateLegacy()


@pytest.fixture
def pipeline_params():
    return pipeline.PipelineParameters('appname', 'python2.7')


class TestPipelineGenLegacy(object):

    def setup_method(self):
        self.pipeline_gen = pipeline.CreatePipelineTemplateLegacy()

    def generate_template(self, app_name='appname',
                          lambda_python_version='python2.7',
                          codebuild_image=None, code_source='codecommit'):
        params = PipelineParameters(
            app_name=app_name,
            lambda_python_version=lambda_python_version,
            codebuild_image=codebuild_image,
            code_source=code_source,
        )
        template = self.pipeline_gen.create_template(params)
        return template

    def test_app_name_in_param_default(self):
        template = self.generate_template(app_name='app')
        assert template['Parameters']['ApplicationName']['Default'] == 'app'

    def test_python_version_in_param_default(self):
        template = self.generate_template(lambda_python_version='python2.7')
        assert template['Parameters']['CodeBuildImage']['Default'] == \
            'aws/codebuild/python:2.7.12'

    def test_python_36_in_param_default(self):
        template = self.generate_template(lambda_python_version='python3.6')
        assert template['Parameters']['CodeBuildImage']['Default'] == \
            'aws/codebuild/python:3.6.5'

    def test_invalid_python_throws_error(self):
        with pytest.raises(InvalidCodeBuildPythonVersion):
            self.generate_template('app', 'python2.6')

    def test_nonsense_py_version_throws_error(self):
        with pytest.raises(InvalidCodeBuildPythonVersion):
            self.generate_template('app', 'foobar')

    def test_can_provide_codebuild_image(self):
        template = self.generate_template('appname', 'python2.7',
                                          codebuild_image='python:3.6.1')
        default_image = template['Parameters']['CodeBuildImage']['Default']
        assert default_image == 'python:3.6.1'

    def test_no_source_resource_when_using_github(self):
        template = self.generate_template(code_source='github')
        resources = template['Resources']
        assert 'SourceRepository' not in set(resources)

    def test_can_add_github_as_source_stage(self):
        template = self.generate_template(code_source='github')
        resources = template['Resources']
        source_stage = resources['AppPipeline']['Properties']['Stages'][0]
        assert source_stage['Name'] == 'Source'
        actions = source_stage['Actions']
        assert len(actions) == 1
        action = actions[0]
        assert action['ActionTypeId'] == {
            'Category': 'Source',
            'Provider': 'GitHub',
            'Owner': 'ThirdParty',
            'Version': '1',
        }
        assert action['RunOrder'] == 1
        assert action['OutputArtifacts'] == [{'Name': 'SourceRepo'}]
        assert action['Configuration'] == {
            'Owner': {'Ref': 'GithubOwner'},
            'Repo': {'Ref': 'GithubRepoName'},
            'OAuthToken': {'Ref': 'GithubPersonalToken'},
            'Branch': 'master',
            'PollForSourceChanges': True,
        }


class TestPipelineGenV2(object):

    def setup_method(self):
        self.pipeline_gen = pipeline.CreatePipelineTemplateV2()

    def generate_template(self, app_name='appname',
                          lambda_python_version='python3.7',
                          codebuild_image=None, code_source='github',
                          pipeline_version='v2'):
        params = PipelineParameters(
            app_name=app_name,
            lambda_python_version=lambda_python_version,
            codebuild_image=codebuild_image,
            code_source=code_source,
            pipeline_version=pipeline_version,
        )
        template = self.pipeline_gen.create_template(params)
        return template

    def test_new_default_codebuild_image(self):
        template = self.generate_template(app_name='app')
        assert template['Parameters']['CodeBuildImage']['Default'] == (
            "aws/codebuild/amazonlinux2-x86_64-standard:3.0"
        )

    def test_validate_python_versions(self):
        with pytest.raises(InvalidCodeBuildPythonVersion):
            self.generate_template(lambda_python_version='python2.7')

    def test_uses_v2_codebuild_spec(self):
        # The codebuild v2 spec is tested separately, we just need a
        # sanity check to ensure we're using the v0.2 buildspec version.
        template = self.generate_template(app_name='app')
        codebuild_job = template['Resources']['AppPackageBuild']
        assert "version: '0.2'" in codebuild_job[
            'Properties']['Source']['BuildSpec']

    def test_github_source_uses_secretsmanager_in_v2(self):
        template = self.generate_template(code_source='github')
        source_stage = template['Resources'][
            'AppPipeline']['Properties']['Stages'][0]
        assert source_stage['Name'] == 'Source'
        oauth_token = source_stage['Actions'][0]['Configuration']['OAuthToken']
        assert oauth_token == {
            'Fn::Join': [
                '', ['{{resolve:secretsmanager:',
                     {'Ref': 'GithubRepoSecretId'},
                     ':SecretString:',
                     {'Ref': 'GithubRepoSecretJSONKey'},
                     '}}']
            ]
        }
        # We should also add these Refs to our Parameters.
        params = template['Parameters']
        assert 'GithubRepoSecretId' in params
        assert 'GithubRepoSecretJSONKey' in params


def test_source_repo_resource(pipeline_params):
    template = {}
    pipeline.CodeCommitSourceRepository().add_to_template(
        template, pipeline_params)
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


def test_codebuild_resource(pipeline_params):
    template = {}
    pipeline.CodeBuild().add_to_template(template, pipeline_params)
    resources = template['Resources']
    assert 'ApplicationBucket' in resources
    assert 'CodeBuildRole' in resources
    assert 'CodeBuildPolicy' in resources
    assert 'AppPackageBuild' in resources
    assert resources['ApplicationBucket'] == {'Type': 'AWS::S3::Bucket'}
    assert template['Outputs']['CodeBuildRoleArn'] == {
        'Value': {'Fn::GetAtt': 'CodeBuildRole.Arn'}
    }


def test_codepipeline_resource(pipeline_params):
    template = {}
    pipeline.CodePipeline().add_to_template(template, pipeline_params)
    resources = template['Resources']
    assert 'AppPipeline' in resources
    assert 'ArtifactBucketStore' in resources
    assert 'CodePipelineRole' in resources
    assert 'CFNDeployRole' in resources
    # Some basic sanity checks
    assert resources['AppPipeline']['Type'] == 'AWS::CodePipeline::Pipeline'
    assert resources['ArtifactBucketStore']['Type'] == 'AWS::S3::Bucket'
    assert resources['CodePipelineRole']['Type'] == 'AWS::IAM::Role'
    assert resources['CFNDeployRole']['Type'] == 'AWS::IAM::Role'
    properties = resources['AppPipeline']['Properties']
    stages = properties['Stages']
    beta_stage = stages[2]
    beta_config = beta_stage['Actions'][0]['Configuration']
    assert beta_config == {
        'ActionMode': 'CHANGE_SET_REPLACE',
        'Capabilities': 'CAPABILITY_IAM',
        'ChangeSetName': {'Fn::Sub': '${ApplicationName}ChangeSet'},
        'RoleArn': {'Fn::GetAtt': 'CFNDeployRole.Arn'},
        'StackName': {'Fn::Sub': '${ApplicationName}BetaStack'},
        'TemplatePath': 'CompiledCFNTemplate::transformed.yaml'
    }


def test_install_requirements_in_buildspec(pipeline_params):
    template = {}
    pipeline_params.chalice_version_range = '>=1.0.0,<2.0.0'
    pipeline.CodeBuild().add_to_template(template, pipeline_params)
    build = template['Resources']['AppPackageBuild']
    build_spec = build['Properties']['Source']['BuildSpec']
    assert 'pip install -r requirements.txt' in build_spec
    assert "pip install 'chalice>=1.0.0,<2.0.0'" in build_spec


def test_default_version_range_locks_minor_version():
    parts = [int(p) for p in chalice_version.split('.')]
    min_version = '%s.%s.%s' % (parts[0], parts[1], 0)
    max_version = '%s.%s.%s' % (parts[0], parts[1] + 1, 0)
    params = pipeline.PipelineParameters('appname', 'python2.7')
    assert params.chalice_version_range == '>=%s,<%s' % (
        min_version, max_version
    )


def test_can_validate_python_version():
    with pytest.raises(InvalidCodeBuildPythonVersion):
        pipeline.PipelineParameters(
            'myapp', lambda_python_version='bad-python-value'
        )


def test_can_extract_python_version():
    assert pipeline.PipelineParameters('app', 'python3.7').py_major_minor == (
        '3.7')


def test_can_generate_github_source(pipeline_params):
    template = {}
    pipeline_params.code_source = 'github'
    pipeline.GithubSource().add_to_template(template, pipeline_params)
    cfn_params = template['Parameters']
    assert set(cfn_params) == set(['GithubOwner', 'GithubRepoName',
                                   'GithubPersonalToken'])


def test_can_create_buildspec_v2():
    params = pipeline.PipelineParameters('myapp', 'python3.7')
    buildspec = pipeline.create_buildspec_v2(params)
    assert buildspec['phases']['install']['runtime-versions'] == {
        'python': '3.7',
    }


def test_build_extractor():
    template = {
        'Resources': {
            'AppPackageBuild': {
                'Properties': {
                    'Source': {
                        'BuildSpec': 'foobar'
                    }
                }
            }
        }
    }
    extract = pipeline.BuildSpecExtractor()
    extracted = extract.extract_buildspec(template)
    assert extracted == 'foobar'
    assert 'BuildSpec' not in template[
        'Resources']['AppPackageBuild']['Properties']['Source']
