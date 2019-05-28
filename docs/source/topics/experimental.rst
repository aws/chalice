Experimental APIs
=================

Chalice maintains backwards compatibility for all features that appear in this
documentation.  Any Chalice application using version 1.x will continue to work
for all future versions of 1.x.

We also believe that Chalice has a lot of potential for new ideas and APIs,
many of which will take several iterations to get right.  We may implement a
new idea and need to make changes based on customer usage and feedback.  This
may include backwards incompatible changes all the way up to the removal of
a feature.

To accommodate these new features, Chalice has support for experimental APIs,
which are features that are added to Chalice on a provisional basis.  Because
these features may include backwards incompatible changes, you must explicitly
opt-in to using these features.  This makes it clear that you are using an
experimental feature that may change.

Opting-in to Experimental APIs
------------------------------

Each experimental feature in chalice has a name associated with it.  To opt-in
to an experimental API, you must have the feature name to the
``experimental_feature_flags`` attribute on your ``app`` object.
This attribute's type is a set of strings.

.. code-block:: python

    from chalice import Chalice

    app = Chalice('myapp')
    app.experimental_feature_flags.update([
        'MYFEATURE1',
        'MYFEATURE2',
    ])


If you use an experimental API without opting-in, you will receive
a message whenever you run a Chalice CLI command.  The error message
tells you which feature flags you need to add::

    $ chalice deploy
    You are using experimental features without explicitly opting in.
    Experimental features do not guarantee backwards compatibility and may be removed in the future.
    If you still like to use these experimental features, you can opt-in by adding this to your app.py file:

    app.experimental_feature_flags.update([
        'BLUEPRINTS'
    ])


    See https://chalice.readthedocs.io/en/latest/topics/experimental.rst for more details.

The feature flag only happens when running CLI commands.  There are no runtime
checks for experimental features once your application is deployed.


List of Experimental APIs
-------------------------

In the table below, the "Feature Flag Name" column is the value you
must add to the ``app.experimental_feature_flags`` attribute.
The status of an experimental API can be:

* ``Trial`` - You must explicitly opt-in to use this feature.
* ``Accepted`` - This feature has graduated from an experimental
  feature to a fully supported, backwards compatible feature in Chalice.
  Accepted features still appear in the table for auditing purposes.
* ``Rejected`` - This feature has been removed.


.. list-table:: Experimental APIs
  :header-rows: 1

  * - Feature
    - Feature Flag Name
    - Version Added
    - Status
    - GitHub Issue(s)
  * - :doc:`blueprints`
    - ``BLUEPRINTS``
    - 1.7.0
    - Trial
    - `#1023 <https://github.com/aws/chalice/pull/1023>`__,
      `#651 <https://github.com/aws/chalice/pull/651>`__
  * - :doc:`websockets`
    - ``WEBSOCKETS``
    - 1.9.0
    - Trial
    - `#1041 <https://github.com/aws/chalice/pull/1041>`__,
      `#1017 <https://github.com/aws/chalice/issues/1017>`__


See the `original discussion <https://github.com/aws/chalice/issues/1019>`__
for more background information and alternative proposals.
