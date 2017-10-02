import zipfile
import json
import os
import io

import pytest

from chalice import utils


@pytest.fixture
def osutils():
    return utils.OSUtils()


def test_can_zip_single_file(tmpdir):
    source = tmpdir.mkdir('sourcedir')
    source.join('hello.txt').write(b'hello world')
    outfile = str(tmpdir.join('out.zip'))
    utils.create_zip_file(source_dir=str(source),
                          outfile=outfile)
    with zipfile.ZipFile(outfile) as f:
        contents = f.read('hello.txt')
        assert contents == b'hello world'
        assert f.namelist() == ['hello.txt']


def test_can_zip_recursive_contents(tmpdir):
    source = tmpdir.mkdir('sourcedir')
    source.join('hello.txt').write(b'hello world')
    subdir = source.mkdir('subdir')
    subdir.join('sub.txt').write(b'sub.txt')
    subdir.join('sub2.txt').write(b'sub2.txt')
    subsubdir = subdir.mkdir('subsubdir')
    subsubdir.join('leaf.txt').write(b'leaf.txt')

    outfile = str(tmpdir.join('out.zip'))
    utils.create_zip_file(source_dir=str(source),
                          outfile=outfile)
    with zipfile.ZipFile(outfile) as f:
        assert sorted(f.namelist()) == sorted([
            'hello.txt',
            'subdir/sub.txt',
            'subdir/sub2.txt',
            'subdir/subsubdir/leaf.txt',
        ])
        assert f.read('subdir/subsubdir/leaf.txt') == b'leaf.txt'


def test_can_write_recorded_values(tmpdir):
    filename = str(tmpdir.join('deployed.json'))
    utils.record_deployed_values({'dev': {'deployed': 'foo'}}, filename)
    with open(filename, 'r') as f:
        assert json.load(f) == {'dev': {'deployed': 'foo'}}


def test_can_merge_recorded_values(tmpdir):
    filename = str(tmpdir.join('deployed.json'))
    first = {'dev': {'deployed': 'values'}}
    second = {'prod': {'deployed': 'values'}}
    utils.record_deployed_values(first, filename)
    utils.record_deployed_values(second, filename)
    combined = first.copy()
    combined.update(second)
    with open(filename, 'r') as f:
        data = json.load(f)
    assert data == combined


def test_can_remove_stage_from_deployed_values(tmpdir):
    filename = str(tmpdir.join('deployed.json'))
    deployed = {
        'dev': {'deployed': 'values'},
    }
    left_after_removal = {
        'prod': {'deployed': 'values'}
    }
    deployed.update(left_after_removal)
    with open(filename, 'wb') as f:
        f.write(json.dumps(deployed).encode('utf-8'))
    utils.remove_stage_from_deployed_values('dev', filename)

    with open(filename, 'r') as f:
        data = json.load(f)
    assert data == left_after_removal


def test_remove_stage_from_deployed_values_already_removed(tmpdir):
    filename = str(tmpdir.join('deployed.json'))
    deployed = {
        'dev': {'deployed': 'values'},
        'prod': {'deployed': 'values'}
    }
    with open(filename, 'wb') as f:
        f.write(json.dumps(deployed).encode('utf-8'))
    utils.remove_stage_from_deployed_values('fake_key', filename)

    with open(filename, 'r') as f:
        data = json.load(f)
    assert data == deployed


def test_remove_stage_from_deployed_values_no_file(tmpdir):
    filename = str(tmpdir.join('deployed.json'))
    utils.remove_stage_from_deployed_values('fake_key', filename)

    # Make sure it doesn't create the file if it didn't already exist
    assert not os.path.isfile(filename)


class TestOSUtils(object):
    def test_can_read_unicode(self, tmpdir, osutils):
        filename = str(tmpdir.join('file.txt'))
        checkmark = u'\2713'
        with io.open(filename, 'w', encoding='utf-16') as f:
            f.write(checkmark)

        content = osutils.get_file_contents(filename, binary=False,
                                            encoding='utf-16')
        assert content == checkmark
