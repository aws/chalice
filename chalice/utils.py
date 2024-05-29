import io
import os
import zipfile
import json
import contextlib
import tempfile
import re
import shutil
import sys
import tarfile
from datetime import datetime, timedelta
import subprocess
from os import PathLike  # noqa

from collections import OrderedDict  # noqa
import click
from typing import IO, Dict, List, Any, Tuple, Iterator, BinaryIO, Text  # noqa
from typing import Optional, Union  # noqa
from typing import MutableMapping, Callable  # noqa
from typing import cast  # noqa
import dateutil.parser
from dateutil.tz import tzutc

from chalice.constants import WELCOME_PROMPT

OptInt = Optional[int]
OptBytes = Optional[bytes]
EnvVars = MutableMapping
StrPath = Union[str, 'PathLike[str]']


class AbortedError(Exception):
    pass


def to_cfn_resource_name(name: str) -> str:
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


def remove_stage_from_deployed_values(key: str, filename: str) -> None:
    """Delete a top level key from the deployed JSON file."""
    final_values: Dict[str, Any] = {}
    try:
        with open(filename, 'r') as f:
            final_values = json.load(f)
    except IOError:
        # If there is no file to delete from, then this funciton is a noop.
        return

    try:
        del final_values[key]
        with open(filename, 'wb') as outfile:
            data = serialize_to_json(final_values)
            outfile.write(data.encode('utf-8'))
    except KeyError:
        # If they key didn't exist then there is nothing to remove.
        pass


def record_deployed_values(
    deployed_values: Dict[str, Any], filename: str
) -> None:
    """Record deployed values to a JSON file.

    This allows subsequent deploys to lookup previously deployed values.

    """
    final_values: Dict[str, Any] = {}
    if os.path.isfile(filename):
        with open(filename, 'r') as f:
            final_values = json.load(f)
    final_values.update(deployed_values)
    with open(filename, 'wb') as outfile:
        data = serialize_to_json(final_values)
        outfile.write(data.encode('utf-8'))


def serialize_to_json(data: Any) -> str:
    """Serialize to pretty printed JSON.

    This includes using 2 space indentation, no trailing whitespace, and
    including a newline at the end of the JSON document.  Useful when you want
    to serialize JSON to disk.

    """
    return json.dumps(data, indent=2, separators=(',', ': ')) + '\n'


class ChaliceZipFile(zipfile.ZipFile):
    """Support deterministic zipfile generation.

    Normalizes datetime and permissions.

    """

    compression = 0  # Try to make mypy happy.
    _default_time_time = (1980, 1, 1, 0, 0, 0)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._osutils = cast(OSUtils, kwargs.pop('osutils', OSUtils()))
        super(ChaliceZipFile, self).__init__(*args, **kwargs)

    # pylint: disable=W0221
    def write(
        self,
        filename: StrPath,
        arcname: Optional[StrPath] = None,
        compress_type: OptInt = None,
        compresslevel: OptInt = None,
    ) -> None:
        # Only supports files, py2.7 and 3 have different signatures.
        # We know that in our packager code we never call write() on
        # directories.
        zinfo = self._create_zipinfo(filename, arcname, compress_type)
        with open(filename, 'rb') as f:
            self.writestr(zinfo, f.read())

    def _create_zipinfo(
        self,
        filename: StrPath,
        arcname: Optional[StrPath],
        compress_type: Optional[int],
    ) -> zipfile.ZipInfo:
        # The main thing that prevents deterministic zip file generation
        # is that the mtime of the file is included in the zip metadata.
        # We don't actually care what the mtime is when we run on lambda,
        # so we always set it to the default value (which comes from
        # zipfile.py).  This ensures that as long as the file contents don't
        # change (or the permissions) then we'll always generate the exact
        # same zip file bytes.
        # We also can't use ZipInfo.from_file(), it's only in python3.
        st = self._osutils.stat(str(filename))
        if arcname is None:
            arcname = filename
        arcname = self._osutils.normalized_filename(str(arcname))
        arcname = arcname.lstrip(os.sep)
        zinfo = zipfile.ZipInfo(arcname, self._default_time_time)
        # The external_attr needs the upper 16 bits to be the file mode
        # so we have to shift it up to the right place.
        zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
        zinfo.file_size = st.st_size
        zinfo.compress_type = compress_type or self.compression
        return zinfo


