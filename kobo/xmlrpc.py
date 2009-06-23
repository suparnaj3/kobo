# -*- coding: utf-8 -*-


import cookielib
import httplib
import os
import socket
import sys
import time
import urllib2
import xmlrpclib


__all__ = (
    "CookieTransport",
    "SafeCookieTransport",
    "retry_request_decorator"
)


class CookieResponse(object):
    """Fake response class for cookie extraction."""

    __slots__ = (
        "headers",
    )


    def __init__(self, headers):
        self.headers = headers


    def info(self):
        """Pass response headers to cookie jar."""
        return self.headers


class CookieTransport(xmlrpclib.Transport):
    """Cookie enabled XML-RPC transport."""

    _use_datetime = False # fix for python 2.5
    scheme = "http"


    def __init__(self, cookiejar=None):
        self.cookiejar = cookiejar or cookielib.CookieJar()

        if hasattr(self.cookiejar, "load"):
            if not os.path.exists(self.cookiejar.filename):
                if hasattr(self.cookiejar, "save"):
                    self.cookiejar.save(self.cookiejar.filename)
            self.cookiejar.load(self.cookiejar.filename)


    def send_cookies(self, connection, cookie_request):
        """Add cookies to the header."""
        self.cookiejar.add_cookie_header(cookie_request)

        for header, value in cookie_request.header_items():
            if header.startswith("Cookie"):
                connection.putheader(header, value)


    def send_host(self, connection, host, headers=None):
        """Send host information and extra headers."""
        host, extra_headers, x509 = self.get_host_info(host)
        connection.putheader("Host", host)

        if extra_headers is None:
            extra_headers = {}

        if headers:
            extra_headers.update(headers)

        for key, value in extra_headers.iteritems():
            connection.putheader(key, value)


    def request(self, host, handler, request_body, verbose=0):
        """Send a HTTP request."""
        h = self.make_connection(host)
        if verbose:
            h.set_debuglevel(1)

        request_url = "%s://%s/" % (self.scheme, host)
        cookie_request  = urllib2.Request(request_url)

        self.send_request(h, handler, request_body)
        self.send_host(h, host, {})
        self.send_cookies(h, cookie_request)
        self.send_user_agent(h)
        self.send_content(h, request_body)

        errcode, errmsg, headers = h.getreply()
        if errcode / 100 == 2:
            cookie_response = CookieResponse(headers)
            self.cookiejar.extract_cookies(cookie_response, cookie_request)
            if hasattr(self.cookiejar, "save"):
                self.cookiejar.save(self.cookiejar.filename)

        elif errcode != 200:
            raise xmlrpclib.ProtocolError(
                host + handler,
                errcode, errmsg,
                headers
                )

        self.verbose = verbose

        try:
            sock = h._conn.sock
        except AttributeError:
            sock = None

        return self._parse_response(h.getfile(), sock)


class SafeCookieTransport(CookieTransport):
    """Cookie enabled XML-RPC transport over HTTPS."""

    scheme = "https"

    def make_connection(self, host):
        """Create a HTTPS connection object."""
        host, extra_headers, x509 = self.get_host_info(host)
        try:
            HTTPS = httplib.HTTPS
        except AttributeError:
            raise NotImplementedError("your version of httplib doesn't support HTTPS")
        else:
            return HTTPS(host, None, **(x509 or {}))


def retry_request_decorator(transport_class):
    """Use this class decorator on a Transport to retry requests which failed on socket errors."""
    class RetryTransportClass(transport_class):
        def __init__(self, retry_count=5, retry_timeout=30, *args, **kwargs):
            transport_class.__init__(self, *args, **kwargs)
            self.retry_count = retry_count
            self.retry_timeout = retry_timeout

        def request(self, *args, **kwargs):
            if self.retry_count == 0:
                return transport_class.request(self, *args, **kwargs)

            for i in xrange(self.retry_count+1):
                try:
                    result = transport_class.request(self, *args, **kwargs)
                    return result
                except KeyboardInterrupt:
                    raise
                except (socket.error, socket.herror, socket.gaierror, socket.timeout), ex:
                    if i >= self.retry_count:
                        raise
                    print >> sys.stderr, "Connection failed, retrying. Error was: %s" % ex
                    time.sleep(self.retry_timeout)

    RetryTransportClass.__name__ = transport_class.__name__
    RetryTransportClass.__doc__ = transport_class.__name__
    return RetryTransportClass