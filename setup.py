#!/usr/bin/env python
from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    README = readme_file.read()


install_requires = [
    'click==6.6',
    'botocore>=1.5.40,<2.0.0',
    'typing==3.6.4',
    'six>=1.10.0,<2.0.0',
    'pip>=9,<11',
    'attrs==17.4.0',
    'enum34==1.1.6',
    'jmespath>=0.9.3,<1.0.0',
    'watchdog==0.8.3',
]

setup(
    name='chalice',
    version='1.3.0',
    description="Microframework",
    long_description=README,
    author="James Saryerwinnie",
    author_email='js@jamesls.com',
    url='https://github.com/aws/chalice',
    packages=find_packages(exclude=['tests']),
    install_requires=install_requires,
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
