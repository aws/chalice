App Packaging
=============

In order to deploy your chalice app, a zip file is created that
contains your application and all third party packages your application
rqeuires.  This file is used by AWS Lambda and is referred
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

* **requirements.txt** - During the packaging process, chalice will
  run ``pip install -r requirements.txt`` in a virtual environment
  and automatically install 3rd party python packages into the deployment
  package.
* **vendor/** - The *contents* of this directory are automatically added to
  the top level of the deployment package.

Chalice will also check for an optional ``vendor/`` directory in the project
root directory.  The contents of this directory are automatically included in
the top level of the deployment package (see :ref:`package-examples` for
specific examples).  The ``vendor/`` directory is helpful in these scenarios:

* You need to include custom packages or binary content that is not accessible
  via ``pip``.  These may be internal packages that aren't public.
* You need to use C extensions, and you're not developing on Linux.


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


Psycopg2 Example
----------------

Below shows an example of how you can use the
`psycopg2 <https://pypi.python.org/pypi/psycopg2>`__ package in a chalice app.

We're going to leverage the ``vendor/`` directory in order to use this
package in our app.  We can't use ``requirements.txt`` file because
``psycopg2`` has additional requirements:

* It contains C extensions and if you're not developing on Amazon Linux,
  the binaries built on a dev machine will not match what's needed on AWS
  Lambda.
* AWS Lambda does not have the ``libpq.so`` library available, so we need
  to build a custom version of ``psycopg2`` that has ``libpq.so`` statically
  linked.

You can do this yourself by building `psycopg2 <https://pypi.python.org/pypi/psycopg2>`__
on Amazon Linux with the ``static_libpq=1`` value set in the ``setup.cfg``
file.  You can then copy/unzip the ``.whl`` file into the ``vendor/``
directory.

There are also existing packages that have prebuilt this, including the
3rd party `awslambda-psycopg2 <https://github.com/jkehler/awslambda-psycopg2>`__
package.  If you wanted to use this 3rd party package you can follow these
steps::

$ mkdir vendor
$ git clone git@github.com:jkehler/awslambda-psycopg2.git
$ cp -r awslambda-psycopg2/psycopg2 vendor/
$ rm -rf awslambda-psycopg2/


You should now have a directory that looks like this::

    $ tree
    .
    ├── app.py
    ├── app.pyc
    ├── requirements.txt
    └── vendor
        └── psycopg2
            ├── __init__.py
            ├── _json.py
            ├── _psycopg.so
            ....


In your ``app.py`` file you can now import ``psycopg2``, and this
dependency will automatically be included when the ``chalice deploy``
command is run.
