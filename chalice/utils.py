import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

import click
import yaml
from typing import IO, Dict, List, Any, Tuple, Iterator, BinaryIO  # noqa
from typing import Optional, Union  # noqa
from typing import MutableMapping  # noqa

from chalice.constants import WELCOME_PROMPT


OptInt = Optional[int]
OptStr = Optional[str]
EnvVars = MutableMapping


class AbortedError(Exception):
    pass


def to_cfn_resource_name(name):
    # type: (str) -> str
    """Transform a name to a valid cfn name.

    This will convert the provided name to a CamelCase name.
    It's possible that the conversion to a CFN resource name
    can result in name collisions.  It's up to the caller
    to handle name collisions appropriately.

    """
    if not name:
        raise ValueError("Invalid name: %r" % name)
    word_separators = ['-', '_']
    for word_separator in word_separators:
        word_parts = [p for p in name.split(word_separator) if p]
        name = ''.join([w[0].upper() + w[1:] for w in word_parts])
    return re.sub(r'[^A-Za-z0-9]+', '', name)


def remove_stage_from_deployed_values(key, filename):
    # type: (str, str) -> None
    """Delete a top level key from the deployed yaml file."""
    final_values = {}  # type: Dict[str, Any]
    f = None  # type: Optional[IO[Any]]
    try:
        with open(filename, 'r') as f:
            final_values = yaml.load(f)
    except IOError:
        # If there is no file to delete from, then this funciton is a noop.
        return

    try:
        del final_values[key]
        with io.open(filename, 'w', encoding='utf-8') as f:
            data = serialize_to_yaml(final_values)
            f.write(data)
    except KeyError:
        # If they key didn't exist then there is nothing to remove.
        pass


def record_deployed_values(deployed_values, filename):
    # type: (Dict[str, Any], str) -> None
    """Record deployed values to a yaml file.

    This allows subsequent deploys to lookup previously deployed values.

    """
    final_values = {}  # type: Dict[str, Any]
    f = None  # type: Optional[IO[Any]]
    if os.path.isfile(filename):
        with open(filename, 'r') as f:
            final_values = yaml.load(f)
    final_values.update(deployed_values)
    with io.open(filename, 'w', encoding='utf-8') as f:
        data = serialize_to_yaml(final_values)
        f.write(data)


def serialize_to_yaml(data):
    # type: (Any) -> Any
    """Serialize to pretty printed yaml.

    This includes using 2 space indentation, no trailing whitespace, and
    including a newline at the end of the yaml document.  Useful when you want
    to serialize yaml  to disk.

    """
    b = io.StringIO()
    b.write('---\n')
    yaml.dump(data, indent=2, stream=b, default_flow_style=False)
    return b.getvalue()


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

    def environ(self):
        # type: () -> MutableMapping
        return os.environ

    def open(self, filename, mode):
        # type: (str, str) -> IO
        return open(filename, mode)

    def open_zip(self, filename, mode, compression=ZIP_DEFLATED):
        # type: (str, str, int) -> zipfile.ZipFile
        return zipfile.ZipFile(filename, mode, compression=compression)

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

    def get_file_contents(self, filename, binary=True, encoding='utf-8'):
        # type: (str, bool, Any) -> str
        # It looks like the type definition for io.open is wrong.
        # the encoding arg is unicode, but the actual type is
        # Optional[Text].  For now we have to use Any to keep mypy happy.
        if binary:
            mode = 'rb'
            # In binary mode the encoding is not used and most be None.
            encoding = None
        else:
            mode = 'r'
        with io.open(filename, mode, encoding=encoding) as f:
            return f.read()

    def get_buffered_contents(self, filename, binary=True, encoding='utf-8'):
        # type: (str, bool, Any) -> IO[Any]
        # It looks like the type definition for io.open is wrong.
        # the encoding arg is unicode, but the actual type is
        # Optional[Text].  For now we have to use Any to keep mypy happy.
        if binary:
            mode = 'rb'
            # In binary mode the encoding is not used and most be None.
            encoding = None
        else:
            mode = 'r'
        return io.open(filename, mode, encoding=encoding)

    def set_file_contents(self, filename, contents, binary=True):
        # type: (str, str, bool) -> None
        if binary:
            mode = 'wb'
        else:
            mode = 'w'
        with open(filename, mode) as f:
            f.write(contents)

    def extract_zipfile(self, zipfile_path, unpack_dir):
        # type: (str, str) -> None
        with zipfile.ZipFile(zipfile_path, 'r') as z:
            z.extractall(unpack_dir)

    def extract_tarfile(self, tarfile_path, unpack_dir):
        # type: (str, str) -> None
        with tarfile.open(tarfile_path, 'r:*') as tar:
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

    def copy(self, source, destination):
        # type: (str, str) -> None
        shutil.copy(source, destination)

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

    def popen(self, command, stdout=None, stderr=None, env=None):
        # type: (List[str], OptInt, OptInt, EnvVars) -> subprocess.Popen
        p = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env)
        return p

    def mtime(self, path):
        # type: (str) -> int
        return os.stat(path).st_mtime

    @property
    def pipe(self):
        # type: () -> int
        return subprocess.PIPE


def getting_started_prompt(prompter):
    # type: (Any) -> bool
    return prompter.prompt(WELCOME_PROMPT)


class UI(object):
    def __init__(self, out=None, err=None, confirm=None):
        # type: (Optional[IO], Optional[IO], Any) -> None
        # I tried using a more exact type for the 'confirm'
        # param, but mypy seems to miss the 'if confirm is None'
        # check and types _confirm as Union[..., None].
        # So for now, we're using Any for this type.
        if out is None:
            out = sys.stdout
        if err is None:
            err = sys.stderr
        if confirm is None:
            confirm = click.confirm
        self._out = out
        self._err = err
        self._confirm = confirm

    def write(self, msg):
        # type: (str) -> None
        self._out.write(msg)

    def error(self, msg):
        # type: (str) -> None
        self._err.write(msg)

    def confirm(self, msg, default=False, abort=False):
        # type: (str, bool, bool) -> Any
        try:
            return self._confirm(msg, default, abort)
        except click.Abort:
            raise AbortedError()


class PipeReader(object):
    def __init__(self, stream):
        # type: (IO[str]) -> None
        self._stream = stream

    def read(self):
        # type: () -> OptStr
        if not self._stream.isatty():
            return self._stream.read()
        return None


def replace_yaml_extension(yaml_filename):
    # type: (str) -> str
    """
    Replace yaml suffixes with json suffixes.

    This allows the newer version of chalice that is looking for
    yaml files to work nicely with legacy .json files.
    """
    return re.sub(r'\.ya?ml$', '.json', yaml_filename)
