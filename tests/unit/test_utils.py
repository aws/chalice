import re
import mock
import sys
import click
import pytest
from six import StringIO
from hypothesis.strategies import text
from hypothesis import given
import string

from chalice import utils


class TestUI(object):
    def setup(self):
        self.out = StringIO()
        self.err = StringIO()
        self.ui = utils.UI(self.out, self.err)

    def test_write_goes_to_out_obj(self):
        self.ui.write("Foo")
        assert self.out.getvalue() == 'Foo'
        assert self.err.getvalue() == ''

    def test_error_goes_to_err_obj(self):
        self.ui.error("Foo")
        assert self.err.getvalue() == 'Foo'
        assert self.out.getvalue() == ''

    def test_confirm_raises_own_exception(self):
        confirm = mock.Mock(spec=click.confirm)
        confirm.side_effect = click.Abort()
        ui = utils.UI(self.out, self.err, confirm)
        with pytest.raises(utils.AbortedError):
            ui.confirm("Confirm?")

    def test_confirm_returns_value(self):
        confirm = mock.Mock(spec=click.confirm)
        confirm.return_value = 'foo'
        ui = utils.UI(self.out, self.err, confirm)
        return_value = ui.confirm("Confirm?")
        assert return_value == 'foo'


class TestPipeReader(object):
    def test_pipe_reader_does_read_pipe(self):
        mock_stream = mock.Mock(spec=sys.stdin)
        mock_stream.isatty.return_value = False
        mock_stream.read.return_value = 'foobar'
        reader = utils.PipeReader(mock_stream)
        value = reader.read()
        assert value == 'foobar'

    def test_pipe_reader_does_not_read_tty(self):
        mock_stream = mock.Mock(spec=sys.stdin)
        mock_stream.isatty.return_value = True
        mock_stream.read.return_value = 'foobar'
        reader = utils.PipeReader(mock_stream)
        value = reader.read()
        assert value is None


def test_serialize_json():
    assert utils.serialize_to_json({'foo': 'bar'}) == (
        '{\n'
        '  "foo": "bar"\n'
        '}\n'
    )


@pytest.mark.parametrize('name,cfn_name', [
    ('f', 'F'),
    ('foo', 'Foo'),
    ('foo_bar', 'FooBar'),
    ('foo_bar_baz', 'FooBarBaz'),
    ('F', 'F'),
    ('FooBar', 'FooBar'),
    ('S3Bucket', 'S3Bucket'),
    ('s3Bucket', 'S3Bucket'),
    ('123', '123'),
    ('foo-bar-baz', 'FooBarBaz'),
    ('foo_bar-baz', 'FooBarBaz'),
    ('foo-bar_baz', 'FooBarBaz'),
    # Not actually possible, but we should
    # ensure we only have alphanumeric chars.
    ('foo_bar!?', 'FooBar'),
    ('_foo_bar', 'FooBar'),
])
def test_to_cfn_resource_name(name, cfn_name):
    assert utils.to_cfn_resource_name(name) == cfn_name


@given(name=text(alphabet=string.ascii_letters + string.digits + '-_'))
def test_to_cfn_resource_name_properties(name):
    try:
        result = utils.to_cfn_resource_name(name)
    except ValueError:
        # This is acceptable, the function raises ValueError
        # on bad input.
        pass
    else:
        assert re.search('[^A-Za-z0-9]', result) is None
