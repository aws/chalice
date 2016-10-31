import os
import zipfile
from pytest import fixture

import botocore.session

from chalice import deployer


@fixture(autouse=True)
def set_region(monkeypatch):
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-west-2')
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'foo')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'bar')
    monkeypatch.delenv('AWS_PROFILE', raising=False)
    # Ensure that the existing ~/.aws/{config,credentials} file
    # don't influence test results.
    monkeypatch.setenv('AWS_CONFIG_FILE', '/tmp/asdfasdfaf/does/not/exist')
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE',
                       '/tmp/asdfasdfaf/does/not/exist2')


@fixture
def chalice_deployer():
    d = deployer.LambdaDeploymentPackager()
    return d


def _create_app_structure(tmpdir):
    appdir = tmpdir.mkdir('app')
    appdir.join('app.py').write('# Test app')
    appdir.mkdir('.chalice')
    return appdir


def test_can_create_deployment_package(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Test app')
    chalice_dir = appdir.join('.chalice')
    chalice_deployer.create_deployment_package(str(appdir))
    # There should now be a zip file created.
    contents = chalice_dir.join('deployments').listdir()
    assert len(contents) == 1
    assert str(contents[0]).endswith('.zip')


def test_can_inject_latest_app(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Test app v1')
    chalice_dir = appdir.join('.chalice')
    name = chalice_deployer.create_deployment_package(str(appdir))

    # Now suppose we update our app code but not any deps.
    # We can use inject_latest_app.
    appdir.join('app.py').write('# Test app NEW VERSION')
    # There should now be a zip file created.
    chalice_deployer.inject_latest_app(name, str(appdir))
    contents = chalice_dir.join('deployments').listdir()
    assert len(contents) == 1
    assert str(contents[0]) == name
    with zipfile.ZipFile(name) as f:
        contents = f.read('app.py')
        assert contents == '# Test app NEW VERSION'


def test_app_injection_still_compresses_file(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Test app v1')
    name = chalice_deployer.create_deployment_package(str(appdir))
    original_size = os.path.getsize(name)
    appdir.join('app.py').write('# Test app v2')
    chalice_deployer.inject_latest_app(name, str(appdir))
    new_size = os.path.getsize(name)
    # The new_size won't be exactly the same as the original,
    # we just want to make sure it wasn't converted to
    # ZIP_STORED.
    assert abs(original_size - new_size) < 10


def test_no_error_message_printed_on_empty_reqs_file(tmpdir,
                                                     chalice_deployer,
                                                     capfd):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Foo')
    appdir.join('requirements.txt').write('\n')
    chalice_deployer.create_deployment_package(str(appdir))
    out, err = capfd.readouterr()
    assert err.strip() == ''


def test_can_create_deployer_from_factory_function():
    session = botocore.session.get_session()
    d = deployer.create_default_deployer(session)
    assert isinstance(d, deployer.Deployer)


def test_osutils_proxies_os_functions(tmpdir):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write(b'hello')

    osutils = deployer.OSUtils()

    app_file = str(appdir.join('app.py'))
    assert osutils.file_exists(app_file)
    assert osutils.get_file_contents(app_file) == b'hello'
    assert osutils.open(app_file, 'rb').read() == b'hello'
    osutils.remove_file(app_file)
    # Removing again doesn't raise an error.
    osutils.remove_file(app_file)
    assert not osutils.file_exists(app_file)


def test_includes_app_and_chalicelib_dir(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    # We're now also going to create additional files
    chalicelib = appdir.mkdir('chalicelib')
    appdir.join('chalicelib', '__init__.py').write('# Test package')
    appdir.join('chalicelib', 'mymodule.py').write('# Test module')
    appdir.join('chalicelib', 'config.json').write('{"test": "config"}')
    # Should also include sub directories
    subdir = chalicelib.mkdir('subdir')
    subdir.join('submodule.py').write('# Test submodule')
    subdir.join('subconfig.json').write('{"test": "subconfig"}')
    name = chalice_deployer.create_deployment_package(str(appdir))
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('chalicelib/__init__.py', '# Test package', f)
        _assert_in_zip('chalicelib/mymodule.py', '# Test module', f)
        _assert_in_zip('chalicelib/config.json', '{"test": "config"}', f)
        _assert_in_zip('chalicelib/subdir/submodule.py',
                       '# Test submodule', f)
        _assert_in_zip('chalicelib/subdir/subconfig.json',
                       '{"test": "subconfig"}', f)


def _assert_in_zip(path, contents, zip):
    allfiles = zip.namelist()
    assert path in allfiles
    assert zip.read(path) == contents


def test_subsequent_deploy_replaces_chalicelib(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    chalicelib = appdir.mkdir('chalicelib')
    appdir.join('chalicelib', '__init__.py').write('# Test package')
    subdir = chalicelib.mkdir('subdir')
    subdir.join('submodule.py').write('# Test submodule')

    name = chalice_deployer.create_deployment_package(str(appdir))
    subdir.join('submodule.py').write('# Test submodule v2')
    appdir.join('chalicelib', '__init__.py').remove()
    chalice_deployer.inject_latest_app(name, str(appdir))
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('chalicelib/subdir/submodule.py',
                       '# Test submodule v2', f)
        # And chalicelib/__init__.py should no longer be
        # in the zipfile because we deleted it in the appdir.
        assert 'chalicelib/__init__.py' not in f.namelist()
