import socket
import six
import os

from typing import Dict, Any  # noqa

from six import StringIO


STRING_TYPES = six.string_types


def pip_import_string():
    # type: () -> str
    import pip
    pip_major_version = int(pip.__version__.split('.')[0])
    pip_minor_version = int(pip.__version__.split('.')[1])
    pip_major_minor = (pip_major_version, pip_minor_version)
    # Pip moved its internals to an _internal module in version 10.
    # In order to be compatible with version 9 which has it at at the
    # top level we need to figure out the correct import path here.
    if (9, 0) <= pip_major_minor < (10, 0):
        return 'from pip import main'
    elif (10, 0) <= pip_major_minor < (19, 3):
        # Pip changed their import structure again in 19.3
        # https://github.com/pypa/pip/commit/09fd200
        return 'from pip._internal import main'
    elif (19, 3) <= pip_major_minor < (20, 0):
        return 'from pip._internal.main import main'
    elif (20, 0) <= pip_major_minor < (21, 0):
        # More changes! https://github.com/pypa/pip/issues/7498
        return 'from pip._internal.cli.main import main'
    raise RuntimeError("Unknown import string for pip version: %s"
                       % str(pip_major_minor))


if os.name == 'nt':
    # windows
    # This is the actual patch used on windows to prevent distutils from
    # compiling C extensions. The msvc compiler base class has its compile
    # method overridden to raise a CompileError. This can be caught by
    # setup.py code which can then fallback to making a pure python
    # package if possible.
    # We need mypy to ignore these since they are never actually called from
    # within our process they do not need to be a part of our typechecking
    # pass.
    def prevent_msvc_compiling_patch():  # type: ignore
        import distutils
        import distutils._msvccompiler
        import distutils.msvc9compiler
        import distutils.msvccompiler

        from distutils.errors import CompileError

        def raise_compile_error(*args, **kwargs):  # type: ignore
            raise CompileError('Chalice blocked C extension compiling.')
        distutils._msvccompiler.MSVCCompiler.compile = raise_compile_error
        distutils.msvc9compiler.MSVCCompiler.compile = raise_compile_error
        distutils.msvccompiler.MSVCCompiler.compile = raise_compile_error

    # This is the setuptools shim used to execute setup.py by pip.
    # Lines 2 and 3 have been added to call the above function
    # `prevent_msvc_compiling_patch` and extra escapes have been added on line
    # 5 because it is passed through another layer of string parsing before it
    # is executed.
    _SETUPTOOLS_SHIM = (
        r"import setuptools, tokenize;__file__=%r;"
        r"from chalice.compat import prevent_msvc_compiling_patch;"
        r"prevent_msvc_compiling_patch();"
        r"f=getattr(tokenize, 'open', open)(__file__);"
        r"code=f.read().replace('\\r\\n', '\\n');"
        r"f.close();"
        r"exec(compile(code, __file__, 'exec'))"
    )

    # On windows the C compiling story is much more complex than on posix as
    # there are many different C compilers that setuptools and disutils will
    # try and find using a combination of known filepaths, registry entries,
    # and environment variables. Since there is no simple environment variable
    # we can replace when starting the subprocess that builds the package;
    # we need to apply a patch at runtime to prevent pip/setuptools/distutils
    # from being able to build C extensions.
    # Patching out every possible technique for finding each compiler would
    # be a losing game of whack-a-mole. In addition we need to apply a patch
    # two layers down through subprocess calls, specifically:
    #  * Chalice creates a subprocess of `pip wheel ...` to build sdists
    #    into wheel files.
    #  * Pip creates another python subprocess to call the setup.py file in
    #    the sdist. Before doing so it applies the above shim to make the
    #    setup file compatible with setuptools. This shim layer also reads
    #    and executes the code in the setup.py.
    #  * Setuptools (which will have been executed by the shim) will
    #    eventually call distutils to do the heavy lifting for C compiling.
    #
    # Our patch needs to affect the bottom level here (distutils) and patch
    # it out to prevent it from compiling C in a graceful way that results in
    # falling back to building a purepython library if possible.
    # The below line will be injected just before the `pip wheel ...` portion
    # of the subprocess that Chalice starts. This replaces the
    # SETUPTOOLS_SHIM that pip normally uses with the one defined above.
    # When pip goes to run its subprocess for executing setup.py it will
    # inject _SETUPTOOLS_SHIM rather than the usual SETUPTOOLS_SHIM in pip.
    # This lets us apply our patches in the same process that will compile
    # the c extensions before the setup.py file has been executed.
    # The actual patches used are decribed in the comment above
    # _SETUPTOOLS_SHIM.
    pip_no_compile_c_shim = (
        'import pip;'
        'pip.wheel.SETUPTOOLS_SHIM = """%s""";'
    ) % _SETUPTOOLS_SHIM
    pip_no_compile_c_env_vars = {}  # type: Dict[str, Any]
else:
    # posix
    # On posix systems setuptools/distutils uses the CC env variable to
    # locate a C compiler for building C extensions. All we need to do is set
    # it to /var/false, and the module building process will fail to build.
    # C extensions, and any fallback processes in place to build a pure python
    # package will be kicked off.
    # No need to monkey patch the process.
    pip_no_compile_c_shim = ''
    pip_no_compile_c_env_vars = {
        'CC': '/var/false'
    }


if six.PY3:
    from urllib.parse import urlparse, parse_qs

    def is_broken_pipe_error(error):
        # type: (Exception) -> bool
        return isinstance(error, BrokenPipeError)  # noqa
else:
    from urlparse import urlparse, parse_qs

    def is_broken_pipe_error(error):
        # type: (Exception) -> bool

        # In python3, this is a BrokenPipeError. However in python2, this
        # is a socket.error that has the message 'Broken pipe' in it. So we
        # don't want to be assuming all socket.error are broken pipes so just
        # check if the message has 'Broken pipe' in it.
        return isinstance(error, socket.error) and 'Broken pipe' in str(error)
