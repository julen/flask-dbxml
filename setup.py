"""
Flask-DBXML
-----------

Wrapper around DB-XML for Flask.

Links
`````

* `documentation <http://packages.python.org/Flask-DBXML>`_
* `development version
  <http://github.com/julen/flask-dbxml/zipball/master#egg=Flask-DBXML-dev>`_

"""
from setuptools import setup


setup(
    name='Flask-DBXML',
    version='0.1',
    url='http://github.com/julen/flask-dbxml',
    license='BSD',
    author='Julen Ruiz Aizpuru',
    author_email='julenx@gmail.com',
    description='Wrapper around DB-XML for Flask.',
    long_description=__doc__,
    packages=['flaskext'],
    namespace_packages=['flaskext'],
    zip_safe=False,
    platforms='any',
    install_requires=[
        'Flask'
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ]
)
