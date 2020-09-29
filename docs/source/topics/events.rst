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


.. _cwe-events:

CloudWatch Events
==================

You can configure a lambda function to subscribe to
any `CloudWatch Event <https://amzn.to/2SCgWA6>`__.

To subscribe to a CloudWatch Event in chalice, you use the
``@app.on_cw_event()`` decorator.  Let's look at an example.


.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.on_cw_event({"source": ["aws.codecommit"]})
    def on_code_commit_changes(event):
        print(event.to_dict())

In this example, we have a single lambda function that we subscribe to all
events from the AWS Code Commit service. The first parameter to the decorator
is the event pattern that will be used to filter the events sent to the function.

See the `CloudWatch Event pattern docs <https://amzn.to/2OlqZso>`__
for additional syntax and examples.

The function you decorate must accept a single argument,
which will be of type :class:`CloudWatchEvent`.

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

    app = Chalice(app_name='chalice-sns-demo')
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

And now we can test our app by publishing a few SNS messages to our topic.
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

In this example we used the SNS topic name to register our handler, but you can
also use the topic arn. This can be useful if your topic is in another region
or account.


.. _sqs-events:

SQS Events
==========

You can configure a lambda function to be invoked whenever messages are
available on an SQS queue.  To configure this, use the
:meth:`Chalice.on_sqs_message` decorator and provide the name of the SQS queue
and an optional batch size.

The message visibility timeout of your SQS queue must be greater than or
equal to the lambda timeout.  The default message visibility timeout
when you create an SQS queue is 30 seconds, and the default timeout
for a Lambda function is 60 seconds, so you'll need to modify one of these
values in order to successfully connect an SQS queue to a Lambda function.

You can check the visibility timeout of your queue using the
``GetQueueAttributes`` API call.  Using the
`AWS CLI <https://docs.aws.amazon.com/cli/latest/reference/sqs/get-queue-attributes.html>`__,
you can run this command to check the value::

  $ aws sqs get-queue-attributes \
      --queue-url https://us-west-2.queue.amazonaws.com/1/testq \
      --attribute-names VisibilityTimeout
  {
      "Attributes": {
          "VisibilityTimeout": "30"
      }
  }

You can set the visibility timeout of your SQS queue using the
``SetQueueAttributes`` API call.  Again using the AWS CLI you can
run this command::

  $ aws sqs set-queue-attributes \
      --queue-url https://us-west-2.queue.amazonaws.com/1/testq \
      --attributes VisibilityTimeout=60

If you would prefer to change the timeout of your lambda function instead,
you can specify this timeout value using the ``lambda_timeout`` config key
if your ``.chalice/config.json`` file.
See :ref:`lambda-config` for a list of all supported lambda configuration
values in chalice.  In this example below, we're setting the timeout
of our ``handle_sqs_message`` lambda function to 30 seconds::

  $ cat .chalice/config.json
  {
    "stages": {
      "dev": {
        "lambda_functions": {
          "handle_sqs_message": {
            "lambda_timeout": 30
          }
        }
      }
    },
    "version": "2.0",
    "app_name": "chalice-sqs-demo"
  }


In this example below, we're connecting the ``handle_sqs_message`` lambda
function to the ``my-queue`` SQS queue.  Note that we are specifying the
queue name, not the queue URL or queue ARN.  If you are connecting your
lambda function to a FIFO queue, make sure you specify the ``.fifo``
suffix, e.g. ``my-queue.fifo``.

.. code-block:: python

    from chalice import Chalice

    app = chalice.Chalice(app_name='chalice-sqs-demo')
    app.debug = True

    @app.on_sqs_message(queue='my-queue', batch_size=1)
    def handle_sqs_message(event):
        for record in event:
            app.log.debug("Received message with contents: %s", record.body)


