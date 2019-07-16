===========
AWS Chalice
===========

AWS Chalice allows you to quickly create and
deploy applications that use Amazon API Gateway and AWS Lambda.
It provides:

* A command line tool for creating, deploying, and managing your app
* A familiar and easy to use API for declaring views in python code
* Automatic IAM policy generation


::

    $ pip install chalice
    $ chalice new-project helloworld && cd helloworld
    $ cat app.py

    from chalice import Chalice

    app = Chalice(app_name="helloworld")

    @app.route("/")
    def index():
        return {"hello": "world"}

    $ chalice deploy
    ...
    https://endpoint/dev

    $ curl https://endpoint/api
    {"hello": "world"}

Up and running in less than 30 seconds.


Getting Started
---------------

.. toctree::
   :maxdepth: 2

   quickstart


Topics
------

.. toctree::
   :maxdepth: 2

   topics/routing
   topics/views
   topics/configfile
   topics/multifile
   topics/logging
   topics/sdks
   topics/stages
   topics/packaging
   topics/pyversion
   topics/cfn
   topics/authorizers
   topics/events
   topics/purelambda
   topics/blueprints
   topics/websockets
   topics/cd
   topics/experimental


API Reference
-------------

.. toctree::
   :maxdepth: 2

   api


Tutorials
---------

.. toctree::
   :maxdepth: 2

   tutorials/websockets

Upgrade Notes
-------------

.. toctree::
   :maxdepth: 2

   upgrading


Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
