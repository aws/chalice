#!/usr/bin/env python
from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    README = readme_file.read()


install_requires = []
with open("./requirements.txt") as f:
    install_requires = f.read().splitlines()


setup(
    name='chalice',
    version='1.11.1',
    description="Microframework",
    long_description=README,
    author="James Saryerwinnie",
    author_email='js@jamesls.com',
    url='https://github.com/aws/chalice',
    packages=find_packages(exclude=['tests']),
    install_requires=install_requires,
    extras_require={
        'event-file-poller': ['watchdog==0.8.3'],
    },
    license="Apache License 2.0",
    package_data={'chalice': ['*.json']},
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
    ],
)
