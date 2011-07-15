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

import math
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

    def as_callback(self, fn):
        self.filter = lambda x: fn(x.asString().decode('utf-8'))

        return self

    @xmlresult
    def all(self, first=-1, last=-1):
        for i, xmlresult in enumerate(self.xmlresults):
            if (first == -1 or i >= first) and (last == -1 or i < last):
                self.resultset.append(self.filter(xmlresult))
            else:
                self.resultset.append(None)

        del self.xmlresults

        return self.resultset

    @xmlresult
    def first(self):
        self.xmlresults.reset()

        if self.xmlresults.hasNext():
            self.resultset.append(self.filter(self.xmlresults.next()))

        del self.xmlresults

        try:
            return self.resultset[0]
        except IndexError:
            return None

    @xmlresult
    def first_or_404(self):
        result = self.first()

        if result is None:
            abort(404)

        return result

    @xmlresult
    def paginate(self, page, per_page, error_out=True):

        if error_out and page < 1:
            abort(404)

        offset = (page - 1) * per_page
        last = offset + per_page
        items = self.all(offset, last)[offset:last]

        if not items and page != 1 and error_out:
            abort(404)

        return Pagination(self, page, per_page, len(self.resultset), items)


class DBXML(object):

    def __init__(self):
        self.manager = None
        self.container = None

    def connect(self, app):
        self.env = DBEnv()

        self.env.set_cachesize(app.config['DBXML_CACHESIZE_GB'],
                               app.config['DBXML_CACHESIZE_BYTES'])
        self.env.set_lk_max_locks(10000)
        self.env.set_lk_max_lockers(10000)
        self.env.set_lk_max_objects(10000)

        self.env.open(app.config['DBXML_ENV'],
                      DB_CREATE|DB_INIT_LOCK|DB_INIT_LOG| \
                      DB_INIT_MPOOL|DB_INIT_TXN|DB_THREAD|DB_RECOVER, 0)

        self.manager = XmlManager(self.env, DBXML_ALLOW_EXTERNAL_ACCESS)

        if app.debug:
            self.manager.setLogLevel(LEVEL_ALL, True)

        self.db = DB(self.env)
        self.db.open(app.config['DBXML_ENV'] + 'seq.db', DB_BTREE,
                     DB_AUTO_COMMIT|DB_CREATE)
        try:
            cc = XmlContainerConfig()
            cc.setAllowCreate(True)
            cc.setIndexNodes(True)
            cc.setThreaded(True)
            cc.setTransactional(True)

            self.container = self.manager. \
                openContainer(app.config['DBXML_DATABASE'], cc)

            uc = self.manager.createUpdateContext()
            self.container.setAutoIndexing(False, uc)
        except XmlException:
            self.cleanup()
            raise

    def cleanup(self):
        if hasattr(self, 'container'):
            del self.container
        if hasattr(self, 'manager'):
            del self.manager
        if hasattr(self, 'env'):
            self.env.close(0)
            del self.env

    def init_app(self, app):

        app.config.setdefault('DBXML_DATABASE', 'default.dbxml')
        app.config.setdefault('DBXML_CACHESIZE_GB', 0)
        app.config.setdefault('DBXML_CACHESIZE_BYTES', 64 * 1024 * 1024)

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

    @property
    def session(self):
        ctx = _request_ctx_stack.top
        if ctx is not None:
            return ctx.dbxml

    @cached_property
    def collection(self):
        return 'dbxml:///' + current_app.config['DBXML_DATABASE']

    def add_document(self, filename=None, docname=None):
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

    def rm_document(self, docname=None):
        if docname is None:
            return

        update_context = self.manager.createUpdateContext()
        txn = self.manager.createTransaction()

        try:
            self.container.deleteDocument(txn, docname, update_context)
            txn.commit()
            print 'Document removed successfully.'
        except XmlException:
            txn.abort()
            print 'Document not found. Aborting.'

    def add_indexes(self, indexes):
        """Programatically adds new indexes to the container.

        `indexes` is a list of tuples which contains three elements:
        namespace, the element to be indexed, and the index string.

        It's highly recommended to perform this action right after creating
        the container. Otherwise, containers need to be reindexed and
        depending on the size of the current container, it can be a very
        expensive operation.
        """

        txn = self.manager.createTransaction()
        uc = self.manager.createUpdateContext()
        index_spec = self.container.getIndexSpecification()

        for (ns, element, index_string) in indexes:
            index_spec.addIndex(ns, element, index_string)

        try:
            self.container.setIndexSpecification(txn, index_spec, uc)
            txn.commit()
            print 'Indexes added successfully.'
        except XmlException:
            txn.abort()
            print 'Failed to add new indexes.'

    def generate_id(self, key):
        seq = DBSequence(self.db)
        seq.open(key, txn=None, flags=DB_CREATE)

        return seq.get()

    def _populate_context(self, qc, ctx):

        def _encoded_xml_value(val):

            if isinstance(val, unicode):
                newval = val.encode('utf-8')
            else:
                newval = str(val)

            return XmlValue(newval)

        for key, value in ctx.iteritems():
            if value is None:
                continue

            if isinstance(value, dict):
                self._populate_context(qc, value)
            elif isinstance(value, list):
                for val in value:
                    newval = self.manager.createResults()
                    newval.add(_encoded_xml_value(val))
            else:
                newval = _encoded_xml_value(value)

            qc.setVariableValue(key, newval)

    def query(self, query_string, context={}, document=None, **kwargs):

        if document:
            query = u'doc("{0}/{1}"){2}'.format(self.collection,
                                                document,
                                                query_string)
        else:
            query = u'collection("{0}"){1}'.format(self.collection,
                                                   query_string)

        return self.raw_query(query.encode('utf-8'), context, **kwargs)

    def template_query(self, template_name, context={}, **kwargs):

        # Open the template source, and pass it as the XQuery query
        jinja_env = current_app.jinja_env
        (query, filename, uptodate) = jinja_env.loader \
            .get_source(jinja_env, template_name)
        query = str(query.encode('utf-8'))

        return self.raw_query(query, context, **kwargs)

    def raw_query(self, query, context={}, txn=None, commit=True):

        context.update({'collection': self.collection})

        query_context = self.manager.createQueryContext()
        query_context.setEvaluationType(query_context.Lazy)

        query_context.setBaseURI(current_app.config['DBXML_BASE_URI'])

        self._populate_context(query_context, context)

        if txn is None:
            txn = self.manager.createTransaction()

        query_expression = self.manager.prepare(txn, query, query_context)

        try:
            result = query_expression.execute(txn, query_context).copyResults()
            if commit:
                txn.commit()
        except XmlException, e:
            result = []
            if commit:
                txn.abort()
        finally:
            del query_context
            del query_expression

        return Result(result)

    def insert_before(self, xml, where, document=None, **kwargs):

        if document:
            query = u'insert nodes {0} before doc("{1}/{2}"){3}'. \
                    format(xml, self.collection, document, where)
        else:
            query = u'insert nodes {0} before collection("{1}"){2}'. \
                    format(xml, self.collection, where)

        return self.insert_raw(query.encode('utf-8'), **kwargs)

    def insert_after(self, xml, where, document=None, **kwargs):

        if document:
            query = u'insert nodes {0} after doc("{1}/{2}"){3}'. \
                    format(xml, self.collection, document, where)
        else:
            query = u'insert nodes {0} after collection("{1}"){2}'. \
                    format(xml, self.collection, where)

        return self.insert_raw(query.encode('utf-8'), **kwargs)

    def insert_as_first(self, xml, where, document=None, **kwargs):

        if document:
            query = u'insert nodes {0} as first into doc("{1}/{2}"){3}'. \
                    format(xml, self.collection, document, where)
        else:
            query = u'insert nodes {0} as first into collection("{1}"){2}'. \
                    format(xml, self.collection, where)

        return self.insert_raw(query.encode('utf-8'), **kwargs)

    def insert_as_last(self, xml, where, document=None, **kwargs):

        if document:
            query = u'insert nodes {0} as last into doc("{1}/{2}"){3}'. \
                    format(xml, self.collection, document, where)
        else:
            query = u'insert nodes {0} as last into collection("{1}"){2}'. \
                    format(xml, self.collection, where)

        return self.insert_raw(query.encode('utf-8'), **kwargs)

    def replace(self, old, new, document=None, **kwargs):

        if document:
            query = u'replace node doc("{0}/{1}"){2} with {3}'. \
                    format(self.collection, document, old, new)
        else:
            query = u'replace node collection("{0}"){1} with {2}'. \
                    format(self.collection, old, new)

        return self.insert_raw(query.encode('utf-8'), **kwargs)

    def replace_value(self, old, new, document=None, **kwargs):

        if document:
            query = u'replace value of node doc("{0}/{1}"){2} with "{3}"'. \
                    format(self.collection, document, old, new)
        else:
            query = u'replace value of node collection("{0}"){1} with "{2}"'. \
                    format(self.collection, old, new)

        return self.insert_raw(query.encode('utf-8'), **kwargs)

    def insert_raw(self, query, context={}, txn=None, commit=True):

        context.update({'collection': self.collection})
        query_context = self.manager.createQueryContext()
        self._populate_context(query_context, context)

        if txn is None:
            txn = self.manager.createTransaction()

        try:
            result = self.manager.query(txn, query, query_context)

            if commit:
                txn.commit()

            return True
        except XmlException, e:
            result = []

            if commit:
                txn.abort()

            return False
        finally:
            del query_context
            del result


