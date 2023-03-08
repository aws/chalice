"""New project generation.

How it Works
============

Project template are placed with the ./chalice/templates directory.  Each
directory corresponds to a single template.  The name of the directory has
the structure ``0123-template-name``, where the first part consists of a four
digit number followed by a ``-``, then the name of the template.  The leading
number is not exposed externally to the user and is used solely for sorting
purposes so we can display the project templates in the order we prefer.
The template name is the name that's used in the ``--project-type`` value
for the ``new-project`` command.

Each template can have a ``DESCRIPTION`` file that contains a short
description of the project template.  This will be used as the display
value instead of the project type key if this file is available.  The
``DESCRIPTION`` file is not copied over when generating the new project
files.

There's basic support for templating values.  This allows you to write
templates with placeholder values that are filled in during project
generation time.  These values are denoted via ``{{template_var}}``.
The following keys are supported:

* ``app_name`` - The name of the project.
* ``chalice_version`` - The current version of chalice generating the project.

"""
from __future__ import print_function
import os
import re
import json
import fnmatch
from dataclasses import dataclass
from typing import Optional, Dict, Any, Iterator, Tuple, Match, List  # noqa

import inquirer

from chalice.constants import WELCOME_PROMPT
from chalice.utils import OSUtils
from chalice.app import __version__ as chalice_version


TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates'
)
VAR_REF_REGEX = r'{{(.*?)}}'
IGNORE_FILES = ['metadata.json', '*.pyc']


class BadTemplateError(Exception):
    pass


def create_new_project_skeleton(
    project_name: str, project_type: Optional[str] = 'legacy'
) -> None:
    osutils = OSUtils()
    all_projects = list_available_projects(TEMPLATES_DIR, osutils)
    project = [p for p in all_projects if p.key == project_type][0]
    template_kwargs = {
        'app_name': project_name,
        'chalice_version': chalice_version,
    }
    project_creator = ProjectCreator(osutils)
    project_creator.create_new_project(
        os.path.join(TEMPLATES_DIR, project.dirname),
        project_name,
        template_kwargs=template_kwargs,
    )


@dataclass
class ProjectTemplate:
    dirname: str
    metadata: Dict[str, Any]
    key: str

    @property
    def description(self) -> str:
        # Pylint doesn't understand the attrs types.
        # pylint: disable=no-member
        return self.metadata.get('description', self.key)


class ProjectCreator(object):
    def __init__(self, osutils: Optional[OSUtils] = None) -> None:
        if osutils is None:
            osutils = OSUtils()
        self._osutils = osutils

    def create_new_project(
        self,
        source_dir: str,
        destination_dir: str,
        template_kwargs: Dict[str, Any],
    ) -> None:
        for full_src_path, full_dst_path in self._iter_files(
            source_dir, destination_dir
        ):
            dest_dir = self._osutils.dirname(full_dst_path)
            if not self._osutils.directory_exists(dest_dir):
                self._osutils.makedirs(dest_dir)
            contents = self._osutils.get_file_contents(
                full_src_path, binary=False
            )
            templated_contents = get_templated_content(
                contents, template_kwargs
            )
            self._osutils.set_file_contents(
                full_dst_path, templated_contents, binary=False
            )

    def _iter_files(
        self, source_dir: str, destination_dir: str
    ) -> Iterator[Tuple[str, str]]:
        for rootdir, _, filenames in self._osutils.walk(source_dir):
            for filename in filenames:
                if self._should_ignore(filename):
                    continue
                full_src_path = os.path.join(rootdir, filename)
                # The starting index needs `+ 1` to account for the
                # trailing `/` char (e.g. foo/bar -> foo/bar/).
                full_dst_path = os.path.join(
                    destination_dir, full_src_path[len(source_dir) + 1:]
                )
                yield full_src_path, full_dst_path

    def _should_ignore(self, filename: str) -> bool:
        for ignore in IGNORE_FILES:
            if fnmatch.fnmatch(filename, ignore):
                return True
        return False


def get_templated_content(
    contents: str, template_kwargs: Dict[str, Any]
) -> str:
    def lookup_var(match: Match) -> str:
        var_name = match.group(1)
        try:
            return template_kwargs[var_name]
        except KeyError:
            raise BadTemplateError(
                "Bad template, referenced template var that does not "
                "exist: '%s', for template contents:\n%s"
                % (var_name, contents)
            )

    new_contents = re.sub(VAR_REF_REGEX, lookup_var, contents)
    return new_contents


def list_available_projects(
    templates_dir: str, osutils: OSUtils
) -> List[ProjectTemplate]:
    projects = []
    for dirname in sorted(osutils.get_directory_contents(templates_dir)):
        filename = osutils.joinpath(templates_dir, dirname, 'metadata.json')
        metadata = json.loads(osutils.get_file_contents(filename, False))
        key = dirname.split('-', 1)[1]
        projects.append(ProjectTemplate(dirname, metadata, key=key))
    return projects


def getting_started_prompt() -> Dict[str, Any]:
    print(WELCOME_PROMPT)
    projects = list_available_projects(TEMPLATES_DIR, OSUtils())
    questions = [
        inquirer.Text('project_name', message='Enter the project name'),
        inquirer.List(
            'project_type',
            message='Select your project type',
            choices=[(p.description, p.key) for p in projects],
        ),
    ]
    answers = inquirer.prompt(questions)
    return answers
