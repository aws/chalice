====================
Lambda Event Sources
====================


.. _scheduled-events:

Scheduled Events
================

Chalice has support for `scheduled events`_.  This feature allows you to
periodically invoke a lambda function based on some regular schedule.  You can
specify a fixed rate or a cron expression.

To create a scheduled event in chalice, you use the ``@app.schedule()``
decorator.  Let's look at an example.


.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.schedule('rate(1 hour)')
    def every_hour(event):
        print(event.to_dict())


In this example, we have a single lambda function that we want automatically
invoked every hour.  When you run ``chalice deploy`` Chalice will create a
lambda function as well as the necessary CloudWatch events/rules such that the
``every_hour`` function is invoked every hour.

The :meth:`Chalice.schedule` method accepts either a string or an
instance of :class:`Rate` or :class:`Cron`.  For example:

.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.schedule(Rate(1, unit=Rate.HOURS))
    def every_hour(event):
        print(event.to_dict())


The function you decorate must accept a single argument,
which will be of type :class:`CloudWatchEvent`.

You can use the ``schedule()`` decorator multiple times
in your chalice app.  Each ``schedule()`` decorator will
result in a new lambda function and associated CloudWatch
event rule.  For example:


.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.schedule(Rate(1, unit=Rate.HOURS))
    def every_hour(event):
        print(event.to_dict())


    @app.schedule(Rate(2, unit=Rate.HOURS))
    def every_two_hours(event):
        print(event.to_dict())


In the app above, chalice will create two lambda functions,
and configure ``every_hour`` to be invoked once an hour,
and ``every_two_hours`` to be invoked once every two hours.


.. _s3-events:

S3 Events
=========

You can configure a lambda function to be invoked whenever
certain events happen in an S3 bucket.  This uses the
`event notifications`_ feature provided by Amazon S3.

To configure this, you just tell Chalice the name of an existing
S3 bucket, along with what events should trigger the lambda function.
This is done with the :meth:`Chalice.on_s3_event` decorator.

Here's an example:

.. code-block:: python

    from chalice import Chalice

    app = chalice.Chalice(app_name='s3eventdemo')
    app.debug = True

    @app.on_s3_event(bucket='mybucket-name',
                     events=['s3:ObjectCreated:*'])
    def handle_s3_event(event):
        app.log.debug("Received event for bucket: %s, key: %s",
                      event.bucket, event.key)

In this example above, Chalice connects the S3 bucket to the
``handle_s3_event`` Lambda function such that whenver an object is uploaded
to the ``mybucket-name`` bucket, the Lambda function will be invoked.
This example also uses the ``.bucket`` and ``.key`` attribute from the
``event`` parameter, which is of type :class:`S3Event`.

It will automatically create the appropriate S3 notification configuration
as needed.  Chalice will also leave any existing notification configuration
on the ``mybucket-name`` untouched.  It will only merge in the additional
configuration needed for the ``handle_s3_event`` Lambda function.


.. warning::

  This feature only works when using `chalice deploy`.  Because you
  configure the lambda function with the name of an existing S3 bucket,
  it is not possible to describe this using a CloudFormation/SAM template.
  The ``chalice package`` command will fail.  You will eventually be able
  to request that chalice create a bucket for you, which will support
  the ``chalice package`` command.

The function you decorate must accept a single argument,
which will be of type :class:`S3Event`.

.. _sns-events:

SNS Events
==========

You can configure a lambda function to be automatically invoked whenever
something publishes to an SNS topic.  Chalice will automatically handle
creating the lambda function, subscribing the lambda function to the
SNS topic, and modifying the lambda function policy to allow SNS to invoke
the function.

To configure this, you just need the name of an existing SNS topic you'd
like to subscribe to.  The SNS topic must already exist.

Below is an example of how to set this up.  The example uses boto3 to
create the SNS topic.  If you don't have boto3 installed in your virtual
environment, be sure to install it with::

    $ pip install boto3

First, we'll create an SNS topic using boto3.

::

    $ python
    >>> import boto3
    >>> sns = boto3.client('sns')
    >>> sns.create_topic(Name='my-demo-topic')
    {'TopicArn': 'arn:aws:sns:us-west-2:12345:my-demo-topic',
     'ResponseMetadata': {}}

Next, we'll create our chalice app::

    $ chalice new-project chalice-demo-sns
    $ cd chalice-demo-sns/

We'll update the ``app.py`` file to use the ``on_sns_message`` decorator:

.. code-block:: python

    from chalice import Chalice

    app = chalice.Chalice(app_name='chalice-sns-demo')
    app.debug = True

    @app.on_sns_message(topic='my-demo-topic')
    def handle_sns_message(event):
        app.log.debug("Received message with subject: %s, message: %s",
                      event.subject, event.message)

We can now deploy our chalice app::

    $ chalice deploy
    Creating deployment package.
    Creating IAM role: chalice-demo-sns-dev
    Creating lambda function: chalice-demo-sns-dev-handle_sns_message
    Subscribing chalice-demo-sns-dev-handle_sns_message to SNS topic my-demo-topic
    Resources deployed:
      - Lambda ARN: arn:aws:lambda:us-west-2:123:function:...

And now we can test our app by publishing a few SNS message to our topic.
We'll do this using boto3.  In the example below, we're using ``list_topics()``
to find the ARN associated with our topic name before calling the ``publish()``
method.

::

    $ python
    >>> import boto3
    >>> sns = boto3.client('sns')
    >>> topic_arn = [t['TopicArn'] for t in sns.list_topics()['Topics']
    ...              if t['TopicArn'].endswith(':my-demo-topic')][0]
    >>> sns.publish(Message='TestMessage1', Subject='TestSubject1',
    ...             TopicArn=topic_arn)
    {'MessageId': '12345', 'ResponseMetadata': {}}
    >>> sns.publish(Message='TestMessage2', Subject='TestSubject2',
    ...             TopicArn=topic_arn)
    {'MessageId': '54321', 'ResponseMetadata': {}}

To verify our function was called correctly, we can use the ``chalice logs``
command::

    $ chalice logs -n handle_sns_message
    2018-06-28 17:49:30.513000 547e0f chalice-demo-sns - DEBUG - Received message with subject: TestSubject1, message: TestMessage1
    2018-06-28 17:49:40.391000 547e0f chalice-demo-sns - DEBUG - Received message with subject: TestSubject2, message: TestMessage2


.. _event notifications: https://docs.aws.amazon.com/AmazonS3/latest/dev/NotificationHowTo.html
