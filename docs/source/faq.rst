Frequently Asked Questions
==========================

**Q: What is AWS Chalice?**

AWS Chalice is a framework for writing serverless apps in python.
It consists of a CLI, a declarative python API for connecting
events to AWS Lambda functions, and a runtime component that
provides APIs accessible to your Lambda functions.

**Q: Why should I use AWS Chalice?**

Chalice is designed for a seamless getting started experience
that can get you up and running quickly.  It handles all the
boilerplate and low level details of creating a serverless
application, allowing you to focus on the business logic
of your application.  It also provides deep integration with
various AWS services allowing you to take advantage of the
features available in each service.

**Q: How does Chalice compare to AWS SAM and the AWS CDK?**

Chalice is designed to work together with AWS SAM.
SAM focus on provisioning the resources needed
for your application, and not necessarily on the application code
itself.  Chalice provides a set of APIs to help you write your
application code, including a routing layer for REST and Websocket
APIs, and decorators to connect various AWS event sources to
Lambda functions.  It then can integrate with AWS SAM by offloading
the deployment to AWS CloudFormation.

**Q: How does Chalice compare to other similiar frameworks?**

The biggest difference between Chalice and other frameworks is that Chalice
is focused on using a familiar, decorator-based API to write serverless
python applications that run on AWS Lambda.  Its goal is to make writing and
deploying these types of applications as simple as possible specifically for
Python developers.  It was designed from the ground up to run in a
serverless environment.

To achieve this goal, it has to make certain tradeoffs.  Chalice makes
assumptions about how applications will be deployed, and it has restrictions on
how an application can be structured.  The feature set is purposefully small.
