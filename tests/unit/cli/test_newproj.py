import os

import pytest

from chalice.cli import newproj


class InMemoryOSUtils(object):
    def __init__(self, filemap=None):
        if filemap is None:
            filemap = {}
        self.filemap = filemap
        self.walk_return_val = None

    def dirname(self, name):
        return os.path.dirname(name)

    def get_directory_contents(self, dirname):
        full_paths = [f for f in self.filemap if f.startswith(dirname)]
        return [p.split(os.sep)[1] for p in full_paths]

    def file_exists(self, filename):
        return filename in self.filemap

    def joinpath(self, *args):
        return os.path.join(*args)

    def walk(self, root_dir):
        return self.walk_return_value

    def directory_exists(self, dirname):
        return True

    def get_file_contents(self, filename, binary=True):
        return self.filemap[filename]

    def set_file_contents(self, filename, contents, binary=True):
        self.filemap[filename] = contents


@pytest.mark.parametrize(
    'contents,template_kwargs,expected', [
        ('{{myvar}}', {'myvar': 'foo'}, 'foo'),
        ('{{myvar}}', {'myvar': 'foo', 'myvar2': 'bar'}, 'foo'),
        ('before {{myvar}} after', {'myvar': 'foo'}, 'before foo after'),
        ('newlines\n{{myvar}}\nbar', {'myvar': 'foo'}, 'newlines\nfoo\nbar'),
        ('NAME = "{{myvar}}"', {'myvar': 'foo'}, 'NAME = "foo"'),
        ('{{one}}{{two}}', {'one': 'foo', 'two': 'bar'}, 'foobar'),
        ('{nomatch}', {'nomatch': 'bar'}, '{nomatch}'),
        ('no template', {'nomatch': 'bar'}, 'no template'),
        ('', {}, ''),
        ('{{noclose', {}, '{{noclose'),
        ('nostart}}', {}, 'nostart}}'),
        ('{{unknown_var}}', {}, newproj.BadTemplateError()),
    ]
)
def test_can_get_templated_content(contents, template_kwargs, expected):
    if isinstance(expected, Exception):
        with pytest.raises(expected.__class__):
            newproj.get_templated_content(contents, template_kwargs)
    else:
        newproj.get_templated_content(contents, template_kwargs) == expected


def test_newproj_copies_and_templates_files():
    fake_osutils = InMemoryOSUtils()
    fake_osutils.walk_return_value = [
        ('source_dir', [], ['foo', 'bar']),
    ]
    fake_osutils.filemap = {
        os.path.join('source_dir', 'foo'): 'hello',
        os.path.join('source_dir', 'bar'): '{{who}}',
    }
    creator = newproj.ProjectCreator(fake_osutils)
    creator.create_new_project('source_dir', 'dest_dir', {'who': 'world'})
    assert fake_osutils.filemap[os.path.join('dest_dir', 'foo')] == 'hello'
    assert fake_osutils.filemap[os.path.join('dest_dir', 'bar')] == 'world'


def test_can_list_available_projects():
    fake_osutils = InMemoryOSUtils()
    join = os.path.join
    first_dir = join('template-dir', '0001-first-proj')
    second_dir = join('template-dir', '0002-second-proj')
    fake_osutils.filemap = {
        join(first_dir, 'metadata.json'): '{"description": "First template"}',
        join(second_dir, 'metadata.json'): '{"description": "Second"}',

    }
    results = newproj.list_available_projects('template-dir', fake_osutils)
    assert results == [
        newproj.ProjectTemplate(
            dirname='0001-first-proj',
            metadata={'description': 'First template'},
            key='first-proj',
        ),
        newproj.ProjectTemplate(
            dirname='0002-second-proj',
            metadata={'description': 'Second'},
            key='second-proj',
        ),
    ]
