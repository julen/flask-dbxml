# -*- coding: utf-8 -*-
"""
    flaskext.dbxml
    ~~~~~~~~~~~~~~

    Wrapper around DB-XML for Flask.

    :copyright: (c) 2011 by Julen Ruiz Aizpuru.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import absolute_import

from flask import abort, current_app, g

from werkzeug.utils import cached_property

import dbxml

import os


class DBXML(object):

    def __init__(self):
        self.manager = None
        self.container = None

    def connect(self, app):
        # XXX: Investigate if DBXML_ALLOW_AUTO_OPEN is really necessary
        self.manager = dbxml.XmlManager(dbxml.DBXML_ALLOW_AUTO_OPEN)
        self.container = self.manager.openContainer(app.config['DBXML_DATABASE'])

    def init_app(self, app):
        app.config.setdefault('DBXML_DATABASE', 'default.dbxml')
        app.config.setdefault('DBXML_DEFAULT_COLLECTION', 'default.dbxml')

        self.connect(app)

        @app.before_request
        def before_request():
            g.dbxml = self

        @app.after_request
        def after_request(response):
            del g.dbxml
            return response

    @cached_property
    def collection(self):
        return os.path.basename(current_app.config['DBXML_DATABASE'])

    def query(self, query_string):
        query = "collection('{0}'){1}".format(self.collection, query_string)

        return self.raw_query(query)

    def raw_query(self, query):
        result = None

        query_context = self.manager.createQueryContext()
        query_context.setEvaluationType(query_context.Lazy)

        query_expression = self.manager.prepare(query, query_context)

        try:
            result = self.manager.query(query, query_context)
        except dbxml.XmlException:
            abort(500)

        return result
