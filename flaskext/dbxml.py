# -*- coding: utf-8 -*-
"""
    flaskext.dbxml
    ~~~~~~~~~~~~~~

    Wrapper around DB-XML for Flask.

    :copyright: (c) 2011 by Julen Ruiz Aizpuru.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import absolute_import

from flask import _request_ctx_stack, current_app, render_template_string

from werkzeug.utils import cached_property

import dbxml
import os


def xmlresult(fn):
    """Requires the result passed to be an instance of XmlResults."""
    def wrapper(obj, *args, **kwargs):
        if isinstance(obj.xmlresults, dbxml.XmlResults):
            return fn(obj, *args, **kwargs)
    return wrapper


class Result(object):

    def __init__(self, xmlresults):
        self.xmlresults = xmlresults
        self.resultset = []
        self.filter = lambda x: x

    def as_str(self):
        self.filter = lambda x: x.asString().decode('utf-8')

        return self

    def as_rendered(self):
        self.filter = lambda x: render_template_string(x.asString()
                                                        .decode('utf-8'))

        return self

    @xmlresult
    def all(self):
        while self.xmlresults.hasNext():
            self.resultset.append(self.filter(self.xmlresults.next()))

        self.xmlresults.reset()

        return self.resultset

    @xmlresult
    def first(self):
        self.xmlresults.reset()

        if self.xmlresults.hasNext():
            self.resultset.append(self.filter(self.xmlresults.next()))

        try:
            return self.resultset[0]
        except IndexError:
            return None


class DBXML(object):

    def __init__(self):
        self.manager = None
        self.container = None

    def connect(self, app):
        self.manager = dbxml.XmlManager(dbxml.DBXML_ALLOW_AUTO_OPEN)

        self.container_config = dbxml.XmlContainerConfig()
        self.container_config.setAllowCreate(True)

        self.container = self.manager.openContainer(app.config['DBXML_DATABASE'],
                                                    self.container_config)

    def init_app(self, app):
        app.config.setdefault('DBXML_DATABASE', 'default.dbxml')

        self.connect(app)

        @app.before_request
        def before_request():
            ctx = _request_ctx_stack.top
            ctx.dbxml = self

        @app.after_request
        def after_request(response):
            ctx = _request_ctx_stack.top
            del ctx.dbxml
            return response

    def get_db(self):
        ctx = _request_ctx_stack.top
        if ctx is not None:
            return ctx.dbxml

    @cached_property
    def collection(self):
        return 'dbxml:///' + current_app.config['DBXML_DATABASE']

    def init_dbxml(self, filename=None, docname=None):
        if filename is None:
            return

        filename = os.path.abspath(filename)

        update_context = self.manager.createUpdateContext()

        if docname is None:
            docname = os.path.basename(filename)

        xml_input = self.manager.createLocalFileInputStream(filename)

        try:
            self.container.putDocument(docname, xml_input, update_context)
            self.container.sync()
            print 'Document added successfully.'
        except dbxml.XmlUniqueError:
            print 'Document already in container. Skipping.'

    def query(self, query_string, context={}):
        query_string = query_string.encode('utf-8')

        query = "collection('{0}'){1}".format(self.collection, query_string)

        return self.raw_query(query, context)

    def template_query(self, template_name, context={}):
        context.update({'collection': self.collection})

        # Open the template source, and pass it as the XQuery query
        jinja_env = current_app.jinja_env
        (query, filename, uptodate) = jinja_env.loader \
            .get_source(jinja_env, template_name)
        query = str(query.encode('utf-8'))

        return self.raw_query(query, context)

    def raw_query(self, query, context={}):
        query_context = self.manager.createQueryContext()
        query_context.setEvaluationType(query_context.Lazy)

        for key, value in context.iteritems():
            query_context.setVariableValue(key, dbxml.XmlValue(str(value)))

        query_expression = self.manager.prepare(query, query_context)

        try:
            result = self.manager.query(query, query_context)
        except dbxml.XmlException:
            result = []

        return Result(result)

    def insert_before(self, xml, where):
        query = "insert nodes {0} before collection('{1}'){2}". \
                format(xml, self.collection, where)

        return self.insert_raw(query)

    def insert_raw(self, query):
        query_context = self.manager.createQueryContext()
        query_context.setEvaluationType(query_context.Lazy)

        query_expression = self.manager.prepare(query, query_context)

        try:
            self.manager.query(query, query_context)
            return True
        except dbxml.XmlException, e:
            return False
