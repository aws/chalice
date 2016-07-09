import zipfile
from pytest import fixture

from chalice import deployer


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


def test_no_error_message_printed_on_empty_reqs_file(tmpdir,
                                                     chalice_deployer,
                                                     capfd):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Foo')
    appdir.join('requirements.txt').write('\n')
    chalice_deployer.create_deployment_package(str(appdir))
    out, err = capfd.readouterr()
    assert err.strip() == ''


def test_can_create_deployer_with_no_args(monkeypatch):
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'foo')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'bar')
    d = deployer.Deployer()
    assert isinstance(d, deployer.Deployer)
