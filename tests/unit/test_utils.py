import mock
import click
import pytest
from six import StringIO

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


def test_serialize_json():
    assert utils.serialize_to_json({'foo': 'bar'}) == (
        '{\n'
        '  "foo": "bar"\n'
        '}\n'
    )
