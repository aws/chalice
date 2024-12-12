# CHANGELOG


## 1.31.3


* enhancement:Pip:Update pip to the latest version (<24.4)
* enhancement:CLI:Remove distutils warning when packaging/deploying apps (#2123)

## 1.31.2


* enhancement:SQS:Add configuration option for MaximumConcurrency for SQS event source (#2104)

## 1.31.1


* enhancement:pip:Update pip version to allow 24.0 (#2092)
* bugfix:tar:Validate tar extraction does not escape destination dir (#1990)

## 1.31.0


* feature:Python:Add support for Python 3.12 (#2086)
* enhancement:Python:Drop support for Python 3.7 (#2095)

## 1.30.0


* feature:Python:Add support for Python 3.11 (#2053)
* enhancement:Pip:Update version dependency on pip (#2080)

## 1.29.0


* feature:Python:Add support for Python 3.10 (#2037)
* enhancement:Pip:Bump pip version range to latest version <23.2 (#2034)

## 1.28.0


* enhancement:Terraform:Update required terraform version to support 1.3 (#2014)
* enhancement:Pip:Bump pip version range to latest version <22.3 (#2016)
* feature:Config:Add support for `log_retention_in_days` (#943)

## 1.27.3


* bugfix:Versioning:Fix version string updates used in the release process (#1971)

## 1.27.2


* enhancement:Terraform:Update aws provider constraint to allow versions 4.x (#1951)
* enhancement:event-source:Add attribute for message attributes in SNSEvent and generated test events (#1934)

## 1.27.1


* enhancement:Pip:Bump pip version range to latest version <22.2 (#1924)
* enhancement:Websockets:Add support for WebSockets API Terraform packaging (#1670)

## 1.27.0


* bugfix:Local:Set a default timeout when creating the local LambdaContext instance (#1896)
* feature:CDK:Add support for CDK v2 (#1742)

## 1.26.6


* bugfix:pip:Fix RuntimeError with pip v22.x (#1887)

## 1.26.5


* enhancement:Terraform:Remove template provider in favor of locals (#1869)
* enhancement:Terraform:Bump Terraform version to suppose 1.1.x (#1868)

## 1.26.4


* bugfix:Terraform:Use updated keywords for providing provider version constraints (#1717)

## 1.26.3


* enhancement:Errors:Remove redundant error code in error message string (#1339)
* enhancement:VPC:Associate VPC endpoint with Rest API (#1449)

## 1.26.2


* enhancement:Dependencies:Update pyyaml to 6.x (#1830)
* bugfix:Websocket:Correctly configure websocket endpoint in the aws-cn partition (#1820)

## 1.26.1


* enhancement:Dependencies:Bump pip dependency to latest released version (#1817)
* enhancement:Tests:Don't include tests package in .whl file (#1814)

## 1.26.0


* feature:Websockets:Add support for setting the Websocket protocol from the connect handler (#1768)
* feature:SQS:Added MaximumBatchingWindowInSeconds to SQS event handler (#1778)

## 1.25.0


* feature:Python:Add support for Python 3.9 (#1787)

## 1.24.2


* enhancement:Dependencies:Bump attrs dependency to latest version (#1786)
* bugfix:Auth:Fix ARN parsing when generating a builtin AuthResponse (#1775)
* enhancement:CLI:Upgrade Click dependency to support v8.0.0 (#1729)

## 1.24.1


* bugfix:GovCloud:Fix partition error when updating API Gateway in GovCloud region (#1770)

## 1.24.0


* feature:Python2.7:Remove support for Python 2.7 (#1766)
* enhancement:Terraform:Update Terraform packaging to support version 1.0 (#1757)
* enhancement:Typing:Add missing WebsocketEvent type information (#1746)
* enhancement:S3 events:Add source account to Lambda permissions when configuring S3 events (#1635)
* enhancement:Packaging:Add support for Terraform v0.15 (#1725)

## 1.23.0


* enhancement:Deploy:Wait for function state to be active when deploying
* feature:SQS:Add queue_arn parameter to enable CDK integration with SQS event handler (#1681)

## 1.22.4


* enhancement:Types:Add missing types to app.pyi stub file (#1701)
* bugfix:Custom Domain:Fix custom domain generation when using the CDK (#1640)
* bugfix:Packaging:Special cases pyrsistent packaging (#1696)

## 1.22.3


* enhancement:Terraform:Bump Terraform version to include 0.14
* bugfix:Typing:Fix type definitions in app.pyi (#1676)
* bugfix:Terraform:Use references instead of function names in Terraform packaging (#1558)

## 1.22.2


* enhancement:Blueprint:Add log property to blueprint
* bugfix:Pipeline:Fix build command in pipeline generation (#1653)
* enhancement:Dependencies:Change enum-compat dependency to enum34 with version restrictions (#1667)

## 1.22.1


* enhancement:Pip:Bump pip version range to latest version 21.x (#1630)
* enhancement:IAM:Improve client call collection when generation policies (#692)

## 1.22.0


* feature:CDK:Add built-in support for the AWS CDK (#1622)

## 1.21.9


* enhancement:Dependencies:Bump attr version constraint (#1620)

## 1.21.8


* enhancement:Authorizers:Add support for custom headers in built-in authorizers (#1613)

## 1.21.7


* enhancement:Terraform:Map custom domain outputs in Terraform packaging (#1601)

## 1.21.6


* enhancement:Packaging:Increase upper bound for AWS provider in Terraform to 3.x (#1596)
* enhancement:Packaging:Add support for manylinux2014 wheels (#1551)

## 1.21.5


* bugfix:Config:Fix config validation for env vars on py27 (#1573)
* bugfix:Pip:Bump pip version contraint (#1590)
* bugfix:REST:Add Allow header with list of allowed methods when returning 405 error (#1583)

## 1.21.4


* enhancement:Local:Allow custom Chalice class in local mode (#1502)
* bugfix:Layers:Ensure single reference to managed layer (#1563)

## 1.21.3


* enhancement:Test:Add test client methods for generating sample kinesis events
* enhancement:Config:Validate env var values are strings (#1543)

## 1.21.2


* bugfix:Terraform:Fix issue with wildcard partition names in s3 event handlers (#1508)
* bugfix:Auth:Fix special case processing for root URL auth (#1271)
* enhancement:Middleware:Add support for HTTP middleware catching exceptions (#1541)

## 1.21.1


* bugfix:Websockets:Fix custom domain name configuration for websockets (#1531)
* bugfix:Local:Add support for multiple actions in builtin auth in local mode (#1527)
* bugfix:Websocket:Fix websocket client configuration when using a custom domain (#1503)
* bugfix:Local:Fix CORs handling in local mode (#761)

## 1.21.0


* bugfix:Blueprints:Fix regression when invoking Lambda functions from blueprints (#1535)
* feature:Events:Add support for Kinesis and DynamoDB event handlers (#987)

## 1.20.1


* bugfix:Blueprints:Preserve docstring in blueprints (#1525)
* enhancement:Binary:Support returning native python types when using `*/*` for binary types (#1501)

## 1.20.0


* enhancement:Blueprints:Add `current_app` property to Blueprints (#1094)
* enhancement:CLI:Set `AWS_CHALICE_CLI_MODE` env var whenever a Chalice CLI command is run (#1200)
* feature:Middleware:Add support for middleware (#1509)
* feature:X-Ray:Add support for AWS X-Ray (#464)

## 1.19.0


* feature:Pipeline:Add a new v2 template for the deployment pipeline CloudFormation template (#1506)

## 1.18.1


* bugfix:Packaging:Add fallback to retrieve name/version from sdist (#1486)
* bugfix:Analyzer:Handle symbols with multiple (shadowed) namespaces (#1494)

## 1.18.0


* feature:Packaging:Add support for automatic layer creation (#1485, #1001)

## 1.17.0


* feature:Testing:Add Chalice test client (#1468)
* enhancement:regions:Add support for non `aws` partitions including aws-cn and aws-us-gov (#792).
* bugfix:dependencies:Fix error when using old versions of click by requiring >=7
* bugfix:local:Fix local mode builtin authorizer not stripping query string from URL (#1470)

## 1.16.0


* enhancement:local:Avoid error from cognito client credentials in local authorizer (#1447)
* bugfix:package:Traverse symlinks to directories when packaging the vendor directory (#583).
* feature:DomainName:Add support for custom domain names to REST/WebSocket APIs (#1194)
* feature:auth:Add support for oauth scopes on routes (#1444).

## 1.15.1


* bugfix:packaging:Fix setup.py dependencies where the wheel package was not being installed (#1435)

## 1.15.0


* feature:blueprints:Mark blueprints as an accepted API (#1250)
* feature:package:Add ability to generate and merge yaml CloudFormation templates (#1425)
* enhancement:terraform:Allow generated terraform template to be used as a terraform module (#1300)
* feature:logs:Add support for tailing logs (#4).

## 1.14.1


* enhancement:pip:Update pip version range to 20.1.

## 1.14.0


* bugfix:packaging:Fix pandas packaging regression (#1398)
* feature:CLI:Add ``dev plan/appgraph`` commands (#1396)
* enhancement:SQS:Validate queue name is used and not queue URL or ARN (#1388)

## 1.13.1


* enhancement:local:Add support for multiValueHeaders in local mode (#1381).
* bugfix:local:Make ``current_request`` thread safe in local mode (#759)
* enhancement:local:Add support for cognito in local mode (#1377).
* bugfix:packaging:Fix terraform generation when injecting custom domains (#1237)
* enhancement:packaging:Ensure repeatable zip file generation (#1114).
* bugfix:CORS:Fix CORS request when returning compressed binary types (#1336)

## 1.13.0


* bugfix:logs:Fix error for ``chalice logs`` when a Lambda function
has not been invoked (#1252)
* feature:CORS:Add global CORS configuration (#70)
* bugfix:packaging:Fix packaging simplejson (#1304)
* feature:python:Add support for Python 3.8 (#1315)
* feature:authorizer:Add support for invocation role in custom authorizer (#1303)
* bugfix:packaging:Fix packaging on case-sensitive filesystems (#1356)

## 1.12.0


* feature:CLI:Add ``generate-models`` command (#1245)
* enhancement:websocket:Add ``close`` and ``info`` commands to websocket api (#1259)
* enhancement:dependencies:Bump upper bound on PIP to ``<19.4`` (#1273, #1272)

## 1.11.1


* bugfix:blueprint:Fix mouting blueprints with root routes (#1230)
* feature:rest-api:Add support for multi-value headers responses (#1205)

## 1.11.0


* feature:config:Add support for stage independent lambda configuration (#1162)
* feature:event-source:Add support for subscribing to CloudWatch Events (#1126)
* feature:event-source:Add a ``description`` argument to CloudWatch schedule events (#1155)
* bugfix:rest-api:Fix deployment of API Gateway resource policies (#1220)

## 1.10.0


* feature:websocket:Add experimental support for websockets (#1017)
* feature:rest-api:API Gateway Endpoint Type Configuration (#1160)
* feature:rest-api:API Gateway Resource Policy Configuration (#1160)
* feature:packaging:Add --merge-template option to package command (#1195)
* feature:packaging:Add support for packaging via terraform (#1129)

## 1.9.1


* enhancement:rest-api:Make MultiDict mutable (#1158)

## 1.9.0


* enhancement:dependencies:Update PIP to support up to 19.1.x (#1104)
* bugfix:rest-api:Fix handling of more complex Accept headers for binary
content types (#1078)
* enhancement:rest-api:Raise TypeError when trying to serialize an unserializable
type (#1100)
* enhancement:policy:Update ``policies.json`` file (#1110)
* feature:rest-api:Support repeating values in the query string (#1131)
* feature:packaging:Add layer support to chalice package (#1130)
* bugfix:rest-api:Fix bug with route ``name`` kwarg raising a ``TypeError`` (#1112)
* enhancement:logging:Change exceptions to always be logged at the ERROR level (#969)
* bugfix:CLI:Fix bug handling exceptions during ``chalice invoke`` on
Python 3.7 (#1139)
* bugfix:rest-api:Add support for API Gateway compression (#672)
* enhancement:packaging:Add support for both relative and absolute paths for
``--package-dir`` (#940)

## 1.8.0


* bugfix:packaging:Fall back to pure python version of yaml parser
when unable to compile C bindings for PyYAML (#1074)
* feature:packaging:Add support for Lambda layers. (#1001)

## 1.7.0


* bugfix:packaging:Fix packaging multiple local directories as dependencies (#1047)
* feature:event-source:Add support for passing SNS ARNs to ``on_sns_message`` (#1048)
* feature:blueprint:Add support for Blueprints (#1023)
* feature:config:Add support for opting-in to experimental features (#1053)
* feature:event-source:Provide Lambda context in event object (#856)

## 1.6.2


* enhancement:dependencies:Add support for pip 18.2 (#991)
* enhancement:logging:Add more detailed debug logs to the packager. (#934)
* feature:python:Add support for python3.7 (#992)
* feature:rest-api:Support bytes for the application/json binary type (#988)
* enhancement:rest-api:Use more compact JSON representation by default for dicts (#958)
* enhancement:logging:Log internal exceptions as errors (#254)
* feature:rest-api:Generate swagger documentation from docstrings (#574)

## 1.6.1


* bugfix:local:Fix local mode issue with unicode responses and Content-Length (#910)
* enhancement:dev:Fix issue with ``requirements-dev.txt`` not setting up a working
dev environment (#920)
* enhancement:dependencies:Add support for pip 18 (#910)

## 1.6.0


* feature:CLI:Add ``chalice invoke`` command (#900)

## 1.5.0


* feature:policy:Add support for S3 upload_file/download_file in
policy generator (#889)

## 1.4.0


* enhancement:CI-CD:Add support for generating python 3.6 pipelines (#858)
* feature:event-source:Add support for connecting lambda functions to S3 events (#855)
* feature:event-source:Add support for connecting lambda functions to SNS message (#488)
* enhancement:local:Make ``watchdog`` an optional dependency and add a built in
``stat()`` based file poller (#867)
* feature:event-source:Add support for connecting lambda functions to an SQS queue (#884)

## 1.3.0


* feature:config:Add support for Lambdas in a VPC (#413, #837, #673)
* feature:packaging:Add support for packaging local directories (#653)
* enhancement:local:Add support for automatically reloading the local
dev server when files are modified (#316, #846, #706)
* enhancement:logging:Add support for viewing cloudwatch logs of all
lambda functions (#841, #849)

## 1.2.3


* enhancement:dependency:Add support for pip 10 (#808)
* enhancement:policy:Update ``policies.json`` file (#817)

## 1.2.2


* bugfix:packaging:Fix package command not correctly setting environment variables (#795)

## 1.2.1


* enhancement:rest-api:Add CORS headers to error response (#715)
* bugfix:local:Fix parsing empty query strings in local mode (#767)
* bugfix:packaging:Fix regression in ``chalice package`` when using role arns (#793)

## 1.2.0

This release features a rewrite of the core deployment
code used in Chalice.  This is a backwards compatible change
for users, but you may see changes to the autogenerated
files Chalice creates.
Please read the `upgrade notes for 1.2.0
<http://chalice.readthedocs.io/en/latest/upgrading.html#v1-2-0>`__
for more detailed information about upgrading to this release.



* enhancement:rest-api:Print out full stack trace when an error occurs (#711)
* enhancement:rest-api:Add ``image/jpeg`` as a default binary content type (#707)
* feature:event-source:Add support for AWS Lambda only projects (#162, #640)
* bugfix:policy:Fix inconsistent IAM role generation with pure lambdas (#685)
* enhancement:deployment:Rewrite Chalice deployer to more easily support additional AWS resources (#604)
* feature:packaging:Update the ``chalice package`` command to support
pure lambda functions and scheduled events. (#772)
* bugfix:packaging:Fix packager edge case normalizing sdist names (#778)
* bugfix:packaging:Fix SQLAlchemy packaging (#778)
* bugfix:packaging:Fix packaging abi3, wheels this fixes cryptography 2.2.x packaging (#764)

## 1.1.1


* feature:CLI:Add ``--connection-timeout`` to the ``deploy`` command (#344)
* bugfix:policy:Fix IAM role creation issue (#565)
* bugfix:local:Fix `chalice local` handling of browser requests (#565)
* enhancement:policy:Support async/await syntax in automatic policy generation (#565)
* enhancement:packaging:Support additional PyPi package formats (.tar.bz2) (#720)

## 1.1.0


* enhancement:rest-api:Default to ``None`` in local mode when no query parameters
are provided (#593)
* enhancement:local:Add support for binding a custom address for local dev server (#596)
* bugfix:rest-api:Fix local mode handling of routes with trailing slashes (#582)
* bugfix:config:Scale ``lambda_timeout`` parameter correctly in local mode (#579)
* feature:CI-CD:Add ``--codebuild-image`` to the ``generate-pipeline`` command (#609)
* feature:CI-CD:Add ``--source`` and ``--buildspec-file`` to the
``generate-pipeline`` command (#609)

## 1.0.4


* bugfix:packaging:Fix issue deploying some packages in Windows with utf-8 characters (#560)
* feature:packaging:Add support for custom authorizers with ``chalice package`` (#580)

## 1.0.3


* bugfix:packaging:Fix issue with some packages with `-` or `.` in their distribution name (#555)
* bugfix:rest-api:Fix issue where chalice local returned a 403 for successful OPTIONS requests (#554)
* bugfix:local:Fix issue with chalice local mode causing http clients to hang on responses
with no body (#525)
* enhancement:local:Add ``--stage`` parameter to ``chalice local`` (#545)
* bugfix:policy:Fix issue with analyzer that followed recursive functions infinitely (#531)

## 1.0.2


* bugfix:rest-api:Fix issue where requestParameters were not being mapped
correctly resulting in invalid generated javascript SDKs (#498)
* bugfix:rest-api:Fix issue where ``api_gateway_stage`` was being
ignored when set in the ``config.json`` file (#495)
* bugfix:rest-api:Fix bug where ``raw_body`` would raise an exception if no HTTP
body was provided (#503)
* bugfix:CLI:Fix bug where exit codes were not properly being propagated during packaging (#500)
* feature:local:Add support for Builtin Authorizers in local mode (#404)
* bugfix:packaging:Fix environment variables being passed to subprocess while packaging (#501)
* enhancement:rest-api:Allow view to require API keys as well as authorization (#473)

## 1.0.1


* bugfix:packaging:Only use alphanumeric characters for event names in SAM template (#450)
* enhancement:config:Print useful error message when config.json is invalid (#458)
* bugfix:rest-api:Fix api gateway stage being set incorrectly in non-default chalice stage
(`#$70 <https://github.com/aws/chalice/issues/470>`__)

## 1.0.0


* enhancement:rest-api:Change default API Gateway stage name to ``api`` (#431)
* enhancement:local:Add support for ``CORSConfig`` in ``chalice local`` (#436)
* enhancement:logging:Propagate ``DEBUG`` log level when setting ``app.debug`` (#386)
* feature:rest-api:Add support for wildcard routes and HTTP methods in ``AuthResponse`` (#403)
* bugfix:policy:Fix bug when analyzing list comprehensions (#412)
* enhancement:local:Update ``chalice local`` to use HTTP 1.1 (#448)

## 1.0.0b2

Please read the `upgrade notes for 1.0.0b2
<http://chalice.readthedocs.io/en/latest/upgrading.html#v1-0-0b2>`__
for more detailed information about upgrading to this release.

Note: to install this beta version of chalice you must specify
``pip install 'chalice>=1.0.0b2,<2.0.0'`` or
use the ``--pre`` flag for pip: ``pip install --pre chalice``.


* enhancement:local:Set env vars from config in ``chalice local`` (#396)
* bugfix:packaging:Fix edge case when building packages with optional c extensions (#421)
* enhancement:policy:Remove legacy ``policy.json`` file support. Policy files must
use the stage name, e.g. ``policy-dev.json`` (#430)
* bugfix:deployment:Fix issue where IAM role policies were updated twice on redeploys (#428)
* enhancement:rest-api:Validate route path is not an empty string (#432)
* enhancement:rest-api:Change route code to invoke view function with kwargs instead of
positional args (#429)

## 1.0.0b1

Please read the `upgrade notes for 1.0.0b1
<http://chalice.readthedocs.io/en/latest/upgrading.html#v1-0-0b1>`__
for more detailed information about upgrading to this release.

Note: to install this beta version of chalice you must specify
``pip install 'chalice>=1.0.0b1,<2.0.0'`` or
use the ``--pre`` flag for pip: ``pip install --pre chalice``.



* bugfix:rest-api:Fix unicode responses being quoted in python 2.7 (#262)
* feature:event-source:Add support for scheduled events (#390)
* feature:event-source:Add support for pure lambda functions (#390)
* feature:packaging:Add support for wheel packaging. (#249)

## 0.10.1


* bugfix:deployment:Fix deployment issue for projects deployed with versions
prior to 0.10.0 (#387)
* bugfix:policy:Fix crash in analyzer when encountering genexprs and listcomps (#263)

## 0.10.0


* bugfix:deployment:Fix issue where provided ``iam_role_arn`` was not respected on
redeployments of chalice applications and in the CloudFormation template
generated by ``chalice package`` (#339)
* bugfix:config:Fix ``autogen_policy`` in config being ignored (#367)
* feature:rest-api:Add support for view functions that share the same view url but
differ by HTTP method (#81)
* enhancement:deployment:Improve deployment error messages for deployment packages that are
too large (#246, #330, #380)
* feature:rest-api:Add support for built-in authorizers (#356)

## 0.9.0


* feature:rest-api:Add support for ``IAM`` authorizer (#334)
* feature:config:Add support for configuring ``lambda_timeout``, ``lambda_memory_size``,
and ``tags`` in your AWS Lambda function (#347)
* bugfix:packaging:Fix vendor directory contents not being importable locally (#350)
* feature:rest-api:Add support for binary payloads (#348)

## 0.8.2


* bugfix:CLI:Fix issue where ``--api-gateway-stage`` was being
ignored  (#325)
* feature:CLI:Add ``chalice delete`` command (#40)

## 0.8.1


* enhancement:deployment:Alway overwrite existing API Gateway Rest API on updates (#305)
* enhancement:CORS:Added more granular support for CORS (#311)
* bugfix:local:Fix duplicate content type header in local model (#311)
* bugfix:rest-api:Fix content type validation when charset is provided (#306)
* enhancement:rest-api:Add back custom authorizer support (#322)

## 0.8.0


* feature:python:Add support for python3! (#296)
* bugfix:packaging:Fix swagger generation when using ``api_key_required=True`` (#279)
* bugfix:CI-CD:Fix ``generate-pipeline`` to install requirements file before packaging (#295)

## 0.7.0


* feature:CLI:Add ``chalice package`` command.  This will
create a SAM template and Lambda deployment package that
can be subsequently deployed by AWS CloudFormation. (#258)
* feature:CLI:Add a ``--stage-name`` argument for creating chalice stages.
A chalice stage is a completely separate set of AWS resources.
As a result, most configuration values can also be specified
per chalice stage. (#264, #270)
* feature:policy:Add support for ``iam_role_file``, which allows you to
specify the file location of an IAM policy to use for your app (#272)
* feature:config:Add support for setting environment variables in your app (#273)
* feature:CI-CD:Add a ``generate-pipeline`` command (#277)

## 0.6.0

Check out the `upgrade notes for 0.6.0
<http://chalice.readthedocs.io/en/latest/upgrading.html#v0-6-0>`__
for more detailed information about changes in this release.



* feature:local:Add port parameter to local command (#220)
* feature:packaging:Add support for binary vendored packages (#182, #106, #42)
* feature:rest-api:Add support for customizing the returned HTTP response (#240, #218, #110, #30, #226)
* enhancement:packaging:Always inject latest runtime to allow for chalice upgrades (#245)

## 0.5.1


* enhancement:local:Add support for serializing decimals in ``chalice local`` (#187)
* enhancement:local:Add stdout handler for root logger when using ``chalice local`` (#186)
* enhancement:local:Map query string parameters when using ``chalice local`` (#184)
* enhancement:rest-api:Support Content-Type with a charset (#180)
* bugfix:deployment:Fix not all resources being retrieved due to pagination (#188)
* bugfix:deployment:Fix issue where root resource was not being correctly retrieved (#205)
* bugfix:deployment:Handle case where local policy does not exist
(`29 <https://github.com/awslabs/chalice/issues/29>`__)

## 0.5.0


* enhancement:logging:Add default application logger (#149)
* enhancement:local:Return 405 when method is not supported when running
``chalice local`` (#159)
* enhancement:SDK:Add path params as requestParameters so they can be used
in generated SDKs as well as cache keys (#163)
* enhancement:rest-api:Map cognito user pool claims as part of request context (#165)
* feature:CLI:Add ``chalice url`` command to print the deployed URL (#169)
* enhancement:deployment:Bump up retry limit on initial function creation to 30 seconds (#172)
* feature:local:Add support for ``DELETE`` and ``PATCH`` in ``chalice local`` (#167)
* feature:CLI:Add ``chalice generate-sdk`` command (#178)

## 0.4.0


* bugfix:deployment:Fix issue where role name to arn lookup was failing due to lack of pagination (#139)
* enhancement:rest-api:Raise errors when unknown kwargs are provided to ``app.route(...)`` (#144)
* enhancement:config:Raise validation error when configuring CORS and an OPTIONS method (#142)
* feature:rest-api:Add support for multi-file applications (#21)
* feature:local:Add support for ``chalice local``, which runs a local HTTP server for testing (#22)

## 0.3.0


* bugfix:rest-api:Fix bug with case insensitive headers (#129)
* feature:CORS:Add initial support for CORS (#133)
* enhancement:deployment:Only add API gateway permissions if needed (#48)
* bugfix:policy:Fix error when dict comprehension is encountered during policy generation (#131)
* enhancement:CLI:Add ``--version`` and ``--debug`` options to the chalice CLI

## 0.2.0


* enhancement:rest-api:Add support for input content types besides ``application/json`` (#96)
* enhancement:rest-api:Allow ``ChaliceViewErrors`` to propagate, so that API Gateway
can properly map HTTP status codes in non debug mode (#113)
* enhancement:deployment:Add windows compatibility (#31)

## 0.1.0


* enhancement:packaging:Require ``virtualenv`` as a package dependency. (#33)
* enhancement:CLI:Add ``--profile`` option when creating a new project (#28)
* enhancement:rest-api:Add support for more error codes exceptions (#34)
* enhancement:rest-api:Improve error validation when routes containing a
trailing ``/`` char (#65)
* enhancement:rest-api:Validate duplicate route entries (#79)
* enhancement:policy:Ignore lambda expressions in policy analyzer (#74)
* enhancement:rest-api:Print original error traceback in debug mode (#50)
* feature:rest-api:Add support for authenticate routes (#14)
* feature:policy:Add ability to disable IAM role management (#61)