Whenever a message is sent to the SQS queue our function will be automatically
invoked.  The function argument is an :class:`SQSEvent` object, and each
``record`` in the example above is of type :class:`SQSRecord`.  Lambda takes
care of automatically scaling your function as needed.  See `Understanding
Scaling Behavior`_ for more information on how Lambda scaling works.

If your lambda functions completes without raising an exception, then
Lambda will automatically delete all the messages associated with the
:class:`SQSEvent`.  You don't need to manually call ``sqs.delete_message()``
in your lambda function.  If your lambda function raises an exception, then
Lambda won't delete any messages, and once the visibility timeout has been
reached, the messages will be available again in the SQS queue.  Note that
if you are using a batch size of more than one, the entire batch succeeds or
fails.  This means that it is possible for your lambda function to see
a message multiple times, even if it's successfully processed the message
previously.  There are a few options available to mitigate this:

* Use a batch size of 1 (the default value).
* Use a separate data store to check if you've already processed an SQS
  message.  You can use services such as Amazon DynamoDB or Amazon ElastiCache.
* Manually call ``sqs.delete_message()`` in your Lambda function once you've
  successfully processed a message.

For more information on Lambda and SQS,
see the `AWS documentation`_.

.. _kinesis-events:

Kinesis Events
==============

You can configure a Lambda function to be invoked whenever messages are
published to an Amazon Kinesis data stream.  To configure this, use the
:meth:`Chalice.on_kinesis_message` decorator and provide the name of the
Kinesis stream.

The :class:`KinesisEvent` that is passed in as the ``event`` argument
to the event handler is also iterable.  This allows you to iterate over
all the records in the event.  Additionally, each record has a ``.data``
attribute that is automatically base64 decoded for you.

Here's an example:

.. code-block:: python

    from chalice import Chalice

    app = chalice.Chalice(app_name='kinesiseventdemo')
    app.debug = True

    @app.on_kinesis_message(stream='mystream')
    def handle_kinesis_message(event):
        for record in event:
            # The .data attribute is automatically base64 decoded for you.
            app.log.debug("Received message with contents: %s", record.data)

For more information on using Kinesis and Lambda, see
`Using AWS Lambda with Amazon Kinesis <https://docs.aws.amazon.com/lambda/latest/dg/with-kinesis.html>`__.

.. _dynamodb-events:

DynamoDB Events
===============

You can configure a Lambda function to be invoked whenever messages are
published to an Amazon DynamoDB stream.  To configure this, use the
:meth:`Chalice.on_dynamodb_message` decorator and provide the name of the
DynamoDB stream ARN.

.. note::
   Other event handlers such as :meth:`Chalice.on_kinesis_message`,
   :meth:`Chalice.on_sqs_message`, and :meth:`Chalice.on_sns_message`
   only require the resource name and not the full ARN.  In the case
   of DynamoDB streams, there are auto-generated portions of the
   stream ARN that cannot be computed based on the resource name.  This
   is why Chalice requires that full stream ARN when configuring
   a DynamoDB stream handler.

The :class:`DynamoDBEvent` that is passed in as the ``event`` argument
to the event handler is also iterable.  This allows you to iterate over
all the records in the event.

Here's an example:

.. code-block:: python

    from chalice import Chalice

    app = chalice.Chalice(app_name='ddb-event-demo')
    app.debug = True

    @app.on_kinesis_message(stream_arn='arn:aws:dynamodb:.../stream/2020')
    def handle_ddb_message(event):
        for record in event:
            app.log.debug("New: %s", record.new_image)


For more information on using Lambda and DynamoDB, see
`Using AWS Lambda with Amazon DynamoDB <https://docs.aws.amazon.com/lambda/latest/dg/with-ddb.html>`__.


.. _event notifications: https://docs.aws.amazon.com/AmazonS3/latest/dev/NotificationHowTo.html
.. _AWS documentation: https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html
.. _Understanding Scaling Behavior: https://docs.aws.amazon.com/lambda/latest/dg/scaling.html
