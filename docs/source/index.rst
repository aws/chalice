========================================
Python Serverless Microframework for AWS
========================================

The python serverless microframework for AWS allows you to quickly create and
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
    Your application is available at: https://endpoint/dev

    $ curl https://endpoint/dev
    {"hello": "world"}

Up and running in less than 30 seconds.

**This project is published as a preview project and is not yet recommended for
production APIs.**  Give this project a try and share your feedback with us
on `github <https://github.com/awslabs/chalice>`__.


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
   topics/packaging


API Reference
-------------

.. toctree::
   :maxdepth: 2

   api




Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
