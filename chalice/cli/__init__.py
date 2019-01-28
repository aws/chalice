"""Command line interface for chalice.

Contains commands for deploying chalice.

"""
import logging
import os
import platform
import sys
import tempfile
import shutil
import traceback
import functools

import botocore.exceptions
import click
from typing import Dict, Any, Optional  # noqa

from chalice import __version__ as chalice_version
from chalice.app import Chalice  # noqa
from chalice.awsclient import TypedAWSClient
from chalice.awsclient import ReadTimeout
from chalice.cli.factory import CLIFactory
from chalice.cli.factory import NoSuchFunctionError
from chalice.config import Config  # noqa
from chalice.logs import display_logs
from chalice.utils import create_zip_file
from chalice.deploy.validate import validate_routes, validate_python_version
from chalice.deploy.validate import ExperimentalFeatureError
from chalice.utils import getting_started_prompt, UI, serialize_to_json
from chalice.constants import CONFIG_VERSION, TEMPLATE_APP, GITIGNORE
from chalice.constants import DEFAULT_STAGE_NAME
from chalice.constants import DEFAULT_APIGATEWAY_STAGE_NAME
from chalice.local import LocalDevServer  # noqa
from chalice.constants import DEFAULT_HANDLER_NAME
from chalice.invoke import UnhandledLambdaError


def _configure_logging(level, format_string=None):
    # type: (int, Optional[str]) -> None
    if format_string is None:
        format_string = "%(asctime)s %(name)s [%(levelname)s] %(message)s"
    logger = logging.getLogger('')
    logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setLevel(level)
    formatter = logging.Formatter(format_string)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


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
                'api_gateway_stage': DEFAULT_APIGATEWAY_STAGE_NAME,
            }
        }
    }
    if profile is not None:
        cfg['profile'] = profile
    with open(config, 'w') as f:
        f.write(serialize_to_json(cfg))
    with open(os.path.join(project_name, 'requirements.txt'), 'w'):
        pass
    with open(os.path.join(project_name, 'app.py'), 'w') as f:
        f.write(TEMPLATE_APP % project_name)
    with open(os.path.join(project_name, '.gitignore'), 'w') as f:
        f.write(GITIGNORE)


def get_system_info():
    # type: () -> str
    python_info = "python {}.{}.{}".format(sys.version_info[0],
                                           sys.version_info[1],
                                           sys.version_info[2])
    platform_system = platform.system().lower()
    platform_release = platform.release()
    platform_info = "{} {}".format(platform_system, platform_release)
    return "{}, {}".format(python_info, platform_info)


@click.group()
@click.version_option(version=chalice_version,
                      message='%(prog)s %(version)s, {}'
                      .format(get_system_info()))
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
    if debug is True:
        _configure_logging(logging.DEBUG)
    ctx.obj['project_dir'] = project_dir
    ctx.obj['debug'] = debug
    ctx.obj['factory'] = CLIFactory(project_dir, debug, environ=os.environ)
    os.chdir(project_dir)


@cli.command()
@click.option('--host', default='127.0.0.1')
@click.option('--port', default=8000, type=click.INT)
@click.option('--stage', default=DEFAULT_STAGE_NAME,
              help='Name of the Chalice stage for the local server to use.')
@click.option('--autoreload/--no-autoreload',
              default=True,
              help='Automatically restart server when code changes.')
@click.pass_context
def local(ctx, host='127.0.0.1', port=8000, stage=DEFAULT_STAGE_NAME,
          autoreload=True):
    # type: (click.Context, str, int, str, bool) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    from chalice.cli import reloader
    # We don't create the server here because that will bind the
    # socket and we only want to do this in the worker process.
    server_factory = functools.partial(
        create_local_server, factory, host, port, stage)
    # When running `chalice local`, a stdout logger is configured
    # so you'll see the same stdout logging as you would when
    # running in lambda.  This is configuring the root logger.
    # The app-specific logger (app.log) will still continue
    # to work.
    logging.basicConfig(
        stream=sys.stdout, level=logging.INFO, format='%(message)s')
    if autoreload:
        project_dir = factory.create_config_obj(
            chalice_stage_name=stage).project_dir
        rc = reloader.run_with_reloader(
            server_factory, os.environ, project_dir)
        # Click doesn't sys.exit() with the RC this function.  The
        # recommended way to do this is to use sys.exit() directly,
        # see: https://github.com/pallets/click/issues/747
        sys.exit(rc)
    run_local_server(factory, host, port, stage)


