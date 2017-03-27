import zipfile

from chalice import utils


def test_can_zip_single_file(tmpdir):
    source = tmpdir.mkdir('sourcedir')
    source.join('hello.txt').write('hello world')
    outfile = str(tmpdir.join('out.zip'))
    utils.create_zip_file(source_dir=str(source),
                          outfile=outfile)
    with zipfile.ZipFile(outfile) as f:
        contents = f.read('hello.txt')
        assert contents == 'hello world'
        assert f.namelist() == ['hello.txt']


def test_can_zip_recursive_contents(tmpdir):
    source = tmpdir.mkdir('sourcedir')
    source.join('hello.txt').write('hello world')
    subdir = source.mkdir('subdir')
    subdir.join('sub.txt').write('sub.txt')
    subdir.join('sub2.txt').write('sub2.txt')
    subsubdir = subdir.mkdir('subsubdir')
    subsubdir.join('leaf.txt').write('leaf.txt')

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
        assert f.read('subdir/subsubdir/leaf.txt') == 'leaf.txt'
