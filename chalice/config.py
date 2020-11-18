import os
import sys
import json

from typing import Dict, Any, Optional, List, Union  # noqa
from chalice import __version__ as current_chalice_version
from chalice.app import Chalice  # noqa
from chalice.constants import DEFAULT_STAGE_NAME
from chalice.constants import DEFAULT_HANDLER_NAME


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

    def __init__(self,
                 chalice_stage=DEFAULT_STAGE_NAME,      # type: str
                 function_name=DEFAULT_HANDLER_NAME,    # type: str
                 user_provided_params=None,             # type: StrMap
                 config_from_disk=None,                 # type: StrMap
                 default_params=None,                   # type: StrMap
                 layers=None,                           # type: List[str]
                 ):
        # type: (...) -> None
        #: Params that a user provided explicitly,
        #: typically via the command line.
        self.chalice_stage = chalice_stage
        self.function_name = function_name
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
        self._chalice_app = None
        self._layers = layers

    @classmethod
    def create(cls, chalice_stage=DEFAULT_STAGE_NAME,
               function_name=DEFAULT_HANDLER_NAME,
               **kwargs):
        # type: (str, str, **Any) -> Config
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
        v = self._chain_lookup('chalice_app')
        # There's two value we support.  If the value
        # is a chalice app, we return it as is.
        # Otherwise, we assume it's a callable that creates
        # a chalice app.  This is used to lazy load the chalice
        # app.
        if isinstance(v, Chalice):
            return v
        elif self._chalice_app is not None:
            return self._chalice_app
        elif not callable(v):
            raise TypeError("Unable to load chalice app, lazy loader is "
                            "not callable: %s" % v)
        app = v()
        self._chalice_app = app
        # Keep mypy happy.
        return app

    @property
    def config_from_disk(self):
        # type: () -> StrMap
        return self._config_from_disk

    @property
    def lambda_python_version(self):
        # type: () -> str
        # We may open this up to configuration later, but for now,
        # we attempt to match your python version to the closest version
        # supported by lambda.
        major, minor = sys.version_info[0], sys.version_info[1]
        if major == 2:
            return 'python2.7'
        # Python 3 for backwards compatibility needs to select python3.6
        # for python versions 3.0-3.6. 3.7 and higher will use python3.7.
        elif (major, minor) <= (3, 6):
            return 'python3.6'
        elif (major, minor) <= (3, 7):
            return 'python3.7'
        return 'python3.8'

    @property
    def layers(self):
        # type: () -> List
        return self._chain_lookup('layers',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def api_gateway_custom_domain(self):
        # type: () -> StrMap
        return self._chain_lookup('api_gateway_custom_domain',
                                  varies_per_chalice_stage=True)

    @property
    def websocket_api_custom_domain(self):
        # type: () -> StrMap
        return self._chain_lookup('websocket_api_custom_domain',
                                  varies_per_chalice_stage=True)

    def _chain_lookup(self, name, varies_per_chalice_stage=False,
                      varies_per_function=False):
        # type: (str, bool, bool) -> Any
        search_dicts = [self._user_provided_params]
        if varies_per_chalice_stage:
            search_dicts.append(
                self._config_from_disk.get('stages', {}).get(
                    self.chalice_stage, {}))
        if varies_per_function:
            # search order:
            # config['stages']['lambda_functions']
            # config['stages']
            # config['lambda_functions']
            search_dicts.insert(
                0, self._config_from_disk.get('stages', {}).get(
                    self.chalice_stage, {}).get('lambda_functions', {}).get(
                        self.function_name, {}))
            search_dicts.append(
                self._config_from_disk.get('lambda_functions', {}).get(
                    self.function_name, {}))
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
            self._config_from_disk.get('stages', {}).get(
                self.chalice_stage, {}).get('lambda_functions', {}).get(
                    self.function_name, {}),
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
    def api_gateway_endpoint_type(self):
        # type: () -> str
        return self._chain_lookup('api_gateway_endpoint_type',
                                  varies_per_chalice_stage=True)

    @property
    def api_gateway_endpoint_vpce(self):
        # type: () -> Union[str, List[str]]
        return self._chain_lookup('api_gateway_endpoint_vpce',
                                  varies_per_chalice_stage=True)

    @property
    def api_gateway_policy_file(self):
        # type: () -> str
        return self._chain_lookup('api_gateway_policy_file',
                                  varies_per_chalice_stage=True)

    @property
    def minimum_compression_size(self):
        # type: () -> int
        return self._chain_lookup('minimum_compression_size',
                                  varies_per_chalice_stage=True)

    @property
    def iam_policy_file(self):
        # type: () -> str
        return self._chain_lookup('iam_policy_file',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def lambda_memory_size(self):
        # type: () -> int
        return self._chain_lookup('lambda_memory_size',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def lambda_timeout(self):
        # type: () -> int
        return self._chain_lookup('lambda_timeout',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def automatic_layer(self):
        # type: () -> bool
        v = self._chain_lookup('automatic_layer',
                               varies_per_chalice_stage=True,
                               varies_per_function=False)
        if v is None:
            return False
        return v

    @property
    def iam_role_arn(self):
        # type: () -> str
        return self._chain_lookup('iam_role_arn',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def manage_iam_role(self):
        # type: () -> bool
        result = self._chain_lookup('manage_iam_role',
                                    varies_per_chalice_stage=True,
                                    varies_per_function=True)
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
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def xray_enabled(self):
        # type: () -> bool
        return self._chain_lookup('xray',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def environment_variables(self):
        # type: () -> Dict[str, str]
        return self._chain_merge('environment_variables')

    @property
    def tags(self):
        # type: () -> Dict[str, str]
        tags = self._chain_merge('tags')
        tags['aws-chalice'] = 'version=%s:stage=%s:app=%s' % (
            current_chalice_version, self.chalice_stage, self.app_name)
        return tags

    @property
    def security_group_ids(self):
        # type: () -> List[str]
        return self._chain_lookup('security_group_ids',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def subnet_ids(self):
        # type: () -> List[str]
        return self._chain_lookup('subnet_ids',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    @property
    def reserved_concurrency(self):
        # type: () -> int
        return self._chain_lookup('reserved_concurrency',
                                  varies_per_chalice_stage=True,
                                  varies_per_function=True)

    def scope(self, chalice_stage, function_name):
        # type: (str, str) -> Config
        # Used to create a new config object that's scoped to a different
        # stage and/or function.  This creates a completely separate copy.
        # This is preferred over mutating the existing config obj.
        # We technically don't need to do a copy here, but this avoids
        # any possible issues if we ever mutate the config values.
        clone = self.__class__(
            chalice_stage=chalice_stage,
            function_name=function_name,
            user_provided_params=self._user_provided_params,
            config_from_disk=self._config_from_disk,
            default_params=self._default_params,
        )
        return clone

    def deployed_resources(self, chalice_stage_name):
        # type: (str) -> DeployedResources
        """Return resources associated with a given stage.

        If a deployment to a given stage has never happened,
        this method will return a value of None.

        """
        # This is arguably the wrong level of abstraction.
        # We might be able to move this elsewhere.
        deployed_file = os.path.join(
            self.project_dir, '.chalice', 'deployed',
            '%s.json' % chalice_stage_name)
        data = self._load_json_file(deployed_file)
        if data is not None:
            schema_version = data.get('schema_version', '1.0')
            if schema_version != '2.0':
                raise ValueError("Unsupported schema version (%s) in file: %s"
                                 % (schema_version, deployed_file))
            return DeployedResources(data)
        return self._try_old_deployer_values(chalice_stage_name)

    def _try_old_deployer_values(self, chalice_stage_name):
        # type: (str) -> DeployedResources
        # They are upgrading from v1.0 to v2.0 of the deployed.json
        # schema.  Attempt to auto convert for them.
        old_deployed_file = os.path.join(self.project_dir, '.chalice',
                                         'deployed.json')
        data = self._load_json_file(old_deployed_file)
        if data is None or chalice_stage_name not in data:
            return DeployedResources.empty()
        return self._upgrade_deployed_values(chalice_stage_name, data)

    def _load_json_file(self, deployed_file):
        # type: (str) -> Any
        if not os.path.isfile(deployed_file):
            return None
        with open(deployed_file, 'r') as f:
            return json.load(f)

    def _upgrade_deployed_values(self, chalice_stage_name, data):
        # type: (str, Any) -> DeployedResources
        deployed = data[chalice_stage_name]
        prefix = '%s-%s-' % (self.app_name, chalice_stage_name)
        resources = []  # type: List[Dict[str, Any]]
        self._upgrade_lambda_functions(resources, deployed, prefix)
        self._upgrade_rest_api(resources, deployed)
        return DeployedResources(
            {'resources': resources, 'schema_version': '2.0'})

    def _upgrade_lambda_functions(self, resources, deployed, prefix):
        # type: (List[Dict[str, Any]], Dict[str, Any], str) -> None
        lambda_functions = deployed.get('lambda_functions', {})
        # In chalice 0.10.0, the lambda_functions had the format
        # {"function-name": "lambda_arn"} as opposed to
        # {"function-name": {"arn": "lambda_arn", "type": "...'}} used
        # in later versions of chalice.  We'll check for both cases
        # so people can upgrade from 0.10.0 to the new deployer.
        is_pre_10_format = not all(
            isinstance(v, dict)
            for v in lambda_functions.values()
        )
        if is_pre_10_format:
            lambda_functions = {
                # The only supported lambda functions in 0.10.0
                # was built in authorizers.
                k: {'type': 'authorizer', 'arn': v}
                for k, v in lambda_functions.items()
            }
        for name, values in lambda_functions.items():
            short_name = name[len(prefix):]
            current = {
                'resource_type': 'lambda_function',
                'lambda_arn': values['arn'],
                'name': short_name,
            }
            resources.append(current)

    def _upgrade_rest_api(self, resources, deployed):
        # type: (List[Dict[str, Any]], Dict[str, Any]) -> None
        resources.extend([
            {'name': 'api_handler',
             'resource_type': 'lambda_function',
             'lambda_arn': deployed['api_handler_arn']},
            {'name': 'rest_api',
             'resource_type': 'rest_api',
             'rest_api_id': deployed['rest_api_id']},
        ])


class DeployedResources(object):
    def __init__(self, deployed_values):
        # type: (Dict[str, Any]) -> None
        self._deployed_values = deployed_values['resources']
        self._deployed_values_by_name = {
            resource['name']: resource
            for resource in deployed_values['resources']
        }

    @classmethod
    def empty(cls):
        # type: () -> DeployedResources
        return cls({'resources': [], 'schema_version': '2.0'})

    def resource_values(self, name):
        # type: (str) -> Dict[str, Any]
        if 'api_mapping' in name:
            name = name.split('.')[0]

        try:
            return self._deployed_values_by_name[name]
        except KeyError:
            raise ValueError("Resource does not exist: %s" % name)

    def resource_names(self):
        # type: () -> List[str]
        return [r['name'] for r in self._deployed_values]
