"""Command line interface for chalice.

Contains commands for deploying chalice.

"""
import os
import json

import click
import botocore.exceptions

from chalice import deployer
from chalice.logs import LogRetriever
from chalice import prompts


TEMPLATE_APP = """\
from chalice import Chalice

app = Chalice(app_name='%s')


@app.route('/')
def index():
    return {'hello': 'world'}


# The view function above will return {"hello": "world"}
# whenver you make an HTTP GET request to '/'.
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


def show_lambda_logs(config, max_entries, include_lambda_messages):
    import botocore.session
    lambda_arn = config['config']['lambda_arn']
    client = botocore.session.get_session().create_client('logs')
    retriever = LogRetriever.create_from_arn(client, lambda_arn)
    events = retriever.retrieve_logs(
        include_lambda_messages=include_lambda_messages,
        max_entries=max_entries)
    for event in events:
        print event['timestamp'], event['logShortId'], event['message'].strip()


def load_project_config(project_dir):
    """Load the chalice config file from the project directory.

    :raise: OSError/IOError if unable to load the config file.

    """
    config_file = os.path.join(project_dir, '.chalice', 'config.json')
    with open(config_file) as f:
        return json.loads(f.read())


def load_chalice_app(project_dir):
    app_py = os.path.join(project_dir, 'app.py')
    with open(app_py) as f:
        g = {}
        contents = f.read()
        try:
            exec contents in g
        except Exception as e:
            exception = click.ClickException(
                "Unable to import your app.py file: %s" % e
            )
            exception.exit_code = 2
            raise exception
        return g['app']


@click.group()
@click.pass_context
def cli(ctx):
    pass


@cli.command()
@click.pass_context
def local(ctx):
    click.echo("Local command")


@cli.command()
@click.option('--project-dir',
              help='The project directory.  Defaults to CWD')
@click.option('--autogen-policy/--no-autogen-policy',
              default=True,
              help='Automatically generate IAM policy for app code.')
@click.argument('stage', nargs=1, required=False)
@click.pass_context
def deploy(ctx, project_dir, autogen_policy, stage):
    if project_dir is None:
        project_dir = os.getcwd()
    ctx.obj['project_dir'] = project_dir
    os.chdir(project_dir)
    try:
        config = load_project_config(project_dir)
        ctx.obj['config'] = config
    except (OSError, IOError):
        click.echo("Unable to load the project config file. "
                   "Are you sure this is a chalice project?")
        raise click.Abort()
    if stage is not None:
        config['stage'] = stage
    app_obj = load_chalice_app(project_dir)
    ctx.obj['chalice_app'] = app_obj
    ctx.obj['autogen_policy'] = autogen_policy
    try:
        d = deployer.Deployer(prompter=click, profile=config['profile'])
    except KeyError:
        d = deployer.Deployer(prompter=click)
    try:
        d.deploy(ctx.obj)
    except botocore.exceptions.NoRegionError:
        e = click.ClickException("No region configured. "
                                 "Either export the AWS_DEFAULT_REGION "
                                 "environment variable or set the "
                                 "region value in our ~/.aws/config file.")
        e.exit_code = 2
        raise e
    except Exception as e:
        e = click.ClickException("Error when deploying: %s" % e)
        e.exit_code = 1
        raise e


@cli.command()
@click.option('--project-dir',
              help='The project directory.  Defaults to CWD')
@click.option('--num-entries', default=None, type=int,
              help='Max number of log entries to show.')
@click.option('--include-lambda-messages/--no-include-lambda-messages',
              default=True,
              help='Controls whether or not lambda log messages are included.')
@click.pass_context
def logs(ctx, project_dir, num_entries, include_lambda_messages):
    if project_dir is None:
        project_dir = os.getcwd()
    ctx.obj['project_dir'] = project_dir
    os.chdir(project_dir)
    try:
        config = load_project_config(project_dir)
        ctx.obj['config'] = config
    except (OSError, IOError):
        click.echo("Unable to load the project config file. "
                   "Are you sure this is a chalice project?")
        raise click.Abort()
    app_obj = load_chalice_app(project_dir)
    ctx.obj['chalice_app'] = app_obj
    show_lambda_logs(ctx.obj, num_entries, include_lambda_messages)


@cli.command('gen-policy')
@click.option('--filename',
              help='The filename to analyze.  Otherwise app.py is assumed.')
@click.pass_context
def gen_policy(ctx, filename):
    from chalice import policy
    if filename is None:
        project_dir = os.getcwd()
        filename = os.path.join(project_dir, 'app.py')
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
@click.pass_context
def new_project(ctx, project_name, profile):
    if project_name is None:
        project_name = prompts.getting_started_prompt(click)
    if os.path.isdir(project_name):
        click.echo("Directory already exists: %s" % project_name)
        raise click.Abort()
    chalice_dir = os.path.join(project_name, '.chalice')
    os.makedirs(chalice_dir)
    config = os.path.join(project_name, '.chalice', 'config.json')
    cfg = {
        'app_name': project_name,
        'stage': 'dev'
    }
    if profile:
        cfg['profile'] = profile
    with open(config, 'w') as f:
        f.write(json.dumps(cfg, indent=2))
    with open(os.path.join(project_name, 'requirements.txt'), 'w') as f:
        pass
    with open(os.path.join(project_name, 'app.py'), 'w') as f:
        f.write(TEMPLATE_APP % project_name)


def main():
    # click's dynamic attrs will allow us to pass through
    # 'obj' via the context object, so we're ignoring
    # these error messages from pylint because we know it's ok.
    # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
    return cli(obj={})
