Event Sources Tutorial
======================

In the :doc:`../quickstart` guide, we looked at how to create a
REST API using the ``@app.route()`` decorator.  Chalice also has
additional decorators that connects your code to specific event sources.
This results in your code being invoked when a specific event occurs.

In this tutorial we'll look at a few examples.

Installation and Configuration
------------------------------

If you haven't already setup and configured Chalice, see the
:doc:`../quickstart` for a step by step guide.  In a nutshell, you can get a
basic Chalice app created with::

    $ python3 --version
    Python 3.9.22
    $ python3 -m venv venv39
    $ . venv39/bin/activate
    $ python3 -m pip install chalice
    $ chalice new-project chalice-sns-demo
    $ cd chalice-sns-demo


We'll also be using the AWS CLI in this tutorial.  You can follow
`these instructions <https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html>`__
for installing the AWS CLI v2.


Amazon SNS Topics
-----------------

In this first example, we'll create a Chalice application that will
call our Lambda function whenever a message is published to an
`SNS Topic <https://aws.amazon.com/sns/>`__.

First, we'll create an SNS topic.  This is what we'll connect to our
Lambda function::

    $ aws sns create-topic --name MyDemoTopic
    {
        "TopicArn": "arn:aws:sns:us-west-2:12345:MyDemoTopic"
    }

Be sure to save the ``TopicArn`` value for later.  In this example
that would be ``arn:aws:sns:us-west-2:12345:MyDemoTopic``.

Next, we'll update the ``app.py`` to create a lambda function that
connects to an SNS topic:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='chalice-sns-demo', debug=True)

    @app.on_sns_message(topic='MyDemoTopic')
    def handle_sns_message(event):
        app.log.debug("Received message with subject: %s, message: %s",
                      event.subject, event.message)

In the code above, we're using the ``@app.on_sns_message()`` decorator to
connect the SNS topic named ``MyDemoTopic`` with the ``handle_sns_message``
function.  Note that we're using the name of the topic and not the
``TopicArn``.

Now we can deploy our chalice app::

    $ chalice deploy
    Creating deployment package.
    Creating IAM role: chalice-demo-sns-dev
    Creating lambda function: chalice-demo-sns-dev-handle_sns_message
    Subscribing chalice-demo-sns-dev-handle_sns_message to SNS topic my-demo-topic
    Resources deployed:
      - Lambda ARN: arn:aws:lambda:us-west-2:123:function:...

Now we can test our app by publishing a few SNS messages to our topic.

::

    $ aws sns publish --topic-arn arn:aws:sns:us-west-2:12345:MyDemoTopic \
        --subject TestSubject --message TestMessage
    {
        "MessageId": "abcdefgh-3e56-54bd-a471-72477b5388af"
    }
    $ aws sns publish --topic-arn arn:aws:sns:us-west-2:12345:MyDemoTopic \
        --subject TestSubject2 --message TestMessage2
    {
        "MessageId": "abcdefgh-3e56-54bd-a471-72477b5388ag"
    }

We should now see log messages showing that our Lambda function was invoked.
We can wait for the messages using the ``chalice logs`` command.

::

    $ chalice logs --follow -n handle_sns_message
    ... 217378 chalice-sns-demo - DEBUG - Received message with subject: TestSubject, message: TestMessage
    ... 217378 chalice-sns-demo - DEBUG - Received message with subject: TestSubject2, message: TestMessage2

Next Steps
----------

In addition to SNS, chalice supports other event sources including Amazon S3,
Amazon SQS, as well as scheduled events.  You can check out the topic guide
on :doc:`../topics/events` for more details.

Cleaning Up
-----------

Once you're done experimenting you can clean up by deleting the Chalice
app and deleting the SNS topic::

    $ chalice delete
    Deleting function: arn:aws:lambda:us-west-2:21345:function:chalice-sns-demo...
    Deleting IAM role: chalice-sns-demo-dev
    $ aws sns delete-topic --topic-arn arn:aws:sns:us-west-2:12345:MyDemoTopic
