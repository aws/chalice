import os
import zipfile
import json
import contextlib
import tempfile
import shutil
import tarfile

from typing import IO, Dict, List, Any, Tuple, Iterator, BinaryIO  # noqa

from chalice.constants import WELCOME_PROMPT


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
    ZIP_DEFLATED = zipfile.ZIP_DEFLATED

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

    @contextlib.contextmanager
    def get_file_context(self, filename, mode='r'):
        # type: (str, str) -> Iterator[BinaryIO]
        try:
            f = open(filename, mode)
            yield f
        finally:
            f.close()

    def set_file_contents(self, filename, contents, binary=True):
        # type: (str, str, bool) -> None
        if binary:
            mode = 'wb'
        else:
            mode = 'w'
        with open(filename, mode) as f:
            f.write(contents)

    def unpack_zipfile(self, zipfile_path, unpack_dir):
        # type: (str, str) -> None
        with zipfile.ZipFile(zipfile_path, 'r') as z:
            z.extractall(unpack_dir)

    @contextlib.contextmanager
    def zipfile_context(self, filename, mode='r',
                        compression=zipfile.ZIP_STORED):
        # type: (str, str, int) -> Iterator[zipfile.ZipFile]
        try:
            z = zipfile.ZipFile(filename, mode=mode, compression=compression)
            yield z
        finally:
            z.close()

    def unpack_tarfile(self, tarfile_path, unpack_dir):
        # type: (str, str) -> None
        with tarfile.open(tarfile_path, 'r:gz') as tar:
            tar.extractall(unpack_dir)

    def directory_exists(self, path):
        # type: (str) -> bool
        return os.path.isdir(path)

    def get_directory_contents(self, path):
        # type: (str) -> List[str]
        return os.listdir(path)

    def makedirs(self, path):
        # type: (str) -> None
        os.makedirs(path)

    def dirname(self, path):
        # type: (str) -> str
        return os.path.dirname(path)

    def abspath(self, path):
        # type: (str) -> str
        return os.path.abspath(path)

    def joinpath(self, *args):
        # type: (str) -> str
        return os.path.join(*args)

    def walk(self, path):
        # type: (str) -> Iterator[Tuple[str, List[str], List[str]]]
        return os.walk(path)

    def copytree(self, source, destination):
        # type: (str, str) -> None
        if not os.path.exists(destination):
            self.makedirs(destination)
        names = self.get_directory_contents(source)
        for name in names:
            new_source = os.path.join(source, name)
            new_destination = os.path.join(destination, name)
            if os.path.isdir(new_source):
                self.copytree(new_source, new_destination)
            else:
                shutil.copy2(new_source, new_destination)

    def rmtree(self, directory):
        # type: (str) -> None
        shutil.rmtree(directory)

    def move(self, source, destination):
        # type: (str, str) -> None
        shutil.move(source, destination)

    @contextlib.contextmanager
    def tempdir(self):
        # type: () -> Any
        tempdir = tempfile.mkdtemp()
        try:
            yield tempdir
        finally:
            shutil.rmtree(tempdir)


def getting_started_prompt(prompter):
    # type: (Any) -> bool
    return prompter.prompt(WELCOME_PROMPT)
