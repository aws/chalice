import os
import sys
import json

from typing import Dict, Any, Optional  # noqa
from chalice.app import Chalice  # noqa
from chalice.constants import DEFAULT_STAGE_NAME


StrMap = Dict[str, Any]


class Config(object):
    """Configuration information for a chalice app.

    Configuration values for a chalice app can come from
    a number of locations, files on disk, CLI params, default
    values, etc.  This object is an abstraction that normalizes
    these values.

    In general, there's a precedence for looking up
    config values:

        * User specified params
        * Config file values
        * Default values

    A user specified parameter would mean values explicitly
    specified by a user.  Generally these come from command
    line parameters (e.g ``--profile prod``), but for the purposes
    of this object would also mean values passed explicitly to
    this config object when instantiated.

    Additionally, there are some configurations that can vary
    per chalice stage (note that a chalice stage is different
    from an api gateway stage).  For config values loaded from
    disk, we allow values to be specified for all stages or
    for a specific stage.  For example, take ``environment_variables``.
    You can set this as a top level key to specify env vars
    to set for all stages, or you can set this value per chalice
    stage to set stage-specific environment variables.  Consider
    this config file::

        {
          "environment_variables": {
            "TABLE": "foo"
          },
          "stages": {
            "dev": {
              "environment_variables": {
                "S3BUCKET": "devbucket"
              }
            },
            "prod": {
              "environment_variables": {
                "S3BUCKET": "prodbucket",
                "TABLE": "prodtable"
              }
            }
          }
        }

    If the currently configured chalice stage is "dev", then
    the config.environment_variables would be::

        {"TABLE": "foo", "S3BUCKET": "devbucket"}

    The "prod" stage would be::

        {"TABLE": "prodtable", "S3BUCKET": "prodbucket"}

    """

    _PYTHON_VERSIONS = {
        2: 'python2.7',
        3: 'python3.6',
    }

    def __init__(self,
                 chalice_stage=DEFAULT_STAGE_NAME,
                 user_provided_params=None,
                 config_from_disk=None,
                 default_params=None):
        # type: (str, StrMap, StrMap, StrMap) -> None
        #: Params that a user provided explicitly,
        #: typically via the command line.
        self.chalice_stage = chalice_stage
        if user_provided_params is None:
            user_provided_params = {}
        self._user_provided_params = user_provided_params
        #: The json.loads() from .chalice/config.json
        if config_from_disk is None:
            config_from_disk = {}
        self._config_from_disk = config_from_disk
        if default_params is None:
            default_params = {}
        self._default_params = default_params

    @classmethod
    def create(cls, chalice_stage=DEFAULT_STAGE_NAME, **kwargs):
        # type: (str, **Any) -> Config
        return cls(chalice_stage=chalice_stage,
                   user_provided_params=kwargs.copy())

    @property
    def profile(self):
        # type: () -> str
        return self._chain_lookup('profile')

    @property
    def app_name(self):
        # type: () -> str
        return self._chain_lookup('app_name')

    @property
    def project_dir(self):
        # type: () -> str
        return self._chain_lookup('project_dir')

    @property
    def chalice_app(self):
        # type: () -> Chalice
        return self._chain_lookup('chalice_app')

    @property
    def config_from_disk(self):
        # type: () -> StrMap
        return self._config_from_disk

    @property
    def iam_policy_file(self):
        # type: () -> str
        return self._chain_lookup('iam_policy_file',
                                  varies_per_chalice_stage=True)

    @property
    def lambda_python_version(self):
        # type: () -> str
        # We may open this up to configuration later, but for now,
        # we attempt to match your python version to the closest version
        # supported by lambda.
        return self._PYTHON_VERSIONS[sys.version_info[0]]

    @property
    def lambda_memory_size(self):
        # type: () -> int
        return self._chain_lookup(
            'lambda_memory_size', varies_per_chalice_stage=True)

    @property
    def lambda_timeout(self):
        # type: () -> int
        return self._chain_lookup(
            'lambda_timeout', varies_per_chalice_stage=True)

    @property
    def tags(self):
        # type: () -> Dict[str, str]
        return self._chain_merge('tags')

    def _chain_lookup(self, name, varies_per_chalice_stage=False):
        # type: (str, bool) -> Any
        search_dicts = [self._user_provided_params]
        if varies_per_chalice_stage:
            search_dicts.append(
                self._config_from_disk.get('stages', {}).get(
                    self.chalice_stage, {}))
        search_dicts.extend([self._config_from_disk, self._default_params])
        for cfg_dict in search_dicts:
            if isinstance(cfg_dict, dict) and cfg_dict.get(name) is not None:
                return cfg_dict[name]

    def _chain_merge(self, name):
        # type: (str) -> Dict[str, Any]
        # Merge values for all search dicts instead of returning on first
        # found.
        search_dicts = [
            # This is reverse order to _chain_lookup().
            self._default_params,
            self._config_from_disk,
            self._config_from_disk.get('stages', {}).get(
                self.chalice_stage, {}),
            self._user_provided_params,
        ]
        final = {}
        for cfg_dict in search_dicts:
            value = cfg_dict.get(name, {})
            if isinstance(value, dict):
                final.update(value)
        return final

    @property
    def config_file_version(self):
        # type: () -> str
        return self._config_from_disk.get('version', '1.0')

    # These are all config values that can vary per
    # chalice stage.

    @property
    def api_gateway_stage(self):
        # type: () -> str
        return self._chain_lookup('api_gateway_stage',
                                  varies_per_chalice_stage=True)

    @property
    def iam_role_arn(self):
        # type: () -> str
        return self._chain_lookup('iam_role_arn',
                                  varies_per_chalice_stage=True)

    @property
    def manage_iam_role(self):
        # type: () -> bool
        result = self._chain_lookup('manage_iam_role',
                                    varies_per_chalice_stage=True)
        if result is None:
            # To simplify downstream code, if manage_iam_role
            # is None (indicating the user hasn't configured/specified this
            # value anywhere), then we'll return a default value of True.
            # Otherwise client code has to do an awkward
            # "if manage_iam_role is None and not manage_iam_role".
            return True
        return result

    @property
    def autogen_policy(self):
        # type: () -> bool
        return self._chain_lookup('autogen_policy',
                                  varies_per_chalice_stage=True)

    @property
    def environment_variables(self):
        # type: () -> Dict[str, str]
        return self._chain_merge('environment_variables')

    def deployed_resources(self, chalice_stage_name):
        # type: (str) -> Optional[DeployedResources]
        """Return resources associated with a given stage.

        If a deployment to a given stage has never happened,
        this method will return a value of None.

        """
        # This is arguably the wrong level of abstraction.
        # We might be able to move this elsewhere.
        deployed_file = os.path.join(self.project_dir, '.chalice',
                                     'deployed.json')
        if not os.path.isfile(deployed_file):
            return None
        with open(deployed_file, 'r') as f:
            data = json.load(f)
        if chalice_stage_name not in data:
            return None
        return DeployedResources.from_dict(data[chalice_stage_name])


class DeployedResources(object):
    def __init__(self, backend, api_handler_arn,
                 api_handler_name, rest_api_id, api_gateway_stage,
                 region, chalice_version):
        # type: (str, str, str, str, str, str, str) -> None
        self.backend = backend
        self.api_handler_arn = api_handler_arn
        self.api_handler_name = api_handler_name
        self.rest_api_id = rest_api_id
        self.api_gateway_stage = api_gateway_stage
        self.region = region
        self.chalice_version = chalice_version

    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, str]) -> DeployedResources
        return cls(
            data['backend'],
            data['api_handler_arn'],
            data['api_handler_name'],
            data['rest_api_id'],
            data['api_gateway_stage'],
            data['region'],
            data['chalice_version'],
        )
