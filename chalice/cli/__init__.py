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
from typing import Dict, Any  # noqa

from chalice import __version__ as chalice_version
from chalice import prompts
from chalice.app import Chalice  # noqa
from chalice.awsclient import TypedAWSClient
from chalice.cli.factory import CLIFactory
from chalice.config import Config  # noqa
from chalice.logs import LogRetriever
from chalice.utils import create_zip_file, record_deployed_values


# This is the version that's written to the config file
# on a `chalice new-project`.  It's also how chalice is able
# to know when to warn you when changing behavior is introduced.
CONFIG_VERSION = '2.0'


TEMPLATE_APP = """\
from chalice import Chalice

app = Chalice(app_name='%s')


@app.route('/')
def index():
    return {'hello': 'world'}


# The view function above will return {"hello": "world"}
# whenever you make an HTTP GET request to '/'.
#
# Here are a few more examples:
#
# @app.route('/hello/{name}')
# def hello_name(name):
#    # '/hello/james' -> {"hello": "james"}
#    return {'hello': name}
#
# @app.route('/users', methods=['POST'])
# def create_user():
#     # This is the JSON body the user sent in their POST request.
#     user_as_json = app.json_body
#     # Suppose we had some 'db' object that we used to
#     # read/write from our database.
#     # user_id = db.create_user(user_as_json)
#     return {'user_id': user_id}
#
# See the README documentation for more examples.
#
"""


GITIGNORE = """\
.chalice/deployments/
.chalice/venv/
"""


def show_lambda_logs(session, config, max_entries, include_lambda_messages):
    # type: (Session, Config, int, bool) -> None
    lambda_arn = config.lambda_arn
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
    factory = ctx.obj['factory']
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
@click.argument('stage', nargs=1, required=False)
@click.pass_context
def deploy(ctx, autogen_policy, profile, stage):
    # type: (click.Context, bool, str, str) -> None
    factory = ctx.obj['factory']
    factory.profile = profile
    config = factory.create_config_obj(
        # Note: stage_name is not the same thing as the chalice stage.
        # This is a legacy artifact that just means "API gateway stage",
        # or for our purposes, the URL prefix.
        stage_name='dev', autogen_policy=autogen_policy)
    if stage is None:
        stage = 'dev'
    session = factory.create_botocore_session()
    d = factory.create_default_deployer(session=session, prompter=click)
    try:
        deployed_values = d.deploy(config, stage_name=stage)
        record_deployed_values(deployed_values, os.path.join(
            config.project_dir, '.chalice', 'deployed.json'))
    except botocore.exceptions.NoRegionError:
        e = click.ClickException("No region configured. "
                                 "Either export the AWS_DEFAULT_REGION "
                                 "environment variable or set the "
                                 "region value in our ~/.aws/config file.")
        e.exit_code = 2
        raise e


@cli.command()
@click.option('--num-entries', default=None, type=int,
              help='Max number of log entries to show.')
@click.option('--include-lambda-messages/--no-include-lambda-messages',
              default=False,
              help='Controls whether or not lambda log messages are included.')
@click.pass_context
def logs(ctx, num_entries, include_lambda_messages):
    # type: (click.Context, int, bool) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    config = factory.create_config_obj('dev', False)
    factory = ctx.obj['factory']
    session = factory.create_botocore_session()
    show_lambda_logs(session, config, num_entries, include_lambda_messages)


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
        click.echo("App file does not exist: %s" % filename)
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
        click.echo("Directory already exists: %s" % project_name)
        raise click.Abort()
    chalice_dir = os.path.join(project_name, '.chalice')
    os.makedirs(chalice_dir)
    config = os.path.join(project_name, '.chalice', 'config.json')
    cfg = {
        'version': CONFIG_VERSION,
        'app_name': project_name,
        'stage': 'dev'
    }
    if profile:
        cfg['profile'] = profile
    with open(config, 'w') as f:
        f.write(json.dumps(cfg, indent=2))
    with open(os.path.join(project_name, 'requirements.txt'), 'w'):
        pass
    with open(os.path.join(project_name, 'app.py'), 'w') as f:
        f.write(TEMPLATE_APP % project_name)
    with open(os.path.join(project_name, '.gitignore'), 'w') as f:
        f.write(GITIGNORE)


@cli.command('url')
@click.pass_context
def url(ctx):
    # type: (click.Context) -> None
    factory = ctx.obj['factory']
    # TODO: Command should be stage aware!
    config = factory.create_config_obj()
    session = factory.create_botocore_session(
        profile=config.profile, debug=ctx.obj['debug'])
    c = TypedAWSClient(session)
    rest_api_id = c.get_rest_api_id(config.app_name)
    stage_name = config.stage
    region_name = c.region_name
    click.echo(
        "https://{api_id}.execute-api.{region}.amazonaws.com/{stage}/"
        .format(api_id=rest_api_id, region=region_name, stage=stage_name)
    )


@cli.command('generate-sdk')
@click.option('--sdk-type', default='javascript',
              type=click.Choice(['javascript']))
@click.argument('outdir')
@click.pass_context
def generate_sdk(ctx, sdk_type, outdir):
    # type: (click.Context, str, str) -> None
    factory = ctx.obj['factory']
    config = factory.create_config_obj()
    factory = ctx.obj['factory']
    session = factory.create_botocore_session(
        profile=config.profile, debug=ctx.obj['debug'])
    client = TypedAWSClient(session)
    rest_api_id = client.get_rest_api_id(config.app_name)
    stage_name = config.stage
    if rest_api_id is None:
        click.echo("Could not find API ID, has this application "
                   "been deployed?")
        raise click.Abort()
    client.download_sdk(rest_api_id, outdir, stage=stage_name,
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
@click.argument('out')
@click.pass_context
def package(ctx, single_file, out):
    # type: (click.Context, bool, str) -> None
    factory = ctx.obj['factory']
    config = factory.create_config_obj()
    packager = factory.create_app_packager(config)
    if single_file:
        dirname = tempfile.mkdtemp()
        try:
            packager.package_app(dirname)
            create_zip_file(source_dir=dirname, outfile=out)
        finally:
            shutil.rmtree(dirname)
    else:
        packager.package_app(out)


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
    except Exception as e:
        click.echo(str(e))
        return 2
