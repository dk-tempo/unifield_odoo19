#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
OpenObject Client Library
"""

import sys
import socket
import zlib
import xmlrpc.client
from .timeout_transport import TimeoutTransport, TimeoutSafeTransport
import ssl
from odoo.exceptions import UserError, ValidationError
from odoo import tools
from odoo import _

import io
import logging

GZIP_MAGIC = '\x78\xda' # magic when max compression used
NB_RETRY = 10

class Connector(object):
    """
    Connector class
    """

    _logger = logging.getLogger('connector')

    def __init__(self, hostname, port, timeout):
        """
        :param hostname: Host name of the server
        :param port: Port for the connection to the server
        """
        self.hostname = hostname
        self.port = port
        self.timeout = timeout

class XmlRPCConnector(Connector):
    """
    This class supports the XmlRPC protocol
    """
    PROTOCOL = 'xmlrpc'

    def __init__(self, hostname, port=8069, timeout=10.0, retry=0):
        Connector.__init__(self, hostname, port, timeout=timeout)
        self._logger = logging.getLogger('connector.xmlrpc')
        self.url = 'http://%s:%s/xmlrpc' % (self.hostname, self.port)
        self.retry = retry

    def send(self, service_name, method, *args):
        url = '%s/%s' % (self.url, service_name)
        transport = TimeoutTransport(timeout=self.timeout)
        # Enable gzip on all payloads
        transport.encode_threshold = 0
        service = xmlrpc.client.ServerProxy(url, allow_none=1, transport=transport)
        return self._send(service, method, *args)

    def _send(self, service, method, *args):
        i = 0
        retry = True
        while retry:
            try:
                retry = False
                return getattr(service, method)(*args)
            except Exception as e:
                error = e
                if i < self.retry:
                    retry = True
                    self._logger.warning("retry to connect %s, error : %s" ,i, e)
                i += 1
        if error:
            raise UserError("Unable to proceed for the following reason:\n%s" % (error.faultCode if hasattr(error, 'faultCode') else error))


class SecuredXmlRPCConnector(XmlRPCConnector):
    """
    This class supports the XmlRPC protocol over HTTPS
    """
    PROTOCOL = 'xmlrpcs'

    def __init__(self, hostname, port=8070, timeout=10.0, retry=0):
        XmlRPCConnector.__init__(self, hostname, port, timeout=timeout, retry=retry)
        self.timeout = timeout
        self.url = 'https://%s:%s/xmlrpc' % (self.hostname, self.port)

    def send(self, service_name, method, *args):
        url = '%s/%s' % (self.url, service_name)
        # Decide whether to accept self-signed certificates
        ctx = ssl.create_default_context()
        transport = TimeoutSafeTransport(timeout=self.timeout)
        # Enable gzip on all payloads
        transport.encode_threshold = 0
        if not tools.config.get('secure_verify', True):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        service = xmlrpc.client.ServerProxy(url, allow_none=1, context=ctx, transport=transport)

        return self._send(service, method, *args)

class Connection(object):
    """
    TODO: Document this class
    """
    _logger = logging.getLogger('connection')

    def __init__(self, connector,
                 database,
                 login=None,
                 password=None,
                 user_id=None):
        """
        :param connector:
        :param database:
        :param login:
        :param password:
        """
        self.connector = connector
        self.database, self.login, self.password = database, login, password
        self.user_id = user_id
        if user_id is None:
            self.user_id = Common(self.connector).login(self.database, self.login, self.password)

        if self.user_id is False:
            raise UserError(_('Unable to connect to the distant server with this user!'))
        self._logger.debug(self.user_id)

    def __repr__(self):
        """
        Return a readable representation of the Connection object
        """
        url = "%(protocol)s://%(login)s:%(password)s@" \
              "%(hostname)s:%(port)d/%(database)s" % {
                  'protocol' : self.connector.PROTOCOL,
                  'login' : self.login,
                  'password' : self.password,
                  'hostname' : self.connector.hostname,
                  'port' : self.connector.port,
                  'database' : self.database,
              }

        return "Connection: %s" % url

class Common(object):
    _logger = logging.getLogger('connection.common')

    def __init__(self, connector):
        self.connector = connector

    def __getattr__(self, method):
        """
        :param method: The method for the linked object (search, read, write, unlink, create, ...)
        """
        #self._logger.debug('method: %r', method)
        def proxy(*args):
            """
            :param args: A list of values for the method
            """
            #self._logger.debug('args: %r', args)
            result = self.connector.send('common', method, *args)
            #self._logger.debug('result: %r' % result)
            return result
        return proxy

class Object(object):
    """
    TODO: Document this class
    """
    _logger = logging.getLogger('object')

    def __repr__(self):
        """
        """
        return "Object <%s>" % (self.model)

    def __init__(self, connection, model, context=None):
        """
        :param connection:
        :param model:
        """
        self.connection = connection
        self.model = model

        self.context = context

    def __getattr__(self, method):
        """
        :param method: The method for the linked object (search, read, write, unlink, create, ...)
        """
        def proxy(*args):
            """
            :param args: A list of values for the method
            """
            return self.__send__(method, *args)
        return proxy

    def __send__(self, method, *args):
        #self._logger.debug('method: %r', method)
        #self._logger.debug('args: %r', args)

        result = self.connection.connector.send('object', 'execute',
                                                self.connection.database,
                                                self.connection.user_id,
                                                self.connection.password,
                                                self.model,
                                                method,
                                                *args)
        #self._logger.debug('result: %r', result)
        return result

    def __add_context(self, arguments, context=None):
        if context is None:
            context = {}

        if self.context is not None:
            context.update(self.context)

        arguments.append(context)
        return arguments

    def exists(self, oid, context=None):
        # TODO: bug, we can't use the read(fields=['id']),
        # because the server returns a positive value but the record does not exist
        # into the database
        value = self.search_count([('id', '=', oid)], context=context)

        return value > 0

    def read(self, ids, fields=None, context=None):
        if fields is None:
            fields = []

        arguments = [ids, fields]
        arguments = self.__add_context(arguments, context)

        records = self.__send__('read', *arguments)

        if isinstance(ids, (list, tuple)):
            records.sort(key=lambda x: ids.index(x['id']))

        return records

    def search(self, domain=None, offset=0, limit=None, order=None, context=None):
        if domain is None:
            domain = []

        if limit is None:
            limit = self.search_count(domain)

        arguments = [domain, offset, limit, order is not None and\
                     order != 'NO_ORDER' and order or False]

        arguments = self.__add_context(arguments, context)

        return self.__send__('search', *arguments)

    def search_count(self, domain, context=None):
        if context is None:
            context = {}

        return self.__send__('search_count', domain, context)

    def write(self, ids, values, context=None):
        if not ids:
            return True
        if not isinstance(ids, (tuple, list)):
            ids = [ids]
        arguments = self.__add_context([ids, values], context)

        return self.__send__('write', *arguments)

    def create(self, values, context=None):
        arguments = self.__add_context([values], context)

        return self.__send__('create', *arguments)

    def unlink(self, ids, context=None):
        if not isinstance(ids, (tuple, list)):
            ids = [ids]
        arguments = self.__add_context([ids], context)

        return self.__send__('unlink', *arguments)

    def select(self, domain=None, fields=None, offset=0, limit=None, order=None, context=None):
        record_ids = self.search(domain, offset=offset, limit=limit, order=order, context=context)

        return self.read(record_ids, fields=fields, context=context)


