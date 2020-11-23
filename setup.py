from setuptools import setup

__version__ = '0.1'

setup(
    name='django_websockets2',
    version=__version__,
    description='Native implementation of websockets and fast ASGI support',
    long_description="""
    Unlocks full power of async Django >= 3.1, including websockets and 
    async coroutines. No monkeypatching, simple and efficient implementation
    based on Django core features. See README for details.""",
    author='https://github.com/kozzztik',
    url='https://github.com/kozzztik/django-websockets2',
    keywords='',
    packages=['django_websockets2'],
    include_package_data=True,
    license=
    'https://github.com/kozzztik/django-websockets2/blob/master/LICENSE',
    classifiers=[
        'License :: OSI Approved',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        ],
    install_requires=[
        "Django >= 3.1.0",
    ],
)
