"""Policy generator based on allowed API calls.

This module will take a set of API calls for services
and make a best effort attempt to generate an IAM policy
for you.

"""
import os
import json
import uuid

from typing import Any, List, Dict, Set  # noqa

import botocore.session


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
                print "Unsupported service:", service
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
