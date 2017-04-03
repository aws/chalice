import os

from chalice.config import Config
from chalice import Chalice
from chalice import package



def _create_app_structure(tmpdir):
    appdir = tmpdir.mkdir('app')
    appdir.join('app.py').write('# Test app')
    appdir.mkdir('.chalice')
    return appdir


def sample_app():
    app = Chalice("sample_app")

    @app.route('/')
    def index():
        return {"hello": "world"}

    return app


def test_can_create_app_packager_with_no_autogen(tmpdir):
    appdir = _create_app_structure(tmpdir)

    outdir = tmpdir.mkdir('outdir')
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app())
    p = package.create_app_packager(config)
    p.package_app(config, str(outdir))
    # We're not concerned with the contents of the files
    # (those are tested in the unit tests), we just want to make
    # sure they're written to disk and look (mostly) right.
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.json' in contents


def test_will_create_outdir_if_needed(tmpdir):
    appdir = _create_app_structure(tmpdir)
    outdir = str(appdir.join('outdir'))
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app())
    p = package.create_app_packager(config)
    p.package_app(config, str(outdir))
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.json' in contents
