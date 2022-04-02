#!/usr/bin/env python3
try:
    from aws_cdk import core as cdk
except ImportError:
    import aws_cdk as cdk
from stacks.chaliceapp import ChaliceApp

app = cdk.App()
ChaliceApp(app, '{{app_name}}')

app.synth()
