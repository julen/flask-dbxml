# -*- coding: utf-8 -*-
"""
    flaskext.dbxml
    ~~~~~~~~~~~~~~

    Wrapper around DB-XML for Flask.

    :copyright: (c) 2011 by Julen Ruiz Aizpuru.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import absolute_import

from flask import _request_ctx_stack, abort, current_app, render_template_string

from werkzeug.utils import cached_property

from bsddb3.db import *
from dbxml import *

import os


def xmlresult(fn):
    """Requires the result passed to be an instance of XmlResults."""
    def wrapper(obj, *args, **kwargs):
        if isinstance(obj.xmlresults, XmlResults):
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
        self.env = DBEnv()
        self.env.open(app.config['DBXML_ENV'],
                      DB_CREATE|DB_INIT_LOCK|DB_INIT_LOG| \
                      DB_INIT_MPOOL|DB_INIT_TXN, 0)

        self.manager = XmlManager(self.env, DBXML_ALLOW_EXTERNAL_ACCESS)

        self.db = DB(self.env)
        self.db.open(app.config['DBXML_ENV'] + 'seq.db', DB_BTREE,
                     DB_AUTO_COMMIT|DB_CREATE)
        try:
            self.container = self.manager. \
                openContainer(app.config['DBXML_DATABASE'],
                              DB_CREATE|DBXML_TRANSACTIONAL)
        except XmlException:
            abort(500)

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
        txn = self.manager.createTransaction()

        if docname is None:
            docname = os.path.basename(filename)

        xml_input = self.manager.createLocalFileInputStream(filename)

        try:
            self.container.putDocument(txn, docname, xml_input, update_context)
            txn.commit()
            print 'Document added successfully.'
        except XmlUniqueError:
            print 'Document already in container. Skipping.'
        except XmlException:
            txn.abort()
            print 'Transaction failed. Aborting.'

    def generate_id(self, key):
        seq = DBSequence(self.db)
        seq.open(key, txn=None, flags=DB_CREATE)

        return seq.get()

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

        query_context.setBaseURI(current_app.config['DBXML_BASE_URI'])

        for key, value in context.iteritems():
            query_context.setVariableValue(key, XmlValue(str(value)))

        query_expression = self.manager.prepare(query, query_context)

        try:
            result = self.manager.query(query, query_context)
        except XmlException:
            result = []

        return Result(result)

    def insert_before(self, xml, where):
        query = "insert nodes {0} before collection('{1}'){2}". \
                format(xml, self.collection, where)

        return self.insert_raw(query)

    def insert_raw(self, query):
        query_context = self.manager.createQueryContext()
        query_context.setEvaluationType(query_context.Lazy)

        txn = self.manager.createTransaction()

        query_expression = self.manager.prepare(txn, query, query_context)

        try:
            self.manager.query(txn, query, query_context)
            txn.commit()
            return True
        except XmlException, e:
            txn.abort()
            return False
