# -*- coding: utf-8 -*-
"""
    flaskext.dbxml
    ~~~~~~~~~~~~~~

    Wrapper around DB-XML for Flask.

    :copyright: (c) 2011 by Julen Ruiz Aizpuru.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import absolute_import

from flask import _request_ctx_stack, current_app

from werkzeug.utils import cached_property

import dbxml


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

        return self.resultset


class DBXML(object):

    def __init__(self):
        self.manager = None
        self.container = None

    def connect(self, app):
        # XXX: Investigate if DBXML_ALLOW_AUTO_OPEN is really necessary
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

        if self.manager is None or self.container is None:
            self.connect()

        update_context = self.manager.createUpdateContext()

        doc = open(filename)

        if docname is None:
            import os
            docname = os.path.basename(filename)

        try:
            self.container.putDocument(docname, doc.read(), update_context)
            print 'Document added successfully.'
        except dbxml.XmlUniqueError:
            print 'Document already in container. Skipping.'

    def query(self, query_string, context={}):
        query_string = query_string.encode('utf-8')

        query = "collection('{0}'){1}".format(self.collection, query_string)

        return self.raw_query(query, context)

    def template_query(self, template_name, dbxml_context={}, jinja_context={}):
        jinja_context.update({'collection': self.collection})

        template = current_app.jinja_env.get_template(template_name)
        rendered_query = template.render(jinja_context).encode('utf-8')

        return self.raw_query(rendered_query, dbxml_context)

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
