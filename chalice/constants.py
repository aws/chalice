
# This is the version that's written to the config file
# on a `chalice new-project`.  It's also how chalice is able
# to know when to warn you when changing behavior is introduced.
CONFIG_VERSION = '2.0'


TEMPLATE_APP = """\
from chalice import Chalice

app = Chalice(app_name='%s')


@app.route('/')
def index():
    return {'hello': 'world'}


# The view function above will return {"hello": "world"}
# whenever you make an HTTP GET request to '/'.
#
# Here are a few more examples:
#
# @app.route('/hello/{name}')
# def hello_name(name):
#    # '/hello/james' -> {"hello": "james"}
#    return {'hello': name}
#
# @app.route('/users', methods=['POST'])
# def create_user():
#     # This is the JSON body the user sent in their POST request.
#     user_as_json = app.current_request.json_body
#     # We'll echo the json body back to the user in a 'user' key.
#     return {'user': user_as_json}
#
# See the README documentation for more examples.
#
"""


GITIGNORE = """\
.chalice/deployments/
.chalice/venv/
"""

DEFAULT_STAGE_NAME = 'dev'
DEFAULT_APIGATEWAY_STAGE_NAME = 'api'
DEFAULT_ENDPOINT_TYPE = 'EDGE'
DEFAULT_TLS_VERSION = 'TLS_1_2'

DEFAULT_LAMBDA_TIMEOUT = 60
DEFAULT_LAMBDA_MEMORY_SIZE = 128
MAX_LAMBDA_DEPLOYMENT_SIZE = 50 * (1024 ** 2)
# This is the name of the main handler used to
# handle API gateway requests.  This is used as a key
# in the config module.
DEFAULT_HANDLER_NAME = 'api_handler'

MIN_COMPRESSION_SIZE = 0
MAX_COMPRESSION_SIZE = 10485760

LAMBDA_TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "",
        "Effect": "Allow",
        "Principal": {
            "Service": "lambda.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
    }]
}


CLOUDWATCH_LOGS = {
    "Effect": "Allow",
    "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
    ],
    "Resource": "arn:*:logs:*:*:*"
}


VPC_ATTACH_POLICY = {
    "Effect": "Allow",
    "Action": [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DetachNetworkInterface",
        "ec2:DeleteNetworkInterface"
    ],
    "Resource": "*"
}

XRAY_POLICY = {
    'Effect': 'Allow',
    'Action': [
        'xray:PutTraceSegments',
        'xray:PutTelemetryRecords',
    ],
    'Resource': '*'
}

CODEBUILD_POLICY = {
    "Version": "2012-10-17",
    # This is the policy straight from the console.
    "Statement": [
        {
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "s3:GetObject",
                "s3:GetObjectVersion",
                "s3:PutObject"
            ],
            "Resource": "arn:*:s3:::*",
            "Effect": "Allow"
        }
    ]
}

CODEPIPELINE_POLICY = {
    "Version": "2012-10-17",
    # Also straight from the console setup.
    "Statement": [
        {
            "Action": [
                "s3:GetObject",
                "s3:GetObjectVersion",
                "s3:GetBucketVersioning",
                "s3:CreateBucket",
                "s3:PutObject",
                "s3:PutBucketVersioning"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "codecommit:CancelUploadArchive",
                "codecommit:GetBranch",
                "codecommit:GetCommit",
                "codecommit:GetUploadArchiveStatus",
                "codecommit:UploadArchive"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "cloudwatch:*",
                "iam:PassRole"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "lambda:InvokeFunction",
                "lambda:ListFunctions"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "cloudformation:CreateStack",
                "cloudformation:DeleteStack",
                "cloudformation:DescribeStacks",
                "cloudformation:UpdateStack",
                "cloudformation:CreateChangeSet",
                "cloudformation:DeleteChangeSet",
                "cloudformation:DescribeChangeSet",
                "cloudformation:ExecuteChangeSet",
                "cloudformation:SetStackPolicy",
                "cloudformation:ValidateTemplate",
                "iam:PassRole"
            ],
            "Resource": "*",
            "Effect": "Allow"
        },
        {
            "Action": [
                "codebuild:BatchGetBuilds",
                "codebuild:StartBuild"
            ],
            "Resource": "*",
            "Effect": "Allow"
        }
    ]
}


WELCOME_PROMPT = r"""

   ___  _  _    _    _     ___  ___  ___
  / __|| || |  /_\  | |   |_ _|/ __|| __|
 | (__ | __ | / _ \ | |__  | || (__ | _|
  \___||_||_|/_/ \_\|____||___|\___||___|


The python serverless microframework for AWS allows
you to quickly create and deploy applications using
Amazon API Gateway and AWS Lambda.

Please enter the project name"""


MISSING_DEPENDENCIES_TEMPLATE = r"""
Could not install dependencies:
%s
You will have to build these yourself and vendor them in
the chalice vendor folder.

Your deployment will continue but may not work correctly
if missing dependencies are not present. For more information:
http://aws.github.io/chalice/topics/packaging.html

"""


EXPERIMENTAL_ERROR_MSG = """

You are using experimental features without explicitly opting in.
Experimental features do not guarantee backwards compatibility and may be
removed in the future.  If you'd still like to use these experimental features,
you can opt in by adding this to your app.py file:\n\n%s

See https://aws.github.io/chalice/topics/experimental.html for more
details.
"""


SQS_EVENT_SOURCE_POLICY = {
    "Effect": "Allow",
    "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
    ],
    "Resource": "*",
}


KINESIS_EVENT_SOURCE_POLICY = {
    "Effect": "Allow",
    "Action": [
        "kinesis:GetRecords",
        "kinesis:GetShardIterator",
        "kinesis:DescribeStream",
        "kinesis:ListStreams",
    ],
    "Resource": "*",
}


DDB_EVENT_SOURCE_POLICY = {
    "Effect": "Allow",
    "Action": [
        "dynamodb:DescribeStream",
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:ListStreams"
    ],
    "Resource": "*"
}


POST_TO_WEBSOCKET_CONNECTION_POLICY = {
    "Effect": "Allow",
    "Action": [
        "execute-api:ManageConnections"
    ],
    "Resource": "arn:*:execute-api:*:*:*/@connections/*"
}
