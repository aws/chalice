import os
import zipfile
import json

from typing import IO, Dict, Any  # noqa

from chalice import __version__ as chalice_version
from chalice.constants import WELCOME_PROMPT
from chalice.config import Config  # noqa


def get_application_tags(config):
    # type: (Config) -> Dict[str, str]
    """Return a chalice application's configured tags.

    This will pull tags from the provided config object and inject
    the default aws-chalice tag as well.
    """
    tags = {}
    if config.tags:
        tags.update(config.tags)
    tags['aws-chalice'] = 'version=%s:stage=%s:app=%s' % (
        chalice_version, config.chalice_stage, config.app_name)
    return tags


def remove_stage_from_deployed_values(key, filename):
    # type: (str, str) -> None
    """Delete a top level key from the deployed JSON file."""
    final_values = {}  # type: Dict[str, Any]
    try:
        with open(filename, 'r') as f:
            final_values = json.load(f)
    except IOError:
        # If there is no file to delete from, then this funciton is a noop.
        return

    try:
        del final_values[key]
        with open(filename, 'wb') as f:
            data = json.dumps(final_values, indent=2, separators=(',', ': '))
            f.write(data.encode('utf-8'))
    except KeyError:
        # If they key didn't exist then there is nothing to remove.
        pass


def record_deployed_values(deployed_values, filename):
    # type: (Dict[str, str], str) -> None
    """Record deployed values to a JSON file.

    This allows subsequent deploys to lookup previously deployed values.

    """
    final_values = {}  # type: Dict[str, Any]
    if os.path.isfile(filename):
        with open(filename, 'r') as f:
            final_values = json.load(f)
    final_values.update(deployed_values)
    with open(filename, 'wb') as f:
        data = json.dumps(final_values, indent=2, separators=(',', ': '))
        f.write(data.encode('utf-8'))


def create_zip_file(source_dir, outfile):
    # type: (str, str) -> None
    """Create a zip file from a source input directory.

    This function is intended to be an equivalent to
    `zip -r`.  You give it a source directory, `source_dir`,
    and it will recursively zip up the files into a zipfile
    specified by the `outfile` argument.

    """
    with zipfile.ZipFile(outfile, 'w',
                         compression=zipfile.ZIP_DEFLATED) as z:
        for root, _, filenames in os.walk(source_dir):
            for filename in filenames:
                full_name = os.path.join(root, filename)
                archive_name = os.path.relpath(full_name, source_dir)
                z.write(full_name, archive_name)


class OSUtils(object):
    def open(self, filename, mode):
        # type: (str, str) -> IO
        return open(filename, mode)

    def remove_file(self, filename):
        # type: (str) -> None
        """Remove a file, noop if file does not exist."""
        # Unlike os.remove, if the file does not exist,
        # then this method does nothing.
        try:
            os.remove(filename)
        except OSError:
            pass

    def file_exists(self, filename):
        # type: (str) -> bool
        return os.path.isfile(filename)

    def get_file_contents(self, filename, binary=True):
        # type: (str, bool) -> str
        if binary:
            mode = 'rb'
        else:
            mode = 'r'
        with open(filename, mode) as f:
            return f.read()

    def set_file_contents(self, filename, contents, binary=True):
        # type: (str, str, bool) -> None
        if binary:
            mode = 'wb'
        else:
            mode = 'w'
        with open(filename, mode) as f:
            f.write(contents)


def getting_started_prompt(prompter):
    # type: (Any) -> bool
    return prompter.prompt(WELCOME_PROMPT)
