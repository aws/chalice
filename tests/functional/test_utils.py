import zipfile
import json

from chalice import utils


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
        assert f.namelist() == [
            'hello.txt',
            'subdir/sub.txt',
            'subdir/sub2.txt',
            'subdir/subsubdir/leaf.txt',
        ]
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
