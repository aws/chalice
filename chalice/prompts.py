WELCOME_PROMPT = r"""

      ___          ___          ___          ___               ___          ___
     /\  \        /\__\        /\  \        /\__\   ___       /\  \        /\  \
    /::\  \      /:/  /       /::\  \      /:/  /  /\  \     /::\  \      /::\  \
   /:/\:\  \    /:/__/       /:/\:\  \    /:/  /   \:\  \   /:/\:\  \    /:/\:\  \
  /:/  \:\  \  /::\  \ ___  /::\~\:\  \  /:/  /    /::\__\ /:/  \:\  \  /::\~\:\  \
 /:/__/ \:\__\/:/\:\  /\__\/:/\:\ \:\__\/:/__/  __/:/\/__//:/__/ \:\__\/:/\:\ \:\__\
 \:\  \  \/__/\/__\:\/:/  /\/__\:\/:/  /\:\  \ /\/:/  /   \:\  \  \/__/\:\~\:\ \/__/
  \:\  \           \::/  /      \::/  /  \:\  \\::/__/     \:\  \       \:\ \:\__\
   \:\  \          /:/  /       /:/  /    \:\  \\:\__\      \:\  \       \:\ \/__/
    \:\__\        /:/  /       /:/  /      \:\__\\/__/       \:\__\       \:\__\
     \/__/        \/__/        \/__/        \/__/             \/__/        \/__/


Chalice is a serverless microframework for python.
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
    return click.prompt(WELCOME_PROMPT)
