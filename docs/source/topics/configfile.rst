Configuration File
==================

Whenever you create a new project using
``chalice new-project``, a ``.chalice`` directory is created
for you.  In this directory is a ``config.json`` file that
you can use to control what happens when you ``chalice deploy``::


    $ tree -a
    .
    ├── .chalice
    │   └── config.json
    ├── app.py
    └── requirements.txt

    1 directory, 3 files

Below are the values you can specify in this file:

* ``manage_iam_role`` - ``true``/``false``.  Indicates if you
  want ``chalice deploy`` to create and update the IAM role
  used for your application.  By default, this value is ``true``.
  However, if you have a preexisting role you've created, you
  can set this value to ``false`` and a role will not be created
  or updated.  Note that if this value is ``false``, no policy
  for this role will be created or managed by this framework.
  ``"manage_iam_role": false`` means that you are responsible for
  managing the role and any associated policies associated with
  that role.  If this value is ``false`` you must specify
  an ``iam_role_arn``, otherwise an error is raised when you
  try to run ``chalice deploy``.

* ``iam_role_arn`` - If ``manage_iam_role`` is ``false``, you
  must specify this value that indicates which IAM role arn to
  use when configuration your application.  This value is only
  used if ``manage_iam_role`` is ``false``.

* ``environment_variables`` - ``{'KEY': 'value'}``.
  You can add any key value pairs to this dictionary that you
  would like. All key value pairs will be set directly as
  environment variables on your lambda function.
