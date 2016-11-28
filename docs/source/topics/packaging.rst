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
