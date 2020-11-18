import os
import zipfile
import json
import mock
import hashlib

from pytest import fixture
import pytest

import chalice.deploy.deployer
import chalice.deploy.packager
from chalice.awsclient import TypedAWSClient
import chalice.utils
from chalice.config import Config
from chalice import Chalice
from chalice.deploy.packager import MissingDependencyError
from chalice.deploy.packager import EmptyPackageError
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.packager import DependencyBuilder
from chalice.deploy.packager import Package


slow = pytest.mark.slow


@fixture
def chalice_deployer():
    ui = chalice.utils.UI()
    osutils = chalice.utils.OSUtils()
    dependency_builder = mock.Mock(spec=DependencyBuilder)
    d = chalice.deploy.packager.LambdaDeploymentPackager(
        osutils=osutils, dependency_builder=dependency_builder,
        ui=ui
    )
    return d


@fixture
def app_only_packager():
    ui = chalice.utils.UI()
    osutils = chalice.utils.OSUtils()
    dependency_builder = mock.Mock(spec=DependencyBuilder)
    d = chalice.deploy.packager.AppOnlyDeploymentPackager(
        osutils=osutils, dependency_builder=dependency_builder,
        ui=ui
    )
    return d, dependency_builder


@fixture
def layer_packager():
    ui = chalice.utils.UI()
    osutils = chalice.utils.OSUtils()
    dependency_builder = mock.Mock(spec=DependencyBuilder)
    d = chalice.deploy.packager.LayerDeploymentPackager(
        osutils=osutils, dependency_builder=dependency_builder,
        ui=ui
    )
    return d, dependency_builder


def _create_app_structure(tmpdir):
    appdir = tmpdir.mkdir('app')
    appdir.join('app.py').write('# Test app')
    appdir.mkdir('.chalice')
    return appdir


