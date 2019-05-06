============
Contributing
============

We work hard to provide a high-quality and useful framework, and we greatly value
feedback and contributions from our community. Whether it's a new feature,
correction, or additional documentation, we welcome your pull requests. Please
submit any `issues <https://github.com/aws/chalice/issues>`__
or `pull requests <https://github.com/aws/chalice/pulls>`__ through GitHub.

This document contains guidelines for contributing code and filing issues.

Contributing Code
=================

This list below are guidelines to use when submitting pull requests.
These are the same set of guidelines that the core contributors use
when submitting changes, and we ask the same of all community
contributions as well:

* Chalice is released under the
  `Apache license <http://aws.amazon.com/apache2.0/>`__.
  Any code you submit will be released under that license.
* We maintain a high percentage of code coverage in our tests.  As
  a general rule of thumb, code changes should not lower the overall
  code coverage percentage for the project.  To help with this,
  we use `codecov <https://codecov.io/gh/aws/chalice>`__, which will
  comment on changes in code coverage for every pull request.
  In practice, this means that every bug fix and feature addition should
  include unit tests, and optionally functional and integration tests.
* All PRs must run cleanly through ``make prcheck``.  This is described
  in more detail in the sections below.
* All new features must include documentation before it can be merged.


Feature Development
===================

Any significant feature development for chalice should have a
corresponding github issue for discussion.  This gives several benefits:

* Helps avoid wasted work by discussing the proposed API changes before
  significant dev work is started.
* Gives a single place to capture discussion about the rationale for
  a feature.

This applies to:

* Any feature that proposes modifying the public API for chalice
* Additions to the chalice config file
* Any new CLI commands

If you'd like to implement a significant feature for chalice,
please file an `issue <https://github.com/aws/chalice/issues>`__
to start the design discussion.

All of the existing proposals are tagged with `proposals
<https://github.com/aws/chalice/issues?q=is%3Aopen+is%3Aissue+label%3Aproposals>`__.


Development Environment Setup
=============================

First, create a virtual environment for chalice::

    $ virtualenv venv
    $ source venv/bin/activate

Keep in mind that chalice is designed to work with AWS Lambda,
so you should ensure your virtual environment is created with
python2.7, python3.6, or python3.7, which are the versions of python currently supported by
AWS Lambda.

Next, you'll need to install chalice.  The easiest way to configure this
is to  use::

    $ pip install -e ".[event-file-poller]"


Run this command the root directory of the chalice repo.

Next, you have a few options.  There are various requirements files
depending on what you'd like to do.

For example, if you'd like to work on chalice, either fixing bugs or
adding new features, install ``requirements-dev.txt``::


    $ pip install -r requirements-dev.txt


If you'd like to just build the docs, install ``requirements-docs.txt``::

    $ pip install -r requirements-docs.txt


Running Tests
-------------

Chalice uses `pytest <https://docs.pytest.org/en/latest/>`__ to run tests.
The tests are categorized into 3 categories:

* ``unit`` - Fast tests that don't make any IO calls (including file system
  access).  Object dependencies are usually mocked out.
* ``functional`` - These tests will test multiple components together,
  typically through an interface that's close to what an end user would
  be using.  For example, there are CLI functional tests that will invoke the
  same functions that would correspond to a ``chalice deploy`` command.
  In the functional tests, AWS calls are stubbed, but they'll go through the
  `botocore stubber
  <http://botocore.readthedocs.io/en/latest/reference/stubber.html>`__.
* ``integration`` - These tests require an AWS accounts and will actually
  create real AWS resources.  The integration tests in chalice usually
  involving deploying a sample app and making assertions about the deployed
  app by making HTTP/AWS requests to external endpoints.

During development, you'll generally run the unit tests, and less
frequently you'll run the functional tests (the functional tests take
an order of magnitude longer than the unit tests).  To run the unit tests,
you can run::

    $ py.test tests/unit/

To run the functional tests you can run::

    $ py.test tests/functional/

There's also a ``Makefile`` in the repo and you can run
``make test`` to run both the unit and functional tests.

Code Analysis
-------------

Chalice uses several python linters to help ensure high
code quality.  This also helps to cut down on the noise
for pull request reviews because many issues are caught
locally during development.

To run all the linters, you can run ``make check``.
This will run:

* `flake8 <http://flake8.pycqa.org/en/latest/>`__, a tool
  for checking pep8 as well as common lint checks
* `doc8 <https://pypi.python.org/pypi/doc8>`__, a style
  checker for sphinx docs
* `pydocstyle <https://github.com/PyCQA/pydocstyle>`__, a
  docstring checker
* `pylint <https://www.pylint.org/>`__, a much more
  exhaustive linter that can catch additional issues
  compared to ``flake8``.

Type Checking
-------------

Chalice leverages the type hints introduced in python 3.5
from `pep 484 <https://www.python.org/dev/peps/pep-0484/>`__
and `pep 526 <https://www.python.org/dev/peps/pep-0526/>`__.
`mypy <http://mypy-lang.org/>`__ is used to check types.
All chalice code must have type hints added or else the
CI build will fail.  To check types you can run ``make typecheck``.

Chalice supports python2 as well as python3.  Because of
the requirement of supporting python2, function annotations
are not allowed for specifying type hints, you must use
type comments as outlined in pep 484.

Keep in mind that ``mypy`` only runs in python3, so you'll need
to either use python3 when developing features or have mypy
globally installed.

PRCheck
-------

Before submitting a PR, ensure that ``make prcheck`` runs
without any errors.  This command will run the linters,
the typecheckers and the unit and functional tests.
``make prcheck`` is also run as part of the travis CI build.
Pull requests must pass ``make prcheck`` before they can be merged.
