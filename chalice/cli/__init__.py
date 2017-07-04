"""Command line interface for chalice.

Contains commands for deploying chalice.

"""
import json
import logging
import os
import sys
import tempfile
import shutil

import botocore.exceptions
import click
from typing import Dict, Any, Optional  # noqa

from chalice import __version__ as chalice_version
from chalice.app import Chalice  # noqa
from chalice.awsclient import TypedAWSClient
from chalice.cli.factory import CLIFactory
from chalice.config import Config  # noqa
from chalice.logs import display_logs
from chalice.utils import create_zip_file
from chalice.utils import record_deployed_values
from chalice.utils import remove_stage_from_deployed_values
from chalice.deploy.deployer import validate_python_version
from chalice.utils import getting_started_prompt
from chalice.constants import CONFIG_VERSION, TEMPLATE_APP, GITIGNORE
from chalice.constants import DEFAULT_STAGE_NAME


def create_new_project_skeleton(project_name, profile=None):
    # type: (str, Optional[str]) -> None
    chalice_dir = os.path.join(project_name, '.chalice')
    os.makedirs(chalice_dir)
    config = os.path.join(project_name, '.chalice', 'config.json')
    cfg = {
        'version': CONFIG_VERSION,
        'app_name': project_name,
        'stages': {
            DEFAULT_STAGE_NAME: {
                'api_gateway_stage': DEFAULT_STAGE_NAME,
            }
        }
    }
    if profile is not None:
        cfg['profile'] = profile
    with open(config, 'w') as f:
        f.write(json.dumps(cfg, indent=2))
    with open(os.path.join(project_name, 'requirements.txt'), 'w'):
        pass
    with open(os.path.join(project_name, 'app.py'), 'w') as f:
        f.write(TEMPLATE_APP % project_name)
    with open(os.path.join(project_name, '.gitignore'), 'w') as f:
        f.write(GITIGNORE)


@click.group()
@click.version_option(version=chalice_version, message='%(prog)s %(version)s')
@click.option('--project-dir',
              help='The project directory.  Defaults to CWD')
@click.option('--debug/--no-debug',
              default=False,
              help='Print debug logs to stderr.')
@click.pass_context
def cli(ctx, project_dir, debug=False):
    # type: (click.Context, str, bool) -> None
    if project_dir is None:
        project_dir = os.getcwd()
    ctx.obj['project_dir'] = project_dir
    ctx.obj['debug'] = debug
    ctx.obj['factory'] = CLIFactory(project_dir, debug)
    os.chdir(project_dir)


def get_env_variables(config):
    # type: (Dict) -> Dict
    env_vars_key = 'environment_variables'
    env_vars = {}  # type: Dict
    if env_vars_key in config and config[env_vars_key]:
        env_vars = {key: value
                    for key, value in config[env_vars_key].items()}
    return env_vars


@cli.command()
@click.option('--port', default=8000, type=click.INT)
@click.pass_context
def local(ctx, port=8000):
    # type: (click.Context, int) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    app_obj = factory.load_chalice_app()
    config = factory.load_project_config()
    env_variables = get_env_variables(config)
    # When running `chalice local`, a stdout logger is configured
    # so you'll see the same stdout logging as you would when
    # running in lambda.  This is configuring the root logger.
    # The app-specific logger (app.log) will still continue
    # to work.
    logging.basicConfig(stream=sys.stdout)
    run_local_server(app_obj, port, env_variables)


@cli.command()
@click.option('--autogen-policy/--no-autogen-policy',
              default=None,
              help='Automatically generate IAM policy for app code.')
@click.option('--profile', help='Override profile at deploy time.')
@click.option('--api-gateway-stage',
              help='Name of the API gateway stage to deploy to.')
@click.option('--stage', default=DEFAULT_STAGE_NAME,
              help=('Name of the Chalice stage to deploy to. '
                    'Specifying a new chalice stage will create '
                    'an entirely new set of AWS resources.'))
@click.pass_context
def deploy(ctx, autogen_policy, profile, api_gateway_stage, stage):
    # type: (click.Context, Optional[bool], str, str, str) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    factory.profile = profile
    config = factory.create_config_obj(
        chalice_stage_name=stage, autogen_policy=autogen_policy,
        api_gateway_stage=api_gateway_stage,
    )
    session = factory.create_botocore_session()
    d = factory.create_default_deployer(session=session, prompter=click)
    deployed_values = d.deploy(config, chalice_stage_name=stage)
    record_deployed_values(deployed_values, os.path.join(
        config.project_dir, '.chalice', 'deployed.json'))


@cli.command('delete')
@click.option('--profile', help='Override profile at deploy time.')
@click.option('--stage', default=DEFAULT_STAGE_NAME,
              help='Name of the Chalice stage to delete.')
@click.pass_context
def delete(ctx, profile, stage):
    # type: (click.Context, str, str) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    factory.profile = profile
    config = factory.create_config_obj(chalice_stage_name=stage)
    session = factory.create_botocore_session()
    d = factory.create_default_deployer(session=session, prompter=click)
    d.delete(config, chalice_stage_name=stage)
    remove_stage_from_deployed_values(stage, os.path.join(
        config.project_dir, '.chalice', 'deployed.json'))


@cli.command()
@click.option('--num-entries', default=None, type=int,
              help='Max number of log entries to show.')
@click.option('--include-lambda-messages/--no-include-lambda-messages',
              default=False,
              help='Controls whether or not lambda log messages are included.')
