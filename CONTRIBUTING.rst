============
Contributing
============



Development Environment Setup
=============================

First, create a virtual environment for chalice::

    $ virtualenv venv-chalice
    $ source venv-chalice/bin/activate

Keep in mind that chalice is designed to work with AWS Lambda,
so you should ensure your virtual environment is created with
python 2.7, which is the version of python currently supported by
AWS Lambda.

Next, you'll need to install chalice.  The easiest way to configure this
is to  use::

    $ pip install -e .

Run this command the root directory of the chalice repo.

Next, you have a few options.  There are various requirements files
depending on what you'd like to do.

For example, if you'd like to work on chalice, either fixing bugs or
adding new features, install ``requirements-dev.txt``::


    $ pip install -r requirements-dev.txt


If you'd like to just build the docs, install ``requirements-docs.txt``::

    $ pip install -r requirements-docs.txt

And finally, if you only want to run the tests, you can run::

    $ pip install -r requirements-test.txt

Note that ``requirements-dev.txt`` automatically includes
``requirements-test.txt`` so if you're interested in chalice development you
only need to install ``requirements-dev.txt``.
