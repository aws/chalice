"""Control plane APIs for programatically building/deploying Chalice apps.

The eventual goal is to expose this as a public API that other tools can use
in their own integrations with Chalice, but this will need time for the APIs
to mature so for the time being this is an internal-only API.
"""
import os
from typing import Optional, Dict, Any
from chalice.cli.factory import CLIFactory


def package_app(project_dir: str,
                output_dir: str,
                stage: str,
                chalice_config: Optional[Dict[str, Any]] = None,
                package_format: str = 'cloudformation',
                template_format: str = 'json') -> None:
    factory = CLIFactory(project_dir, environ=os.environ)
    if chalice_config is None:
        chalice_config = {}
    config = factory.create_config_obj(
        stage, user_provided_params=chalice_config)
    options = factory.create_package_options()
    packager = factory.create_app_packager(config, options,
                                           package_format=package_format,
                                           template_format=template_format)
    packager.package_app(config, output_dir, stage)
