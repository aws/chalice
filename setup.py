#!/usr/bin/env python
from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    README = readme_file.read()


install_requires = [
    'click>=7,<8.0',
    'botocore>=1.12.86,<2.0.0',
    'typing==3.6.4;python_version<"3.7"',
    'mypy-extensions==0.4.3',
    'six>=1.10.0,<2.0.0',
    'pip>=9,<20.4',
    'attrs>=19.3.0,<20.3.0',
    'enum-compat>=0.0.2',
    'jmespath>=0.9.3,<1.0.0',
    'pyyaml>=5.3.1,<6.0.0',
    'wheel',
    'setuptools'
]

setup(
    name='chalice',
    version='1.21.7',
    description="Microframework",
    long_description=README,
    author="James Saryerwinnie",
    author_email='js@jamesls.com',
    url='https://github.com/aws/chalice',
    packages=find_packages(exclude=['tests']),
    install_requires=install_requires,
    extras_require={
        'event-file-poller': ['watchdog==0.9.0'],
    },
    license="Apache License 2.0",
    package_data={'chalice': ['*.json', 'py.typed']},
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
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
)
