# Changelog


## v1.32.0


### Features
* Add support for Python 3.13 (#2137)
* Drop support for Python 3.8 (#2138)

## v1.31.4


### Enhancements
* Update pip to the latest version (<25.1)

## v1.31.3


### Enhancements
* Update pip to the latest version (<24.4)
* Remove distutils warning when packaging/deploying apps (#2123)

## v1.31.2


### Enhancements
* Add configuration option for MaximumConcurrency for SQS event source (#2104)

## v1.31.1


### Enhancements
* Update pip version to allow 24.0 (#2092)

### Bug fixes
* Validate tar extraction does not escape destination dir (#1990)

## v1.31.0


### Features
* Add support for Python 3.12 (#2086)

### Enhancements
* Drop support for Python 3.7 (#2095)

## v1.30.0


### Features
* Add support for Python 3.11 (#2053)

### Enhancements
* Update version dependency on pip (#2080)

## v1.29.0


### Features
* Add support for Python 3.10 (#2037)

### Enhancements
* Bump pip version range to latest version <23.2 (#2034)

## v1.28.0


### Features
* Add support for `log_retention_in_days` (#943)

### Enhancements
* Update required terraform version to support 1.3 (#2014)
* Bump pip version range to latest version <22.3 (#2016)

## v1.27.3


### Bug fixes
* Fix version string updates used in the release process (#1971)

## v1.27.2


### Enhancements
* Update aws provider constraint to allow versions 4.x (#1951)
* Add attribute for message attributes in SNSEvent and generated test events (#1934)

## v1.27.1


### Enhancements
* Bump pip version range to latest version <22.2 (#1924)
* Add support for WebSockets API Terraform packaging (#1670)

## v1.27.0


### Features
* Add support for CDK v2 (#1742)

### Bug fixes
* Set a default timeout when creating the local LambdaContext instance (#1896)

## v1.26.6


### Bug fixes
* Fix RuntimeError with pip v22.x (#1887)

## v1.26.5


### Enhancements
* Remove template provider in favor of locals (#1869)
* Bump Terraform version to suppose 1.1.x (#1868)

## v1.26.4


### Bug fixes
* Use updated keywords for providing provider version constraints (#1717)

## v1.26.3


### Enhancements
* Remove redundant error code in error message string (#1339)
* Associate VPC endpoint with Rest API (#1449)

## v1.26.2


### Enhancements
* Update pyyaml to 6.x (#1830)

### Bug fixes
* Correctly configure websocket endpoint in the aws-cn partition (#1820)

## v1.26.1


### Enhancements
* Bump pip dependency to latest released version (#1817)
* Don't include tests package in .whl file (#1814)

## v1.26.0


### Features
* Add support for setting the Websocket protocol from the connect handler (#1768)
* Added MaximumBatchingWindowInSeconds to SQS event handler (#1778)

## v1.25.0


### Features
* Add support for Python 3.9 (#1787)

## v1.24.2


### Enhancements
* Bump attrs dependency to latest version (#1786)
* Upgrade Click dependency to support v8.0.0 (#1729)

### Bug fixes
* Fix ARN parsing when generating a builtin AuthResponse (#1775)

## v1.24.1


### Bug fixes
* Fix partition error when updating API Gateway in GovCloud region (#1770)

## v1.24.0


### Features
* Remove support for Python 2.7 (#1766)

### Enhancements
* Update Terraform packaging to support version 1.0 (#1757)
* Add missing WebsocketEvent type information (#1746)
* Add source account to Lambda permissions when configuring S3 events (#1635)
* Add support for Terraform v0.15 (#1725)

## v1.23.0


### Features
* Add queue_arn parameter to enable CDK integration with SQS event handler (#1681)

### Enhancements
* Wait for function state to be active when deploying

## v1.22.4


### Enhancements
* Add missing types to app.pyi stub file (#1701)

### Bug fixes
* Fix custom domain generation when using the CDK (#1640)
* Special cases pyrsistent packaging (#1696)

## v1.22.3


### Enhancements
* Bump Terraform version to include 0.14

### Bug fixes
* Fix type definitions in app.pyi (#1676)
* Use references instead of function names in Terraform packaging (#1558)

## v1.22.2


### Enhancements
* Add log property to blueprint
* Change enum-compat dependency to enum34 with version restrictions (#1667)

### Bug fixes
* Fix build command in pipeline generation (#1653)

## v1.22.1


### Enhancements
* Bump pip version range to latest version 21.x (#1630)
* Improve client call collection when generation policies (#692)

## v1.22.0


### Features
* Add built-in support for the AWS CDK (#1622)

## v1.21.9


### Enhancements
* Bump attr version constraint (#1620)

## v1.21.8


### Enhancements
* Add support for custom headers in built-in authorizers (#1613)

## v1.21.7


### Enhancements
* Map custom domain outputs in Terraform packaging (#1601)

## v1.21.6


### Enhancements
* Increase upper bound for AWS provider in Terraform to 3.x (#1596)
* Add support for manylinux2014 wheels (#1551)

## v1.21.5


### Bug fixes
* Fix config validation for env vars on py27 (#1573)
* Bump pip version contraint (#1590)
* Add Allow header with list of allowed methods when returning 405 error (#1583)

## v1.21.4


### Enhancements
* Allow custom Chalice class in local mode (#1502)

### Bug fixes
* Ensure single reference to managed layer (#1563)

## v1.21.3


### Enhancements
* Add test client methods for generating sample kinesis events
* Validate env var values are strings (#1543)

## v1.21.2


### Enhancements
* Add support for HTTP middleware catching exceptions (#1541)

### Bug fixes
* Fix issue with wildcard partition names in s3 event handlers (#1508)
* Fix special case processing for root URL auth (#1271)

## v1.21.1


### Bug fixes
* Fix custom domain name configuration for websockets (#1531)
* Add support for multiple actions in builtin auth in local mode (#1527)
* Fix websocket client configuration when using a custom domain (#1503)
* Fix CORs handling in local mode (#761)

## v1.21.0


### Features
* Add support for Kinesis and DynamoDB event handlers (#987)

### Bug fixes
* Fix regression when invoking Lambda functions from blueprints (#1535)

## v1.20.1


### Enhancements
* Support returning native python types when using `*/*` for binary types (#1501)

### Bug fixes
* Preserve docstring in blueprints (#1525)

## v1.20.0


### Features
* Add support for middleware (#1509)
* Add support for AWS X-Ray (#464)

### Enhancements
* Add `current_app` property to Blueprints (#1094)
* Set `AWS_CHALICE_CLI_MODE` env var whenever a Chalice CLI command is run (#1200)

## v1.19.0


### Features
* Add a new v2 template for the deployment pipeline CloudFormation template (#1506)

## v1.18.1


### Bug fixes
* Add fallback to retrieve name/version from sdist (#1486)
* Handle symbols with multiple (shadowed) namespaces (#1494)

## v1.18.0


### Features
* Add support for automatic layer creation (#1485, #1001)

## v1.17.0


### Features
* Add Chalice test client (#1468)

### Enhancements
* Add support for non `aws` partitions including aws-cn and aws-us-gov (#792).

### Bug fixes
* Fix error when using old versions of click by requiring >=7
* Fix local mode builtin authorizer not stripping query string from URL (#1470)

## v1.16.0


### Features
* Add support for custom domain names to REST/WebSocket APIs (#1194)
* Add support for oauth scopes on routes (#1444).

### Enhancements
* Avoid error from cognito client credentials in local authorizer (#1447)

### Bug fixes
* Traverse symlinks to directories when packaging the vendor directory (#583).

## v1.15.1


### Bug fixes
* Fix setup.py dependencies where the wheel package was not being installed (#1435)

## v1.15.0


### Features
* Mark blueprints as an accepted API (#1250)
* Add ability to generate and merge yaml CloudFormation templates (#1425)
* Add support for tailing logs (#4).

### Enhancements
* Allow generated terraform template to be used as a terraform module (#1300)

## v1.14.1


### Enhancements
* Update pip version range to 20.1.

## v1.14.0


### Features
* Add ``dev plan/appgraph`` commands (#1396)

### Enhancements
* Validate queue name is used and not queue URL or ARN (#1388)

### Bug fixes
* Fix pandas packaging regression (#1398)

## v1.13.1


### Enhancements
* Add support for multiValueHeaders in local mode (#1381).
* Add support for cognito in local mode (#1377).
* Ensure repeatable zip file generation (#1114).

### Bug fixes
* Make ``current_request`` thread safe in local mode (#759)
* Fix terraform generation when injecting custom domains (#1237)
* Fix CORS request when returning compressed binary types (#1336)

## v1.13.0


### Features
* Add global CORS configuration (#70)
* Add support for Python 3.8 (#1315)
* Add support for invocation role in custom authorizer (#1303)

### Bug fixes
* Fix error for ``chalice logs`` when a Lambda function
has not been invoked (#1252)
* Fix packaging simplejson (#1304)
* Fix packaging on case-sensitive filesystems (#1356)

## v1.12.0


### Features
* Add ``generate-models`` command (#1245)

### Enhancements
* Add ``close`` and ``info`` commands to websocket api (#1259)
* Bump upper bound on PIP to ``<19.4`` (#1273, #1272)

## v1.11.1


### Features
* Add support for multi-value headers responses (#1205)

### Bug fixes
* Fix mouting blueprints with root routes (#1230)

## v1.11.0


### Features
* Add support for stage independent lambda configuration (#1162)
* Add support for subscribing to CloudWatch Events (#1126)
* Add a ``description`` argument to CloudWatch schedule events (#1155)

### Bug fixes
* Fix deployment of API Gateway resource policies (#1220)

## v1.10.0


### Features
* Add experimental support for websockets (#1017)
* API Gateway Endpoint Type Configuration (#1160)
* API Gateway Resource Policy Configuration (#1160)
* Add --merge-template option to package command (#1195)
* Add support for packaging via terraform (#1129)

## v1.9.1


### Enhancements
* Make MultiDict mutable (#1158)

## v1.9.0


### Features
* Support repeating values in the query string (#1131)
* Add layer support to chalice package (#1130)

### Enhancements
* Update PIP to support up to 19.1.x (#1104)
* Raise TypeError when trying to serialize an unserializable
type (#1100)
* Update ``policies.json`` file (#1110)
* Change exceptions to always be logged at the ERROR level (#969)
* Add support for both relative and absolute paths for
``--package-dir`` (#940)

### Bug fixes
* Fix handling of more complex Accept headers for binary
content types (#1078)
* Fix bug with route ``name`` kwarg raising a ``TypeError`` (#1112)
* Fix bug handling exceptions during ``chalice invoke`` on
Python 3.7 (#1139)
* Add support for API Gateway compression (#672)

## v1.8.0


### Features
* Add support for Lambda layers. (#1001)

### Bug fixes
* Fall back to pure python version of yaml parser
when unable to compile C bindings for PyYAML (#1074)

## v1.7.0


### Features
* Add support for passing SNS ARNs to ``on_sns_message`` (#1048)
* Add support for Blueprints (#1023)
* Add support for opting-in to experimental features (#1053)
* Provide Lambda context in event object (#856)

### Bug fixes
* Fix packaging multiple local directories as dependencies (#1047)

## v1.6.2


### Features
* Add support for python3.7 (#992)
* Support bytes for the application/json binary type (#988)
* Generate swagger documentation from docstrings (#574)

### Enhancements
* Add support for pip 18.2 (#991)
* Add more detailed debug logs to the packager. (#934)
* Use more compact JSON representation by default for dicts (#958)
* Log internal exceptions as errors (#254)

## v1.6.1


### Enhancements
* Fix issue with ``requirements-dev.txt`` not setting up a working
dev environment (#920)
* Add support for pip 18 (#910)

### Bug fixes
* Fix local mode issue with unicode responses and Content-Length (#910)

## v1.6.0


### Features
* Add ``chalice invoke`` command (#900)

## v1.5.0


### Features
* Add support for S3 upload_file/download_file in
policy generator (#889)

## v1.4.0


### Features
* Add support for connecting lambda functions to S3 events (#855)
* Add support for connecting lambda functions to SNS message (#488)
* Add support for connecting lambda functions to an SQS queue (#884)

### Enhancements
* Add support for generating python 3.6 pipelines (#858)
* Make ``watchdog`` an optional dependency and add a built in
``stat()`` based file poller (#867)

## v1.3.0


### Features
* Add support for Lambdas in a VPC (#413, #837, #673)
* Add support for packaging local directories (#653)

### Enhancements
* Add support for automatically reloading the local
dev server when files are modified (#316, #846, #706)
* Add support for viewing cloudwatch logs of all
lambda functions (#841, #849)

## v1.2.3


### Enhancements
* Add support for pip 10 (#808)
* Update ``policies.json`` file (#817)

## v1.2.2


### Bug fixes
* Fix package command not correctly setting environment variables (#795)

## v1.2.1


### Enhancements
* Add CORS headers to error response (#715)

### Bug fixes
* Fix parsing empty query strings in local mode (#767)
* Fix regression in ``chalice package`` when using role arns (#793)

## v1.2.0

This release features a rewrite of the core deployment
code used in Chalice.  This is a backwards compatible change
for users, but you may see changes to the autogenerated
files Chalice creates.
Please read the [upgrade notes for 1.2.0](https://aws.github.io/chalice/upgrading#v1-2-0)
for more detailed information about upgrading to this release.



### Features
* Add support for AWS Lambda only projects (#162, #640)
* Update the ``chalice package`` command to support
pure lambda functions and scheduled events. (#772)

### Enhancements
* Print out full stack trace when an error occurs (#711)
* Add ``image/jpeg`` as a default binary content type (#707)
* Rewrite Chalice deployer to more easily support additional AWS resources (#604)

### Bug fixes
* Fix inconsistent IAM role generation with pure lambdas (#685)
* Fix packager edge case normalizing sdist names (#778)
* Fix SQLAlchemy packaging (#778)
* Fix packaging abi3, wheels this fixes cryptography 2.2.x packaging (#764)

## v1.1.1


### Features
* Add ``--connection-timeout`` to the ``deploy`` command (#344)

### Enhancements
* Support async/await syntax in automatic policy generation (#565)
* Support additional PyPi package formats (.tar.bz2) (#720)

### Bug fixes
* Fix IAM role creation issue (#565)
* Fix `chalice local` handling of browser requests (#565)

## v1.1.0


### Features
* Add ``--codebuild-image`` to the ``generate-pipeline`` command (#609)
* Add ``--source`` and ``--buildspec-file`` to the
``generate-pipeline`` command (#609)

### Enhancements
* Default to ``None`` in local mode when no query parameters
are provided (#593)
* Add support for binding a custom address for local dev server (#596)

### Bug fixes
* Fix local mode handling of routes with trailing slashes (#582)
* Scale ``lambda_timeout`` parameter correctly in local mode (#579)

## v1.0.4


### Features
* Add support for custom authorizers with ``chalice package`` (#580)

### Bug fixes
* Fix issue deploying some packages in Windows with utf-8 characters (#560)

## v1.0.3


### Enhancements
* Add ``--stage`` parameter to ``chalice local`` (#545)

### Bug fixes
* Fix issue with some packages with `-` or `.` in their distribution name (#555)
* Fix issue where chalice local returned a 403 for successful OPTIONS requests (#554)
* Fix issue with chalice local mode causing http clients to hang on responses
with no body (#525)
* Fix issue with analyzer that followed recursive functions infinitely (#531)

## v1.0.2


### Features
* Add support for Builtin Authorizers in local mode (#404)

### Enhancements
* Allow view to require API keys as well as authorization (#473)

### Bug fixes
* Fix issue where requestParameters were not being mapped
correctly resulting in invalid generated javascript SDKs (#498)
* Fix issue where ``api_gateway_stage`` was being
ignored when set in the ``config.json`` file (#495)
* Fix bug where ``raw_body`` would raise an exception if no HTTP
body was provided (#503)
* Fix bug where exit codes were not properly being propagated during packaging (#500)
* Fix environment variables being passed to subprocess while packaging (#501)

## v1.0.1


### Enhancements
* Print useful error message when config.json is invalid (#458)

### Bug fixes
* Only use alphanumeric characters for event names in SAM template (#450)
* Fix api gateway stage being set incorrectly in non-default chalice stage
([#470](https://github.com/aws/chalice/issues/470))

## v1.0.0


### Features
* Add support for wildcard routes and HTTP methods in ``AuthResponse`` (#403)

### Enhancements
* Change default API Gateway stage name to ``api`` (#431)
* Add support for ``CORSConfig`` in ``chalice local`` (#436)
* Propagate ``DEBUG`` log level when setting ``app.debug`` (#386)
* Update ``chalice local`` to use HTTP 1.1 (#448)

### Bug fixes
* Fix bug when analyzing list comprehensions (#412)

## v1.0.0b2

Please read the [upgrade notes for 1.0.0b2](https://aws.github.io/chalice/upgrading#b2)
for more detailed information about upgrading to this release.

Note: to install this beta version of chalice you must specify
``pip install 'chalice>=1.0.0b2,<2.0.0'`` or
use the ``--pre`` flag for pip: ``pip install --pre chalice``.


### Enhancements
* Set env vars from config in ``chalice local`` (#396)
* Remove legacy ``policy.json`` file support. Policy files must
use the stage name, e.g. ``policy-dev.json`` (#430)
* Validate route path is not an empty string (#432)
* Change route code to invoke view function with kwargs instead of
positional args (#429)

### Bug fixes
* Fix edge case when building packages with optional c extensions (#421)
* Fix issue where IAM role policies were updated twice on redeploys (#428)

## v1.0.0b1

Please read the [upgrade notes for 1.0.0b1](https://aws.github.io/chalice/upgrading#b1)
for more detailed information about upgrading to this release.

Note: to install this beta version of chalice you must specify
``pip install 'chalice>=1.0.0b1,<2.0.0'`` or
use the ``--pre`` flag for pip: ``pip install --pre chalice``.



### Features
* Add support for scheduled events (#390)
* Add support for pure lambda functions (#390)
* Add support for wheel packaging. (#249)

### Bug fixes
* Fix unicode responses being quoted in python 2.7 (#262)

## v0.10.1


### Bug fixes
* Fix deployment issue for projects deployed with versions
prior to 0.10.0 (#387)
* Fix crash in analyzer when encountering genexprs and listcomps (#263)

## v0.10.0


### Features
* Add support for view functions that share the same view url but
differ by HTTP method (#81)
* Add support for built-in authorizers (#356)

### Enhancements
* Improve deployment error messages for deployment packages that are
too large (#246, #330, #380)

### Bug fixes
* Fix issue where provided ``iam_role_arn`` was not respected on
redeployments of chalice applications and in the CloudFormation template
generated by ``chalice package`` (#339)
* Fix ``autogen_policy`` in config being ignored (#367)

## v0.9.0


### Features
* Add support for ``IAM`` authorizer (#334)
* Add support for configuring ``lambda_timeout``, ``lambda_memory_size``,
and ``tags`` in your AWS Lambda function (#347)
* Add support for binary payloads (#348)

### Bug fixes
* Fix vendor directory contents not being importable locally (#350)

## v0.8.2


### Features
* Add ``chalice delete`` command (#40)

### Bug fixes
* Fix issue where ``--api-gateway-stage`` was being
ignored  (#325)

## v0.8.1


### Enhancements
* Alway overwrite existing API Gateway Rest API on updates (#305)
* Added more granular support for CORS (#311)
* Add back custom authorizer support (#322)

### Bug fixes
* Fix duplicate content type header in local model (#311)
* Fix content type validation when charset is provided (#306)

## v0.8.0


### Features
* Add support for python3! (#296)

### Bug fixes
* Fix swagger generation when using ``api_key_required=True`` (#279)
* Fix ``generate-pipeline`` to install requirements file before packaging (#295)

## v0.7.0


### Features
* Add ``chalice package`` command.  This will
create a SAM template and Lambda deployment package that
can be subsequently deployed by AWS CloudFormation. (#258)
* Add a ``--stage-name`` argument for creating chalice stages.
A chalice stage is a completely separate set of AWS resources.
As a result, most configuration values can also be specified
per chalice stage. (#264, #270)
* Add support for ``iam_role_file``, which allows you to
specify the file location of an IAM policy to use for your app (#272)
* Add support for setting environment variables in your app (#273)
* Add a ``generate-pipeline`` command (#277)

## v0.6.0

Check out the [upgrade notes for 0.6.0](https://aws.github.io/chalice/upgrading#v0-6-0)
for more detailed information about changes in this release.



### Features
* Add port parameter to local command (#220)
* Add support for binary vendored packages (#182, #106, #42)
* Add support for customizing the returned HTTP response (#240, #218, #110, #30, #226)

### Enhancements
* Always inject latest runtime to allow for chalice upgrades (#245)

## v0.5.1


### Enhancements
* Add support for serializing decimals in ``chalice local`` (#187)
* Add stdout handler for root logger when using ``chalice local`` (#186)
* Map query string parameters when using ``chalice local`` (#184)
* Support Content-Type with a charset (#180)

### Bug fixes
* Fix not all resources being retrieved due to pagination (#188)
* Fix issue where root resource was not being correctly retrieved (#205)
* Handle case where local policy does not exist
([#29](https://github.com/aws/chalice/issues/29))

## v0.5.0


### Features
* Add ``chalice url`` command to print the deployed URL (#169)
* Add support for ``DELETE`` and ``PATCH`` in ``chalice local`` (#167)
* Add ``chalice generate-sdk`` command (#178)

### Enhancements
* Add default application logger (#149)
* Return 405 when method is not supported when running
``chalice local`` (#159)
* Add path params as requestParameters so they can be used
in generated SDKs as well as cache keys (#163)
* Map cognito user pool claims as part of request context (#165)
* Bump up retry limit on initial function creation to 30 seconds (#172)

## v0.4.0


### Features
* Add support for multi-file applications (#21)
* Add support for ``chalice local``, which runs a local HTTP server for testing (#22)

### Enhancements
* Raise errors when unknown kwargs are provided to ``app.route(...)`` (#144)
* Raise validation error when configuring CORS and an OPTIONS method (#142)

### Bug fixes
* Fix issue where role name to arn lookup was failing due to lack of pagination (#139)

## v0.3.0


### Features
* Add initial support for CORS (#133)

### Enhancements
* Only add API gateway permissions if needed (#48)
* Add ``--version`` and ``--debug`` options to the chalice CLI

### Bug fixes
* Fix bug with case insensitive headers (#129)
* Fix error when dict comprehension is encountered during policy generation (#131)

## v0.2.0


### Enhancements
* Add support for input content types besides ``application/json`` (#96)
* Allow ``ChaliceViewErrors`` to propagate, so that API Gateway
can properly map HTTP status codes in non debug mode (#113)
* Add windows compatibility (#31)

## v0.1.0


### Features
* Add support for authenticate routes (#14)
* Add ability to disable IAM role management (#61)

### Enhancements
* Require ``virtualenv`` as a package dependency. (#33)
* Add ``--profile`` option when creating a new project (#28)
* Add support for more error codes exceptions (#34)
* Improve error validation when routes containing a
trailing ``/`` char (#65)
* Validate duplicate route entries (#79)
* Ignore lambda expressions in policy analyzer (#74)
* Print original error traceback in debug mode (#50)
