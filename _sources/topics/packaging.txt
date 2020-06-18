App Packaging
=============

In order to deploy your Chalice app, a zip file is created that
contains your application and all third party packages your application
requires.  This file is used by AWS Lambda and is referred
to as a deployment package.

Chalice will automatically create this deployment package for you, and offers
several features to make this easier to manage.  Chalice allows you to
clearly separate application specific modules and packages you are writing
from 3rd party package dependencies.


App Directories
---------------

You have two options to structure application specific code/config:

* **app.py** - This file includes all your route information and is always
  included in the deployment package.
* **chalicelib/** - This directory (if it exists) is included in the
  deployment package.  This is where you can add config files and additional
  application modules if you prefer not to have all your app code in the
  ``app.py`` file.

See :doc:`multifile` for more info on the ``chalicelib/`` directory.  Both the
``app.py`` and the ``chalicelib/`` directory are intended for code that you
write yourself.


3rd Party Packages
------------------

There are two options for handling python package dependencies:

* **requirements.txt** - During the packaging process, Chalice will
  install any packages it finds or can build compatible wheels for.
  Specifically all pure python packages as well as all packages that upload
  wheel files for the ``manylinux1_x86_64`` platform will be automatically
  installable.
* **vendor/** - The *contents* of this directory are automatically added to
  the top level of the deployment package.

Chalice will also check for an optional ``vendor/`` directory in the project
root directory.  The contents of this directory are automatically included in
the top level of the deployment package (see :ref:`package-examples` for
specific examples).  The ``vendor/`` directory is helpful in these scenarios:

* You need to include custom packages or binary content that is not accessible
  via ``pip``.  These may be internal packages that aren't public.
* Wheel files are not available for a package you need from pip.
* A package is installable with ``requirements.txt`` but has optional c
  extensions. Chalice can build the dependency without the c extensions, but
  if you want better performance you can vendor a version that is compiled.

As a general rule of thumb, code that you write goes in either ``app.py`` or
``chalicelib/``, and dependencies are either specified in ``requirements.txt``
or placed in the ``vendor/`` directory.

.. _package-examples:

Examples
--------

Suppose I have the following app structure::

    .
    ├── app.py
    ├── chalicelib
    │   ├── __init__.py
    │   └── utils.py
    ├── requirements.txt
    └── vendor
        └── internalpackage
            └── __init__.py

And the ``requirements.txt`` file had one requirement::

    $ cat requirements.txt
    sortedcontainers==1.5.4

Then the final deployment package directory structure would look like this::

    .
    ├── app.py
    ├── chalicelib
    │   ├── __init__.py
    │   └── utils.py
    ├── internalpackage
    │   └── __init__.py
    └── sortedcontainers
        └── __init__.py


This directory structure is then zipped up and sent to AWS Lambda during the
deployment process.


Cryptography Example
--------------------

  Note

  Since the original version of this example was written, cryptography has
  released version 2.0 which does have manylinux1 wheels available. This
  means if you want to use cryptography in a Chalice app all you need to
  do is add ``cryptography`` or ``cryptography>=2.0`` in your
  requirements.txt file.

  This example will use version 1.9 of Cryptography
  because it is a good example of a library with C extensions and no wheel
  files.

Below shows an example of how to use the
`cryptography 1.9 <https://pypi.org/project/cryptography/1.9/>`__ package
in a Chalice app for the ``python3.6`` lambda environment.

Suppose you are on a Mac or Windows and want to deploy a Chalice app that
depends on the ``cryptography==1.9`` package. If you simply add it to your
``requirements.txt`` file and try to deploy it with ``chalice deploy`` you will
get the following warning during deployment::

  $ cat requirements.txt
  cryptography==1.9
  $ chalice deploy
  Updating IAM policy.
  Updating lambda function...
  Creating deployment package.

  Could not install dependencies:
  cryptography==1.9
  You will have to build these yourself and vendor them in
  the chalice vendor folder.

  Your deployment will continue but may not work correctly
  if missing dependencies are not present. For more information:
  http://chalice.readthedocs.io/en/latest/topics/packaging.html

This happened because the ``cryptography`` version 1.9 does not have wheel
files available on PyPi, and has C extensions. Since we are not on the same
platform as AWS Lambda, the compiled C extensions Chalice built were not
compatible. To get around this we are going to leverage the ``vendor/``
directory, and build the ``cryptography`` package on a compatible linux system.

You can do this yourself by building ``cryptography`` on an Amazon Linux
instance running in EC2. All of the following commands were run inside a
``python 3.6`` virtual environment.

* Download the source first::

    $ pip download cryptography==1.9

  This will download all the requirements into the current working directory.
  The directory should have the following contents:

  * ``asn1crypto-0.22.0-py2.py3-none-any.whl``
  * ``cffi-1.10.0-cp36-cp36m-manylinux1_x86_64.whl``
  * ``cryptography-1.9.tar.gz``
  * ``idna-2.5-py2.py3-none-any.whl``
  * ``pycparser-2.17.tar.gz``
  * ``six-1.10.0-py2.py3-none-any.whl``

  This is a complete set of dependencies required for the cryptography package.
  Most of these packages have wheels that were downloaded, which means they can
  simply be put in the ``requirements.txt`` and Chalice will take care of
  downloading them. That leaves ``cryptography`` itself and ``pycparser`` as
  the only two that did not have a wheel file available for download.

* Next build the ``cryptography`` source package into a wheel file::

    $ pip wheel cryptography-1.9.tar.gz

  This will take a few seconds and build a wheel file for both ``cryptography``
  and ``pycparser``. The directory should now have two additional wheel files:

  * ``cryptography-1.9-cp36-cp36m-linux_x86_64.whl``
  * ``pycparser-2.17-py2.py3-none-any.whl``

  The ``cryptography`` wheel file has been built with a compatible
  architecture for Lambda (``linux_x86_64``) and the ``pycparser`` has been
  built for ``any`` architecture which means it can also be automatically
  packaged by Chalice if it is listed in the ``requirements.txt`` file.

* Download the ``cryptography`` wheel file from the Amazon Linux instance and
  unzip it into the ``vendor/`` directory in the root directory of your Chalice
  app.

  You should now have a project directory that looks like this::

     $ tree
     .
     ├── app.py
     ├── requirements.txt
     └── vendor
         ├── cryptography
         │   ├── ... Lots of files
         │
         └── cryptography-1.9.dist-info
             ├── DESCRIPTION.rst
             ├── METADATA
             ├── RECORD
             ├── WHEEL
             ├── entry_points.txt
             ├── metadata.json
             └── top_level.txt

  The ``requirements.txt`` file should look like this::

    $ cat requirements.txt
    cffi==1.10.0
    six==1.10.0
    asn1crypto==0.22.0
    idna==2.5
    pycparser==2.17

  In your ``app.py`` file you can now import ``cryptography``, and these
  dependencies will all get included when the ``chalice deploy`` command is
  run.
