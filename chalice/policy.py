"""Policy generator based on allowed API calls.

This module will take a set of API calls for services
and make a best effort attempt to generate an IAM policy
for you.

"""
from __future__ import print_function
import os
import json
import uuid

from typing import Any, List, Dict, Set  # noqa
import botocore.session

from chalice.constants import CLOUDWATCH_LOGS, VPC_ATTACH_POLICY
from chalice.utils import OSUtils  # noqa
from chalice.config import Config  # noqa


def policy_from_source_code(source_code):
    # type: (str) -> Dict[str, Any]
    from chalice.analyzer import get_client_calls_for_app
    client_calls = get_client_calls_for_app(source_code)
    builder = PolicyBuilder()
    policy = builder.build_policy_from_api_calls(client_calls)
    return policy


def load_policy_actions():
    # type: () -> Dict[str, str]
    policy_json = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'policies.json')
    assert os.path.isfile(policy_json), policy_json
    with open(policy_json) as f:
        return json.loads(f.read())


def diff_policies(old, new):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Set[str]]
    diff = {}
    old_actions = _create_simple_format(old)
    new_actions = _create_simple_format(new)
    removed = old_actions - new_actions
    added = new_actions - old_actions
    if removed:
        diff['removed'] = removed
    if added:
        diff['added'] = added
    return diff


def _create_simple_format(policy):
    # type: (Dict[str, Any]) -> Set[str]
    # This won't be sufficient is the analyzer is ever able
    # to work out which resources you're accessing.
    actions = set()  # type: Set[str]
    for statement in policy['Statement']:
        actions.update(statement['Action'])
    return actions


class AppPolicyGenerator(object):
    def __init__(self, osutils):
        # type: (OSUtils) -> None
        self._osutils = osutils

    def generate_policy(self, config):
        # type: (Config) -> Dict[str, Any]
        """Auto generate policy for an application."""
        # Admittedly, this is pretty bare bones logic for the time
        # being.  All it really does it work out, given a Config instance,
        # which files need to analyzed and then delegates to the
        # appropriately analyzer functions to do the real work.
        # This may change in the future.
        app_py = os.path.join(config.project_dir, 'app.py')
        assert self._osutils.file_exists(app_py)
        app_source = self._osutils.get_file_contents(app_py, binary=False)
        app_policy = policy_from_source_code(app_source)
        app_policy['Statement'].append(CLOUDWATCH_LOGS)
        if config.subnet_ids and config.security_group_ids:
            app_policy['Statement'].append(VPC_ATTACH_POLICY)
        return app_policy


class PolicyBuilder(object):
    VERSION = '2012-10-17'

    def __init__(self, session=None, policy_actions=None):
        # type: (Any, Dict[str, str]) -> None
        if session is None:
            session = botocore.session.get_session()
        if policy_actions is None:
            policy_actions = load_policy_actions()
        self._session = session
        self._policy_actions = policy_actions

    def build_policy_from_api_calls(self, client_calls):
        # type: (Dict[str, Set[str]]) -> Dict[str, Any]
        statements = self._build_statements_from_client_calls(client_calls)
        policy = {
            'Version': self.VERSION,
            'Statement': statements
        }
        return policy

    def _build_statements_from_client_calls(self, client_calls):
        # type: (Dict[str, Set[str]]) -> List[Dict[str, Any]]
        statements = []
        # client_calls = service_name -> set([method_calls])
        for service in sorted(client_calls):
            if service not in self._policy_actions:
                print("Unsupported service: %s" % service)
                continue
            service_actions = self._policy_actions[service]
            method_calls = client_calls[service]
            # Next thing we need to do is convert the method_name to
            # MethodName.  To this reliable we're going to use
            # botocore clients.
            client = self._session.create_client(service,
                                                 region_name='us-east-1')
            mapping = client.meta.method_to_api_mapping
            actions = [service_actions[mapping[method_name]] for
                       method_name in method_calls
                       if mapping.get(method_name) in service_actions]
            actions.sort()
            if actions:
                statements.append({
                    'Effect': 'Allow',
                    'Action': actions,
                    # Probably impossible, but it would be nice
                    # to even keep track of what resources are used
                    # so we can create ARNs and further restrict the policies.
                    'Resource': ['*'],
                    'Sid': str(uuid.uuid4()).replace('-', ''),
                })
        return statements