def create_local_server(factory, host, port, stage):
    # type: (CLIFactory, str, int, str) -> LocalDevServer
    config = factory.create_config_obj(
        chalice_stage_name=stage
    )
    app_obj = config.chalice_app
    # Check that `chalice deploy` would let us deploy these routes, otherwise
    # there is no point in testing locally.
    routes = config.chalice_app.routes
    validate_routes(routes)
    server = factory.create_local_server(app_obj, config, host, port)
    return server


def run_local_server(factory, host, port, stage):
    # type: (CLIFactory, str, int, str) -> None
    server = create_local_server(factory, host, port, stage)
    server.serve_forever()


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
@click.option('--connection-timeout',
              type=int,
              help=('Overrides the default botocore connection '
                    'timeout.'))
@click.pass_context
def deploy(ctx, autogen_policy, profile, api_gateway_stage, stage,
           connection_timeout):
    # type: (click.Context, Optional[bool], str, str, str, int) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    factory.profile = profile
    config = factory.create_config_obj(
        chalice_stage_name=stage, autogen_policy=autogen_policy,
        api_gateway_stage=api_gateway_stage,
    )
    session = factory.create_botocore_session(
        connection_timeout=connection_timeout)
    ui = UI()
    d = factory.create_default_deployer(session=session,
                                        config=config,
                                        ui=ui)
    deployed_values = d.deploy(config, chalice_stage_name=stage)
    reporter = factory.create_deployment_reporter(ui=ui)
    reporter.display_report(deployed_values)


@cli.command('invoke')
@click.option('-n', '--name', metavar='NAME', required=True,
              help=('The name of the function to invoke. '
                    'This is the logical name of the function. If the '
                    'function is decorated by app.route use the name '
                    'api_handler instead.'))
@click.option('--profile', metavar='PROFILE',
              help='Override profile at deploy time.')
@click.option('--stage', metavar='STAGE', default=DEFAULT_STAGE_NAME,
              help=('Name of the Chalice stage to deploy to. '
                    'Specifying a new chalice stage will create '
                    'an entirely new set of AWS resources.'))
@click.pass_context
def invoke(ctx, name, profile, stage):
    # type: (click.Context, str, str, str) -> None
    """Invoke the deployed lambda function NAME."""
    factory = ctx.obj['factory']  # type: CLIFactory
    factory.profile = profile

    try:
        invoke_handler = factory.create_lambda_invoke_handler(name, stage)
        payload = factory.create_stdin_reader().read()
        invoke_handler.invoke(payload)
    except NoSuchFunctionError as e:
        err = click.ClickException(
            "could not find a lambda function named %s." % e.name)
        err.exit_code = 2
        raise err
    except botocore.exceptions.ClientError as e:
        error = e.response['Error']
        err = click.ClickException(
            "got '%s' exception back from Lambda\n%s"
            % (error['Code'], error['Message']))
        err.exit_code = 1
        raise err
    except UnhandledLambdaError:
        err = click.ClickException(
            "Unhandled exception in Lambda function, details above.")
        err.exit_code = 1
        raise err
    except ReadTimeout as e:
        err = click.ClickException(e.message)
        err.exit_code = 1
        raise err


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
    d = factory.create_deletion_deployer(session=session, ui=UI())
    d.deploy(config, chalice_stage_name=stage)


@cli.command()
@click.option('--num-entries', default=None, type=int,
              help='Max number of log entries to show.')
