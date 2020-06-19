
.. image:: ./img/chalice-logo-whitespace.png
   :alt: Chalice Logo

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


Tutorials
---------

.. toctree::
   :maxdepth: 2

   tutorials/index


Topics
------

.. toctree::
   :maxdepth: 2

   topics/index


API Reference
-------------

.. toctree::
   :maxdepth: 2

   api


Upgrade Notes
-------------

.. toctree::
   :maxdepth: 2

   upgrading


Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
