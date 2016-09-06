from typing import Any  # noqa


WELCOME_PROMPT = r"""

   ___  _  _    _    _     ___  ___  ___
  / __|| || |  /_\  | |   |_ _|/ __|| __|
 | (__ | __ | / _ \ | |__  | || (__ | _|
  \___||_||_|/_/ \_\|____||___|\___||___|


The python serverless microframework for AWS allows
you to quickly create and deploy applications using
Amazon API Gateway and AWS Lambda.

Right now it's under developer preview and we're looking
for customer feedback.
Be aware that there are several features missing:

* No support for authentication or authorization
* No support for stages
* No support for CORS

If you'd like to proceded, then answer the questions
below.

Please enter the project name"""


def getting_started_prompt(click):
    # type: (Any) -> bool
    return click.prompt(WELCOME_PROMPT)
