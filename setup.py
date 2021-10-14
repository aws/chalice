#!/usr/bin/env python
import os
from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    README = readme_file.read()


def recursive_include(relative_dir):
    all_paths = []
    root_prefix = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'chalice')
    full_path = os.path.join(root_prefix, relative_dir)
    for rootdir, _, filenames in os.walk(full_path):
        for filename in filenames:
            abs_filename = os.path.join(rootdir, filename)
            all_paths.append(abs_filename[len(root_prefix) + 1:])
    return all_paths


install_requires = [
    'click>=7,<9.0',
    'botocore>=1.14.0,<2.0.0',
    'typing==3.6.4;python_version<"3.7"',
    'mypy-extensions==0.4.3',
    'six>=1.10.0,<2.0.0',
    'pip>=9,<21.4',
    'attrs>=19.3.0,<21.3.0',
    'jmespath>=0.9.3,<1.0.0',
    'pyyaml>=5.3.1,<6.0.0',
    'inquirer>=2.7.0,<3.0.0',
    'wheel',
    'setuptools'
]

setup(
    name='chalice',
    version='1.26.1',
    description="Microframework",
    long_description=README,
    author="James Saryerwinnie",
    author_email='js@jamesls.com',
    url='https://github.com/aws/chalice',
    packages=find_packages(exclude=['tests', 'tests.*']),
    install_requires=install_requires,
    extras_require={
        'event-file-poller': ['watchdog==0.9.0'],
        'cdk': [
            'aws_cdk.aws_iam>=1.85.0,<2.0',
            'aws_cdk.aws-s3-assets>=1.85.0,<2.0',
            'aws_cdk.cloudformation-include>=1.85.0,<2.0',
            'aws_cdk.core>=1.85.0,<2.0',
        ]
    },
    license="Apache License 2.0",
    package_data={'chalice': [
        '*.json', '*.pyi', 'py.typed'] + recursive_include('templates')},
    include_package_data=True,
    zip_safe=False,
    keywords='chalice',
    entry_points={
        'console_scripts': [
            'chalice = chalice.cli:main',
        ]
    },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        "Programming Language :: Python :: 3",
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
)
