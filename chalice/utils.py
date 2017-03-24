import os
import zipfile
import json

from typing import IO, Dict, Any  # noqa


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
    with open(filename, 'w') as f:
        f.write(json.dumps(final_values, indent=2, separators=(',', ': ')))


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