@slow
def test_can_create_deployment_package(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Test app')
    chalice_dir = appdir.join('.chalice')
    chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    # There should now be a zip file created.
    contents = chalice_dir.join('deployments').listdir()
    assert len(contents) == 1
    assert str(contents[0]).endswith('.zip')


@slow
def test_can_inject_latest_app(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Test app v1')
    chalice_dir = appdir.join('.chalice')
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')

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
        assert contents == b'# Test app NEW VERSION'


@slow
def test_zipfile_hash_only_based_on_contents(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Test app v1')
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with open(name, 'rb') as f:
        original_checksum = hashlib.md5(f.read()).hexdigest()

    # Now we'll modify the file our app file with the same contents
    # but it will change the mtime.
    app_file = appdir.join('app.py')
    app_file.write('# Test app v1')
    # Set the mtime to something different (1990-1-1T00:00:00).
    # This would normally result in the zipfile having a different
    # checksum.
    os.utime(str(app_file), (631152000.0, 631152000.0))
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with open(name, 'rb') as f:
        new_checksum = hashlib.md5(f.read()).hexdigest()
    assert new_checksum == original_checksum


@slow
def test_app_injection_still_compresses_file(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Test app v1')
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    original_size = os.path.getsize(name)
    appdir.join('app.py').write('# Test app v2')
    chalice_deployer.inject_latest_app(name, str(appdir))
    new_size = os.path.getsize(name)
    # The new_size won't be exactly the same as the original,
    # we just want to make sure it wasn't converted to
    # ZIP_STORED, so there's a 5% tolerance.
    assert new_size < (original_size * 1.05)


@slow
def test_no_error_message_printed_on_empty_reqs_file(tmpdir,
                                                     chalice_deployer,
                                                     capfd):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write('# Foo')
    appdir.join('requirements.txt').write('\n')
    chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    out, err = capfd.readouterr()
    assert err.strip() == ''


def test_osutils_proxies_os_functions(tmpdir):
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write(b'hello')

    osutils = chalice.utils.OSUtils()

    app_file = str(appdir.join('app.py'))
    assert osutils.file_exists(app_file)
    assert osutils.get_file_contents(app_file) == b'hello'
    assert osutils.open(app_file, 'rb').read() == b'hello'
    osutils.remove_file(app_file)
    # Removing again doesn't raise an error.
    osutils.remove_file(app_file)
    assert not osutils.file_exists(app_file)


@slow
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
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('chalicelib/__init__.py', b'# Test package', f)
        _assert_in_zip('chalicelib/mymodule.py', b'# Test module', f)
        _assert_in_zip('chalicelib/config.json', b'{"test": "config"}', f)
        _assert_in_zip('chalicelib/subdir/submodule.py',
                       b'# Test submodule', f)
        _assert_in_zip('chalicelib/subdir/subconfig.json',
                       b'{"test": "subconfig"}', f)


def _assert_in_zip(path, contents, zip):
    allfiles = zip.namelist()
    assert path in allfiles
    assert zip.read(path) == contents


def _assert_not_in_zip(path, zip):
    allfiles = zip.namelist()
    assert path not in allfiles


@slow
def test_subsequent_deploy_replaces_chalicelib(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    chalicelib = appdir.mkdir('chalicelib')
    appdir.join('chalicelib', '__init__.py').write('# Test package')
    subdir = chalicelib.mkdir('subdir')
    subdir.join('submodule.py').write('# Test submodule')

    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    subdir.join('submodule.py').write('# Test submodule v2')
    appdir.join('chalicelib', '__init__.py').remove()
    chalice_deployer.inject_latest_app(name, str(appdir))
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('chalicelib/subdir/submodule.py',
                       b'# Test submodule v2', f)
        # And chalicelib/__init__.py should no longer be
        # in the zipfile because we deleted it in the appdir.
        assert 'chalicelib/__init__.py' not in f.namelist()


@slow
def test_vendor_dir_included(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    vendor = appdir.mkdir('vendor')
    extra_package = vendor.mkdir('mypackage')
    extra_package.join('__init__.py').write('# Test package')
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('mypackage/__init__.py', b'# Test package', f)


@slow
def test_no_vendor_in_app_only_packager(tmpdir, app_only_packager):
    packager, deps_builder = app_only_packager
    appdir = _create_app_structure(tmpdir)
    appdir.mkdir('chalicelib')
    appdir.join('requirements.txt').write('boto3')
    appdir.join('chalicelib', '__init__.py').write('# Test package')
    vendor = appdir.mkdir('vendor')
    extra_package = vendor.mkdir('mypackage')
    extra_package.join('__init__.py').write('# Test package')
    name = packager.create_deployment_package(
        str(appdir), 'python2.7')
    with zipfile.ZipFile(name) as f:
        _assert_not_in_zip('mypackage/__init__.py', f)
        _assert_in_zip('chalicelib/__init__.py', b'# Test package', f)
        _assert_in_zip('app.py', b'# Test app', f)
    assert not deps_builder.build_site_packages.called


@slow
def test_py_deps_in_layer_package(tmpdir, layer_packager):
    packager, deps_builder = layer_packager
    appdir = _create_app_structure(tmpdir)
    appdir.mkdir('chalicelib')
    appdir.join('requirements.txt').write('boto3')
    appdir.join('chalicelib', '__init__.py').write('# Test package')
    vendor = appdir.mkdir('vendor')
    extra_package = vendor.mkdir('mypackage')
    extra_package.join('__init__.py').write('# Test package')
    name = packager.create_deployment_package(
        str(appdir), 'python2.7')
    assert os.path.basename(name).startswith('managed-layer-')
    with zipfile.ZipFile(name) as f:
        prefix = 'python/lib/python2.7/site-packages'
        _assert_in_zip(
            '%s/mypackage/__init__.py' % prefix, b'# Test package', f)
        _assert_not_in_zip('%s/chalicelib/__init__.py' % prefix, f)
        _assert_not_in_zip('%s/app.py' % prefix, f)
    deps_builder.build_site_packages.assert_called_with(
        'cp27mu', str(appdir.join('requirements.txt')), mock.ANY
    )


def test_empty_layer_package_raises_error(tmpdir, layer_packager):
    packager, deps_builder = layer_packager
    appdir = _create_app_structure(tmpdir)
    appdir.mkdir('chalicelib')
    appdir.join('requirements.txt').write('')
    appdir.join('chalicelib', '__init__.py').write('# Test package')
    filename = packager.deployment_package_filename(str(appdir), 'python2.7')
    with pytest.raises(EmptyPackageError):
        packager.create_deployment_package(
            str(appdir), 'python2.7')
    # We should also verify that the file does not exist so it doesn't
    # get reused in subsequent caches.  This shouldn't affect anything,
    # we're just trying to cleanup properly.
    assert not os.path.isfile(filename)


@slow
def test_subsequent_deploy_replaces_vendor_dir(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    vendor = appdir.mkdir('vendor')
    extra_package = vendor.mkdir('mypackage')
    extra_package.join('__init__.py').write('# v1')
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    # Now we update a package in vendor/ with a new version.
    extra_package.join('__init__.py').write('# v2')
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('mypackage/__init__.py', b'# v2', f)


@slow
def test_vendor_symlink_included(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    extra_package = tmpdir.mkdir('mypackage')
    extra_package.join('__init__.py').write('# Test package')
    vendor = appdir.mkdir('vendor')
    os.symlink(str(extra_package), str(vendor.join('otherpackage')))
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('otherpackage/__init__.py', b'# Test package', f)


@slow
def test_subsequent_deploy_replaces_vendor_symlink(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    extra_package = tmpdir.mkdir('mypackage')
    extra_package.join('__init__.py').write('# v1')
    vendor = appdir.mkdir('vendor')
    os.symlink(str(extra_package), str(vendor.join('otherpackage')))
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('otherpackage/__init__.py', b'# v1', f)
    # Now we update a package in vendor/ with a new version.
    extra_package.join('__init__.py').write('# v2')
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    with zipfile.ZipFile(name) as f:
        _assert_in_zip('otherpackage/__init__.py', b'# v2', f)


def test_zip_filename_changes_on_vendor_update(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    vendor = appdir.mkdir('vendor')
    extra_package = vendor.mkdir('mypackage')
    extra_package.join('__init__.py').write('# v1')
    first = chalice_deployer.deployment_package_filename(
        str(appdir), 'python3.6')
    extra_package.join('__init__.py').write('# v2')
    second = chalice_deployer.deployment_package_filename(
        str(appdir), 'python3.6')
    assert first != second


def test_zip_filename_changes_on_vendor_symlink(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    vendor = appdir.mkdir('vendor')
    extra_package = tmpdir.mkdir('mypackage')
    extra_package.join('__init__.py').write('# v1')
    os.symlink(str(extra_package), str(vendor.join('otherpackage')))
    first = chalice_deployer.deployment_package_filename(
        str(appdir), 'python3.6')
    extra_package.join('__init__.py').write('# v2')
    second = chalice_deployer.deployment_package_filename(
        str(appdir), 'python3.6')
    assert first != second


@slow
def test_chalice_runtime_injected_on_change(tmpdir, chalice_deployer):
    appdir = _create_app_structure(tmpdir)
    name = chalice_deployer.create_deployment_package(
        str(appdir), 'python2.7')
    # We're verifying that we always inject the chalice runtime
    # but we can't actually modify the runtime in this repo, so
    # instead we'll modify the deployment package and change the
    # runtime.
    # We'll then verify when we inject the latest app the runtime
    # has been re-added.  This should give us enough confidence
    # that the runtime is always being inserted.
    _remove_runtime_from_deployment_package(name)
    with zipfile.ZipFile(name) as z:
        assert 'chalice/app.py' not in z.namelist()
    chalice_deployer.inject_latest_app(name, str(appdir))
    with zipfile.ZipFile(name) as z:
        assert 'chalice/app.py' in z.namelist()


def test_does_handle_missing_dependency_error(tmpdir):
    appdir = _create_app_structure(tmpdir)
    builder = mock.Mock(spec=DependencyBuilder)
    fake_package = mock.Mock(spec=Package)
    fake_package.identifier = 'foo==1.2'
    builder.build_site_packages.side_effect = MissingDependencyError(
        set([fake_package]))
    ui = mock.Mock(spec=chalice.utils.UI)
    osutils = chalice.utils.OSUtils()
    packager = LambdaDeploymentPackager(
        osutils=osutils,
        dependency_builder=builder,
        ui=ui,
    )
    packager.create_deployment_package(str(appdir), 'python2.7')

    output = ''.join([call[0][0] for call in ui.write.call_args_list])
    assert 'Could not install dependencies:\nfoo==1.2' in output


def _remove_runtime_from_deployment_package(filename):
    new_filename = os.path.join(os.path.dirname(filename), 'new.zip')
    with zipfile.ZipFile(filename, 'r') as original:
        with zipfile.ZipFile(new_filename, 'w',
                             compression=zipfile.ZIP_DEFLATED) as z:
            for item in original.infolist():
                if item.filename.startswith('chalice/'):
                    continue
                contents = original.read(item.filename)
                z.writestr(item, contents)
    os.remove(filename)
    os.rename(new_filename, filename)


def test_can_delete_app(tmpdir):
    # This is just a sanity check that deletions are working
    # as expected now that there's no separate interface
    # for deletion at the deployer layer.
    appdir = _create_app_structure(tmpdir)
    appdir.join('app.py').write(
        'from chalice import Chalice\n'
        'app = Chalice("testapp")'
    )
    deployed_json = {
        'schema_version': '2.0',
        'backend': 'api',
        'resources': [
            {'name': 'role-index',
                'resource_type': 'iam_role',
                'role_name': 'testapp-dev-index',
                'role_arn': 'arn:aws:iam::1:role/testapp-dev-index'},
            {'lambda_arn': 'arn:aws:lambda:r:1:f:testapp-dev-index',
                'name': 'index', 'resource_type': 'lambda_function'},
            {'name': 'role-james', 'resource_type': 'iam_role',
                'role_name': 'testapp-dev-foo',
                'role_arn': 'arn:aws:iam::1:role/testapp-dev-foo'},
            {'lambda_arn': 'arn:aws:lambda:r:1:f:testapp-dev-foo',
                'name': 'james', 'resource_type': 'lambda_function'}
        ]
    }
    deployed_dir = appdir.join('.chalice', 'deployed')
    deployed_dir.mkdir()
    deployed_dir.join('dev.json').write(
        json.dumps(deployed_json))
    mock_client = mock.Mock(spec=TypedAWSClient)
    ui = mock.Mock(spec=chalice.utils.UI)
    d = chalice.deploy.deployer.create_deletion_deployer(mock_client, ui)

    config = Config(
        chalice_stage='dev',
        user_provided_params={
            'chalice_app': Chalice('testapp'),
            'project_dir': str(appdir),
        },
        config_from_disk={},
        default_params={}
    )
    returned_values = d.deploy(config, 'dev')
    assert returned_values == {
        'schema_version': '2.0',
        'backend': 'api',
        'resources': [],
    }
    call = mock.call
    expected_calls = [
        call.delete_function(
            function_name=u'arn:aws:lambda:r:1:f:testapp-dev-foo'),
        call.delete_role(name=u'testapp-dev-foo'),
        call.delete_function(
            function_name=u'arn:aws:lambda:r:1:f:testapp-dev-index'),
        call.delete_role(name=u'testapp-dev-index')
    ]
    assert expected_calls == mock_client.method_calls
