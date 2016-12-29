from typing import Dict, Any  # noqa
from chalice.app import Chalice  # noqa

StrMap = Dict[str, Any]


class Config(object):
    """Configuration information for a chalice app."""
    def __init__(self,
                 user_provided_params=None,
                 config_from_disk=None,
                 default_params=None):
        # type: (StrMap, StrMap, StrMap) -> None
        #: Params that a user provided explicitly,
        #: typically via the command line.
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
    def create(cls, **kwargs):
        # type: (**Any) -> Config
        return cls(user_provided_params=kwargs.copy())

    @property
    def lambda_arn(self):
        # type: () -> str
        return self._chain_lookup('lambda_arn')

    @property
    def profile(self):
        # type: () -> str
        return self._chain_lookup('profile')

    @property
    def app_name(self):
        # type: () -> str
        return self._chain_lookup('app_name')

    @property
    def stage(self):
        # type: () -> str
        return self._chain_lookup('stage')

    @property
    def manage_iam_role(self):
        # type: () -> bool
        result = self._chain_lookup('manage_iam_role')
        if result is None:
            # To simplify downstream code, if manage_iam_role
            # is None (indicating the user hasn't configured/specified this
            # value anywhere), then we'll return a default value of True.
            # Otherwise client code has to do an awkward
            # "if manage_iam_role is None and not manage_iam_role".
            return True
        return result

    @property
    def iam_role_arn(self):
        # type: () -> str
        return self._chain_lookup('iam_role_arn')

    @property
    def project_dir(self):
        # type: () -> str
        return self._chain_lookup('project_dir')

    @property
    def chalice_app(self):
        # type: () -> Chalice
        return self._chain_lookup('chalice_app')

    @property
    def autogen_policy(self):
        # type: () -> bool
        return self._chain_lookup('autogen_policy')

    @property
    def config_from_disk(self):
        # type: () -> StrMap
        return self._config_from_disk

    def _chain_lookup(self, name):
        # type: (str) -> Any
        all_dicts = [
            self._user_provided_params,
            self._config_from_disk,
            self._default_params
        ]
        for cfg_dict in all_dicts:
            if isinstance(cfg_dict, dict) and cfg_dict.get(name) is not None:
                return cfg_dict[name]
