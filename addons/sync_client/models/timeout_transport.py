import http.client
import xmlrpc.client

import gzip
from io import BytesIO

from odoo.addons.rpc.controllers import xmlrpc as odoo_xmlrpc
#XMLRPC, dumps
from odoo.http import request, dispatch_rpc

def gzip_decode(data):
    """gzip encoded data -> unencoded data

    Decode data using the gzip content encoding as described in RFC 1952
    """
    if not gzip:
        raise NotImplementedError
    with gzip.GzipFile(mode="rb", fileobj=BytesIO(data)) as gzf:
        try:
            decoded = gzf.read()
        except OSError:
            raise ValueError("invalid data")
    return decoded


def _xmlrpc(self, service):
    """Common method to handle an XML-RPC gzip request."""
    data = request.httprequest.get_data()
    if request.httprequest.headers.get('Content-Encoding') == 'gzip':
        data = gzip_decode(data)
    params, method = xmlrpc.client.loads(data, use_datetime=True)
    result = dispatch_rpc(service, method, params)
    return odoo_xmlrpc.dumps((result,))

odoo_xmlrpc.XMLRPC._xmlrpc = _xmlrpc



class TimeoutHTTPConnection(http.client.HTTPConnection):

    def connect(self):
        http.client.HTTPConnection.connect(self)
        if self.timeout is not None:
            self.sock.settimeout(self.timeout)

    def set_timeout(self, timeout):
        self.timeout = timeout

class TimeoutTransport(xmlrpc.client.Transport):

    def __init__(self, timeout=None, *args, **kwargs):
        xmlrpc.client.Transport.__init__(self, *args, **kwargs)
        self.timeout = timeout

    def make_connection(self, host):
        chost, self._extra_headers, _ = self.get_host_info(host)
        self._connection = host, TimeoutHTTPConnection(chost)
        self._connection[1].set_timeout(self.timeout)
        return self._connection[1]

class TimeoutHTTPSConnection(http.client.HTTPSConnection):

    def connect(self):
        http.client.HTTPSConnection.connect(self)
        if self.timeout is not None:
            self.sock.settimeout(self.timeout)

    def set_timeout(self, timeout):
        self.timeout = timeout

class TimeoutSafeTransport(xmlrpc.client.SafeTransport):

    def __init__(self, timeout=None, *args, **kwargs):
        xmlrpc.client.SafeTransport.__init__(self, *args, **kwargs)
        self.timeout = timeout

    def make_connection(self, host):
        chost, self._extra_headers, _ = self.get_host_info(host)
        self._connection = host, TimeoutHTTPSConnection(chost)
        self._connection[1].set_timeout(self.timeout)
        return self._connection[1]