@click.option('--stage', default=DEFAULT_STAGE_NAME)
@click.pass_context
def logs(ctx, num_entries, include_lambda_messages, stage):
    # type: (click.Context, int, bool, str) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    config = factory.create_config_obj(stage, False)
    deployed = config.deployed_resources(stage)
    if deployed is not None:
        session = factory.create_botocore_session()
        retriever = factory.create_log_retriever(
            session, deployed.api_handler_arn)
        display_logs(retriever, num_entries, include_lambda_messages,
                     sys.stdout)


@cli.command('gen-policy')
@click.option('--filename',
              help='The filename to analyze.  Otherwise app.py is assumed.')
@click.pass_context
def gen_policy(ctx, filename):
    # type: (click.Context, str) -> None
    from chalice import policy
    if filename is None:
        filename = os.path.join(ctx.obj['project_dir'], 'app.py')
    if not os.path.isfile(filename):
        click.echo("App file does not exist: %s" % filename, err=True)
        raise click.Abort()
    with open(filename) as f:
        contents = f.read()
        generated = policy.policy_from_source_code(contents)
        click.echo(json.dumps(generated, indent=2))


@cli.command('new-project')
@click.argument('project_name', required=False)
@click.option('--profile', required=False)
def new_project(project_name, profile):
    # type: (str, str) -> None
    if project_name is None:
        project_name = getting_started_prompt(click)
    if os.path.isdir(project_name):
        click.echo("Directory already exists: %s" % project_name, err=True)
        raise click.Abort()
    create_new_project_skeleton(project_name, profile)
    validate_python_version(Config.create())


@cli.command('url')
@click.option('--stage', default=DEFAULT_STAGE_NAME)
@click.pass_context
def url(ctx, stage):
    # type: (click.Context, str) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    config = factory.create_config_obj(stage)
    deployed = config.deployed_resources(stage)
    if deployed is not None:
        click.echo(
            "https://{api_id}.execute-api.{region}.amazonaws.com/{stage}/"
            .format(api_id=deployed.rest_api_id,
                    region=deployed.region,
                    stage=deployed.api_gateway_stage)
        )
    else:
        e = click.ClickException(
            "Could not find a record of deployed values to chalice stage: '%s'"
            % stage)
        e.exit_code = 2
        raise e


@cli.command('generate-sdk')
@click.option('--sdk-type', default='javascript',
              type=click.Choice(['javascript']))
@click.option('--stage', default=DEFAULT_STAGE_NAME)
@click.argument('outdir')
@click.pass_context
def generate_sdk(ctx, sdk_type, stage, outdir):
    # type: (click.Context, str, str, str) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    config = factory.create_config_obj(stage)
    session = factory.create_botocore_session()
    client = TypedAWSClient(session)
    deployed = config.deployed_resources(stage)
    if deployed is None:
        click.echo("Could not find API ID, has this application "
                   "been deployed?", err=True)
        raise click.Abort()
    else:
        rest_api_id = deployed.rest_api_id
        api_gateway_stage = deployed.api_gateway_stage
        client.download_sdk(rest_api_id, outdir,
                            api_gateway_stage=api_gateway_stage,
                            sdk_type=sdk_type)


@cli.command('package')
@click.option('--single-file', is_flag=True,
              default=False,
              help=("Create a single packaged file. "
                    "By default, the 'out' argument "
                    "specifies a directory in which the "
                    "package assets will be placed.  If "
                    "this argument is specified, a single "
                    "zip file will be created instead."))
@click.option('--stage', default=DEFAULT_STAGE_NAME)
@click.argument('out')
@click.pass_context
def package(ctx, single_file, stage, out):
    # type: (click.Context, bool, str, str) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    config = factory.create_config_obj(stage)
    packager = factory.create_app_packager(config)
    if single_file:
        dirname = tempfile.mkdtemp()
        try:
            packager.package_app(config, dirname)
            create_zip_file(source_dir=dirname, outfile=out)
        finally:
            shutil.rmtree(dirname)
    else:
        packager.package_app(config, out)


@cli.command('generate-pipeline')
@click.argument('filename')
@click.pass_context
def generate_pipeline(ctx, filename):
    # type: (click.Context, str) -> None
    """Generate a cloudformation template for a starter CD pipeline.

    This command will write a starter cloudformation template to
    the filename you provide.  It contains a CodeCommit repo,
    a CodeBuild stage for packaging your chalice app, and a
    CodePipeline stage to deploy your application using cloudformation.

    You can use any AWS SDK or the AWS CLI to deploy this stack.
    Here's an example using the AWS CLI:

        \b
        $ chalice generate-pipeline pipeline.json
        $ aws cloudformation deploy --stack-name mystack \b
            --template-file pipeline.json --capabilities CAPABILITY_IAM
    """
    from chalice.pipeline import create_pipeline_template
    factory = ctx.obj['factory']  # type: CLIFactory
    config = factory.create_config_obj()
    output = create_pipeline_template(config)
    with open(filename, 'w') as f:
        f.write(json.dumps(output, indent=2, separators=(',', ': ')))


def run_local_server(app_obj, port, env_variables):
    # type: (Chalice, int, Dict) -> None
    from chalice.local import create_local_server
    server = create_local_server(app_obj, port, env_variables=env_variables)
    server.serve_forever()


def main():
    # type: () -> int
    # click's dynamic attrs will allow us to pass through
    # 'obj' via the context object, so we're ignoring
    # these error messages from pylint because we know it's ok.
    # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
    try:
        return cli(obj={})
    except botocore.exceptions.NoRegionError:
        click.echo("No region configured. "
                   "Either export the AWS_DEFAULT_REGION "
                   "environment variable or set the "
                   "region value in our ~/.aws/config file.", err=True)
        return 2
    except Exception as e:
        click.echo(str(e), err=True)
        return 2
