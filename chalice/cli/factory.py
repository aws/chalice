import sys
import os
import json
import importlib
import logging

from botocore import session
from typing import Any, Optional, Dict  # noqa

from chalice import __version__ as chalice_version
from chalice.app import Chalice  # noqa
from chalice.config import Config
from chalice.deploy import deployer
from chalice.package import create_app_packager
from chalice.package import AppPackager  # noqa


def create_botocore_session(profile=None, debug=False):
    # type: (str, bool) -> session.Session
    s = session.Session(profile=profile)
    _add_chalice_user_agent(s)
    if debug:
        s.set_debug_logger('')
        _inject_large_request_body_filter()
    return s


def _add_chalice_user_agent(session):
    # type: (session.Session) -> None
    suffix = '%s/%s' % (session.user_agent_name, session.user_agent_version)
    session.user_agent_name = 'aws-chalice'
    session.user_agent_version = chalice_version
    session.user_agent_extra = suffix


def _inject_large_request_body_filter():
    # type: () -> None
    log = logging.getLogger('botocore.endpoint')
    log.addFilter(LargeRequestBodyFilter())


class LargeRequestBodyFilter(logging.Filter):
    def filter(self, record):
        # type: (Any) -> bool
        # Note: the proper type should be "logging.LogRecord", but
        # the typechecker complains about 'Invalid index type "int" for "dict"'
        # so we're using Any for now.
        if record.msg.startswith('Making request'):
            if record.args[0].name in ['UpdateFunctionCode', 'CreateFunction']:
                # When using the ZipFile argument (which is used in chalice),
                # the entire deployment package zip is sent as a base64 encoded
                # string.  We don't want this to clutter the debug logs
                # so we don't log the request body for lambda operations
                # that have the ZipFile arg.
                record.args = (record.args[:-1] +
                               ('(... omitted from logs due to size ...)',))
        return True


class CLIFactory(object):
    def __init__(self, project_dir, debug=False, profile=None):
        # type: (str, bool, Optional[str]) -> None
        self.project_dir = project_dir
        self.debug = debug
        self.profile = profile

    def create_botocore_session(self):
        # type: () -> session.Session
        return create_botocore_session(profile=self.profile,
                                       debug=self.debug)

    def create_default_deployer(self, session, prompter):
        # type: (session.Session, deployer.NoPrompt) -> deployer.Deployer
        return deployer.create_default_deployer(
            session=session, prompter=prompter)

    def create_config_obj(self, stage_name='dev', autogen_policy=True):
        # type: (str, bool) -> Config
        user_provided_params = {}  # type: Dict[str, Any]
        default_params = {'project_dir': self.project_dir}
        try:
            config_from_disk = self.load_project_config()
        except (OSError, IOError):
            raise RuntimeError("Unable to load the project config file. "
                               "Are you sure this is a chalice project?")
        app_obj = self.load_chalice_app()
        user_provided_params['chalice_app'] = app_obj
        if stage_name is not None:
            user_provided_params['stage'] = stage_name
        if autogen_policy is not None:
            user_provided_params['autogen_policy'] = autogen_policy
        if self.profile is not None:
            user_provided_params['profile'] = self.profile
        config = Config(user_provided_params, config_from_disk, default_params)
        return config

    def create_app_packager(self, config):
        # type: (Config) -> AppPackager
        return create_app_packager(config)

    def load_chalice_app(self):
        # type: () -> Chalice
        if self.project_dir not in sys.path:
            sys.path.append(self.project_dir)
        try:
            app = importlib.import_module('app')
            chalice_app = getattr(app, 'app')
        except Exception as e:
            # TODO: better error.
            exception = Exception(
                "Unable to import your app.py file: %s" % e
            )
            # exception.exit_code = 2
            raise exception
        return chalice_app

    def load_project_config(self):
        # type: () -> Dict[str, Any]
        """Load the chalice config file from the project directory.

        :raise: OSError/IOError if unable to load the config file.

        """
        config_file = os.path.join(self.project_dir, '.chalice', 'config.json')
        with open(config_file) as f:
            return json.loads(f.read())
