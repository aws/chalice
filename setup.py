#!/usr/bin/env python
from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    README = readme_file.read()


install_requires = [
    'click==6.6',
    'botocore>=1.4.8,<2.0.0',
    'virtualenv>=15.0.0,<16.0.0',
    'typing==3.5.3.0',
]

setup(
    name='chalice',
    version='0.6.0',
    description="Microframework",
    long_description=README,
    author="James Saryerwinnie",
    author_email='js@jamesls.com',
    url='https://github.com/jamesls/chalice',
    python_requires=">=2.7,<3",
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
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
    ],
)
