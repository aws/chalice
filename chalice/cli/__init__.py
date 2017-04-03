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
from botocore.session import Session  # noqa
from typing import Dict, Any, Optional  # noqa

from chalice import __version__ as chalice_version
from chalice import prompts
from chalice.app import Chalice  # noqa
from chalice.awsclient import TypedAWSClient
from chalice.cli.factory import CLIFactory
from chalice.config import Config  # noqa
from chalice.logs import LogRetriever
from chalice.utils import create_zip_file, record_deployed_values
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


def show_lambda_logs(session, lambda_arn, max_entries,
                     include_lambda_messages):
    # type: (Session, str, int, bool) -> None
    client = session.create_client('logs')
    retriever = LogRetriever.create_from_arn(client, lambda_arn)
    events = retriever.retrieve_logs(
        include_lambda_messages=include_lambda_messages,
        max_entries=max_entries)
    for event in events:
        print event['timestamp'], event['logShortId'], event['message'].strip()


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


@cli.command()
@click.option('--port', default=8000, type=click.INT)
@click.pass_context
def local(ctx, port=8000):
    # type: (click.Context, int) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    app_obj = factory.load_chalice_app()
    # When running `chalice local`, a stdout logger is configured
    # so you'll see the same stdout logging as you would when
    # running in lambda.  This is configuring the root logger.
    # The app-specific logger (app.log) will still continue
    # to work.
    logging.basicConfig(stream=sys.stdout)
    run_local_server(app_obj, port)


@cli.command()
@click.option('--autogen-policy/--no-autogen-policy',
              default=True,
              help='Automatically generate IAM policy for app code.')
@click.option('--profile', help='Override profile at deploy time.')
@click.option('--api-gateway-stage',
              help='Name of the API gateway stage to deploy to.')
@click.option('--stage', default=DEFAULT_STAGE_NAME,
              help=('Name of the Chalice stage to deploy to. '
                    'Specifying a new chalice stage will create '
                    'an entirely new set of AWS resources.'))
@click.argument('deprecated-api-gateway-stage', nargs=1, required=False)
@click.pass_context
def deploy(ctx, autogen_policy, profile, api_gateway_stage, stage,
           deprecated_api_gateway_stage):
    # type: (click.Context, bool, str, str, str, str) -> None
    if api_gateway_stage is not None and \
            deprecated_api_gateway_stage is not None:
        raise _create_deprecated_stage_error(api_gateway_stage,
                                             deprecated_api_gateway_stage)
    if deprecated_api_gateway_stage is not None:
        # The "chalice deploy <stage>" is deprecated and will be removed
        # in future versions.  We'll support it for now, but let the
        # user know to stop using this.
        _warn_pending_removal(deprecated_api_gateway_stage)
        api_gateway_stage = deprecated_api_gateway_stage
    factory = ctx.obj['factory']  # type: CLIFactory
    factory.profile = profile
    config = factory.create_config_obj(
        chalice_stage_name=stage, autogen_policy=autogen_policy)
    session = factory.create_botocore_session()
    d = factory.create_default_deployer(session=session, prompter=click)
    deployed_values = d.deploy(config, chalice_stage_name=stage)
    record_deployed_values(deployed_values, os.path.join(
        config.project_dir, '.chalice', 'deployed.json'))


def _create_deprecated_stage_error(option, positional_arg):
    # type: (str, str) -> click.ClickException
    message = (
        "You've specified both an '--api-gateway-stage' value of "
        "'%s' as well as the positional API Gateway stage argument "
        "'chalice deploy \"%s\"'.\n\n"
        "The positional argument for API gateway stage ('chalice deploy "
        "<api-gateway-stage>') is deprecated and support will be "
        "removed in a future version of chalice.\nIf you want to "
        "specify an API Gateway stage, just specify the "
        "--api-gateway-stage option and remove the positional "
        "stage argument.\n"
        "If you want a completely separate set of AWS resources, "
        "consider using the '--stage' argument."
    ) % (option, positional_arg)
    exception = click.ClickException(message)
    exception.exit_code = 2
    return exception


def _warn_pending_removal(deprecated_stage):
    # type: (str) -> None
    click.echo("You've specified a deploy command of the form "
               "'chalice deploy <stage>'\n"
               "This form is deprecated and will be removed in a "
               "future version of chalice.\n"
               "You can use the --api-gateway-stage to achieve the "
               "same functionality, or the newer '--stage' argument "
               "if you want an entirely set of separate resources.",
               err=True)


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
        show_lambda_logs(session, deployed.api_handler_arn, num_entries,
                         include_lambda_messages)


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
        project_name = prompts.getting_started_prompt(click)
    if os.path.isdir(project_name):
        click.echo("Directory already exists: %s" % project_name, err=True)
        raise click.Abort()
    create_new_project_skeleton(project_name, profile)


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


def run_local_server(app_obj, port):
    # type: (Chalice, int) -> None
    from chalice.local import create_local_server
    server = create_local_server(app_obj, port)
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
