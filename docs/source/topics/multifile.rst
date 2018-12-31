Multifile Support
=================

The ``app.py`` file contains all of your view functions and route
information, but you don't have to keep all of your application
code in your ``app.py`` file.

As your application grows, you may reach out a point where you'd
prefer to structure your application in multiple files.
You can create a ``chalicelib/`` directory, and anything
in that directory is recursively included in the deployment
package.  This means that you can have files besides just
``.py`` files in ``chalicelib/``, including ``.yml`` files
for config, or any kind of binary assets.

Let's take a look at a few examples.

Consider the following app directory structure layout::

    .
    ├── app.py
    ├── chalicelib
    │   └── __init__.py
    └── requirements.txt

Where ``chalicelib/__init__.py`` contains:

.. code-block:: python

    MESSAGE = 'world'


and the ``app.py`` file contains:

.. code-block:: python
    :linenos:
    :emphasize-lines: 2

    from chalice import Chalice
    from chalicelib import MESSAGE

    app = Chalice(app_name="multifile")

    @app.route("/")
    def index():
        return {"hello": MESSAGE}


Note in line 2 we're importing the ``MESSAGE`` variable from
the ``chalicelib`` package, which is a top level directory
in our project.  We've created a ``chalicelib/__init__.py``
file which turns the ``chalicelib`` directory into a python
package.

We can also use this directory to store config data.   Consider
this app structure layout::


    .
    ├── app.py
    ├── chalicelib
    │   └── config.yml
    └── requirements.txt


With ``chalicelib/config.yml`` containing::

    ---
    message: world

In our ``app.py`` code, we can load and use our config file:

.. code-block:: python
    :linenos:

    import os
    import json
    import yaml

    from chalice import Chalice

    app = Chalice(app_name="multifile")

    filename = os.path.join(
        os.path.dirname(__file__), 'chalicelib', 'config.yml')
    with open(filename) as f:
        config = yaml.load(f)

    @app.route("/")
    def index():
        # We can access ``config`` here if we want.
        return {"hello": config['message']}