class Pagination(object):

    def __init__(self, queryset, page, per_page, total, items):

        self.queryset = queryset
        self.page = page
        self.per_page = per_page
        self.total = total
        self.items = items

    @property
    def pages(self):
        """The total number of pages"""
        return int(math.ceil(self.total / float(self.per_page)))

    def prev(self, error_out=False):
        """Returns a :class:`Pagination` object for the previous page."""
        assert self.queryset is not None, 'a query object is required ' \
                                       'for this method to work'
        return self.queryset.paginate(self.page - 1, self.per_page, error_out)

    @property
    def prev_num(self):
        """Number of the previous page."""
        return self.page - 1

    @property
    def has_prev(self):
        """True if a previous page exists"""
        return self.page > 1

    def next(self, error_out=False):
        """Returns a :class:`Pagination` object for the next page."""
        assert self.queryset is not None, 'a query object is required ' \
                                       'for this method to work'
        return self.queryset.paginate(self.page + 1, self.per_page, error_out)

    @property
    def has_next(self):
        """True if a next page exists."""
        return self.page < self.pages

    @property
    def next_num(self):
        """Number of the next page"""
        return self.page + 1

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        """Iterates over the page numbers in the pagination.  The four
        parameters control the thresholds how many numbers should be produced
        from the sides.  Skipped page numbers are represented as `None`.
        This is how you could render such a pagination in the templates:

        .. sourcecode:: html+jinja

            {% macro render_pagination(pagination, endpoint) %}
              <div class=pagination>
              {%- for page in pagination.iter_pages() %}
                {% if page %}
                  {% if page != pagination.page %}
                    <a href="{{ url_for(endpoint, page=page) }}">{{ page }}</a>
                  {% else %}
                    <strong>{{ page }}</strong>
                  {% endif %}
                {% else %}
                  <span class=ellipsis>…</span>
                {% endif %}
              {%- endfor %}
              </div>
            {% endmacro %}
        """
        last = 0
        for num in xrange(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num