@click.option('--include-lambda-messages/--no-include-lambda-messages',
              default=False,
              help='Controls whether or not lambda log messages are included.')
@click.option('--stage', default=DEFAULT_STAGE_NAME)
@click.option('-n', '--name',
              help='The name of the lambda function to retrieve logs from.',
              default=DEFAULT_HANDLER_NAME)
@click.option('--profile', help='The profile to use for fetching logs.')
@click.pass_context
def logs(ctx, num_entries, include_lambda_messages, stage, name, profile):
    # type: (click.Context, int, bool, str, str, str) -> None
    factory = ctx.obj['factory']  # type: CLIFactory
    factory.profile = profile
    config = factory.create_config_obj(stage, False)
    deployed = config.deployed_resources(stage)
    if name in deployed.resource_names():
        lambda_arn = deployed.resource_values(name)['lambda_arn']
        session = factory.create_botocore_session()
        retriever = factory.create_log_retriever(
            session, lambda_arn)
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
        click.echo(serialize_to_json(generated))


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
    if deployed is not None and 'rest_api' in deployed.resource_names():
        click.echo(deployed.resource_values('rest_api')['rest_api_url'])
    else:
        e = click.ClickException(
            "Could not find a record of a Rest API in chalice stage: '%s'"
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
    if deployed is not None and 'rest_api' in deployed.resource_names():
        rest_api_id = deployed.resource_values('rest_api')['rest_api_id']
        api_gateway_stage = config.api_gateway_stage
        client.download_sdk(rest_api_id, outdir,
                            api_gateway_stage=api_gateway_stage,
                            sdk_type=sdk_type)
    else:
        click.echo("Could not find API ID, has this application "
                   "been deployed?", err=True)
        raise click.Abort()


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
            packager.package_app(config, dirname, stage)
            create_zip_file(source_dir=dirname, outfile=out)
        finally:
            shutil.rmtree(dirname)
    else:
        packager.package_app(config, out, stage)


@cli.command('generate-pipeline')
@click.option('-i', '--codebuild-image',
              help=("Specify default codebuild image to use.  "
                    "This option must be provided when using a python "
                    "version besides 2.7."))
@click.option('-s', '--source', default='codecommit',
              type=click.Choice(['codecommit', 'github']),
              help=("Specify the input source.  The default value of "
                    "'codecommit' will create a CodeCommit repository "
                    "for you.  The 'github' value allows you to "
                    "reference an existing GitHub repository."))
@click.option('-b', '--buildspec-file',
              help=("Specify path for buildspec.yml file. "
                    "By default, the build steps are included in the "
                    "generated cloudformation template.  If this option "
                    "is provided, a buildspec.yml will be generated "
                    "as a separate file and not included in the cfn "
                    "template.  This allows you to make changes to how "
                    "the project is built without having to redeploy "
                    "a CloudFormation template. This file should be "
                    "named 'buildspec.yml' and placed in the root "
                    "directory of your app."))
@click.argument('filename')
@click.pass_context
def generate_pipeline(ctx, codebuild_image, source, buildspec_file, filename):
    # type: (click.Context, str, str, str, str) -> None
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
    from chalice import pipeline
    factory = ctx.obj['factory']  # type: CLIFactory
    config = factory.create_config_obj()
    p = pipeline.CreatePipelineTemplate()
    params = pipeline.PipelineParameters(
        app_name=config.app_name,
        lambda_python_version=config.lambda_python_version,
        codebuild_image=codebuild_image,
        code_source=source,
    )
    output = p.create_template(params)
    if buildspec_file:
        extractor = pipeline.BuildSpecExtractor()
        buildspec_contents = extractor.extract_buildspec(output)
        with open(buildspec_file, 'w') as f:
            f.write(buildspec_contents)
    with open(filename, 'w') as f:
        f.write(serialize_to_json(output))


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
    except ExperimentalFeatureError as e:
        click.echo(str(e))
        return 2
    except Exception:
        click.echo(traceback.format_exc(), err=True)
        return 2