def create_zip_file(source_dir: str, outfile: str) -> None:
    """Create a zip file from a source input directory.

    This function is intended to be an equivalent to
    `zip -r`.  You give it a source directory, `source_dir`,
    and it will recursively zip up the files into a zipfile
    specified by the `outfile` argument.

    """
    with ChaliceZipFile(
        outfile, 'w', compression=zipfile.ZIP_DEFLATED, osutils=OSUtils()
    ) as z:
        for root, _, filenames in os.walk(source_dir):
            for filename in filenames:
                full_name = os.path.join(root, filename)
                archive_name = os.path.relpath(full_name, source_dir)
                z.write(full_name, archive_name)


class OSUtils(object):
    ZIP_DEFLATED = zipfile.ZIP_DEFLATED

    def environ(self) -> MutableMapping:
        return os.environ

    def open(self, filename: str, mode: str) -> IO:
        return open(filename, mode)

    def open_zip(
        self, filename: str, mode: str, compression: int = ZIP_DEFLATED
    ) -> zipfile.ZipFile:
        return ChaliceZipFile(
            filename, mode, compression=compression, osutils=self
        )

    def remove_file(self, filename: str) -> None:
        """Remove a file, noop if file does not exist."""
        # Unlike os.remove, if the file does not exist,
        # then this method does nothing.
        try:
            os.remove(filename)
        except OSError:
            pass

    def file_exists(self, filename: str) -> bool:
        return os.path.isfile(filename)

    def get_file_contents(
        self, filename: str, binary: bool = True, encoding: Any = 'utf-8'
    ) -> str:
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

    def set_file_contents(
        self, filename: str, contents: str, binary: bool = True
    ) -> None:
        if binary:
            mode = 'wb'
        else:
            mode = 'w'
        with open(filename, mode) as f:
            f.write(contents)

    def extract_zipfile(self, zipfile_path: str, unpack_dir: str) -> None:
        with zipfile.ZipFile(zipfile_path, 'r') as z:
            z.extractall(unpack_dir)

    def extract_tarfile(self, tarfile_path: str, unpack_dir: str) -> None:
        with tarfile.open(tarfile_path, 'r:*') as tar:
            # In Python 3.12+, there's a `filter` arg where passing a
            # 'data' value will handle this behavior for us.  To support older
            # versions of Python we handle this ourselves.  We can't hook
            # into `extractall` directly so the idea is that we do a separate
            # validation pass first to ensure there's no files that try
            # to extract outside of the provided `unpack_dir`.  This is roughly
            # based off of what's done in the `data_filter()` in Python 3.12.
            self._validate_safe_extract(tar, unpack_dir)
            tar.extractall(unpack_dir)

    def _validate_safe_extract(
        self,
        tar: tarfile.TarFile,
        unpack_dir: str
    ) -> None:
        for member in tar:
            self._validate_single_tar_member(member, unpack_dir)

    def _validate_single_tar_member(
        self,
        member: tarfile.TarInfo,
        unpack_dir: str
    ) -> None:
        name = member.name
        dest_path = os.path.realpath(unpack_dir)
        if name.startswith(('/', os.sep)):
            name = member.path.lstrip('/' + os.sep)
        if os.path.isabs(name):
            raise RuntimeError(f"Absolute path in tarfile not allowed: {name}")
        target_path = os.path.realpath(os.path.join(dest_path, name))
        # Check we don't escape the destination dir, e.g `../../foo`
        if os.path.commonpath([target_path, dest_path]) != dest_path:
            raise RuntimeError(
                f"Tar member outside destination dir: {target_path}")
        # If we're dealing with a member that's some type of link, ensure
        # it doesn't point to anything outside of the destination dir.
        if member.islnk() or member.issym():
            if os.path.abspath(member.linkname):
                raise RuntimeError(f"Symlink to abspath: {member.linkname}")
            if member.issym():
                target_path = os.path.join(
                    dest_path,
                    os.path.dirname(name),
                    member.linkname,
                )
            else:
                target_path = os.path.join(
                    dest_path,
                    member.linkname)
            target_path = os.path.realpath(target_path)
            if os.path.commonpath([target_path, dest_path]) != dest_path:
                raise RuntimeError(
                    f"Symlink outside of dest dir: {target_path}")

    def directory_exists(self, path: str) -> bool:
        return os.path.isdir(path)

    def get_directory_contents(self, path: str) -> List[str]:
        return os.listdir(path)

    def makedirs(self, path: str) -> None:
        os.makedirs(path)

    def dirname(self, path: str) -> str:
        return os.path.dirname(path)

    def abspath(self, path: str) -> str:
        return os.path.abspath(path)

    def joinpath(self, *args: str) -> str:
        return os.path.join(*args)

    def walk(
        self, path: str, followlinks: bool = False
    ) -> Iterator[Tuple[str, List[str], List[str]]]:
        return os.walk(path, followlinks=followlinks)

    def copytree(self, source: str, destination: str) -> None:
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

    def rmtree(self, directory: str) -> None:
        shutil.rmtree(directory)

    def copy(self, source: str, destination: str) -> None:
        shutil.copy(source, destination)

    def move(self, source: str, destination: str) -> None:
        shutil.move(source, destination)

    @contextlib.contextmanager
    def tempdir(self) -> Any:
        tempdir = tempfile.mkdtemp()
        try:
            yield tempdir
        finally:
            shutil.rmtree(tempdir)

    def popen(
        self,
        command: List[str],
        stdout: OptInt = None,
        stderr: OptInt = None,
        env: Optional[EnvVars] = None,
    ) -> subprocess.Popen:
        p = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env)
        return p

    def mtime(self, path: str) -> float:
        return os.stat(path).st_mtime

    def stat(self, path: str) -> os.stat_result:
        return os.stat(path)

    def normalized_filename(self, path: str) -> str:
        """Normalize a path into a filename.

        This will normalize a file and remove any 'drive' component
        from the path on OSes that support drive specifications.

        """
        return os.path.normpath(os.path.splitdrive(path)[1])

    @property
    def pipe(self) -> int:
        return subprocess.PIPE

    def basename(self, path: str) -> str:
        return os.path.basename(path)


def getting_started_prompt(prompter: Any) -> bool:
    return prompter.prompt(WELCOME_PROMPT)


class UI(object):
    def __init__(
        self,
        out: Optional[IO] = None,
        err: Optional[IO] = None,
        confirm: Optional[Any] = None,
    ) -> None:
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

    def write(self, msg: str) -> None:
        self._out.write(msg)

    def error(self, msg: str) -> None:
        self._err.write(msg)

    def confirm(
        self, msg: str, default: bool = False, abort: bool = False
    ) -> Any:
        try:
            return self._confirm(msg, default, abort)
        except click.Abort:
            raise AbortedError()


class PipeReader(object):
    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream

    def read(self) -> OptBytes:
        if not self._stream.isatty():
            return self._stream.read()
        return None


class TimestampConverter(object):
    # This is roughly based off of what's used in the AWS CLI.
    _RELATIVE_TIMESTAMP_REGEX = re.compile(
        r"(?P<amount>\d+)(?P<unit>s|m|h|d|w)$"
    )
    _TO_SECONDS = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 24 * 3600,
        'w': 7 * 24 * 3600,
    }

    def __init__(self, now: Optional[Callable[[], datetime]] = None) -> None:
        if now is None:
            now = datetime.utcnow
        self._now = now

    def timestamp_to_datetime(self, timestamp: str) -> datetime:
        """Convert a timestamp to a datetime object.

        This method detects what type of timestamp is provided and
        parse is appropriately to a timestamp object.

        """
        re_match = self._RELATIVE_TIMESTAMP_REGEX.match(timestamp)
        if re_match:
            datetime_value = self._relative_timestamp_to_datetime(
                int(re_match.group('amount')), re_match.group('unit')
            )
        else:
            datetime_value = self.parse_iso8601_timestamp(timestamp)
        return datetime_value

    def _relative_timestamp_to_datetime(
        self, amount: int, unit: str
    ) -> datetime:
        multiplier = self._TO_SECONDS[unit]
        return self._now() + timedelta(seconds=amount * multiplier * -1)

    def parse_iso8601_timestamp(self, timestamp: str) -> datetime:
        return dateutil.parser.parse(timestamp, tzinfos={'GMT': tzutc()})
