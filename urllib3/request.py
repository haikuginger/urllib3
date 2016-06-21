from __future__ import absolute_import

import logging

from .filepost import encode_multipart_formdata, iter_field_objects
from .exceptions import MaxRetryError
from .util.url import parse_url

from .packages.six.moves.urllib.parse import urlencode
from .packages.six.moves.urllib.parse import urljoin

__all__ = ['RequestMethods', 'Request']

log = logging.getLogger(__name__)


class Request(object):
    """
    Implements some of the interface of the stdlib Request object, but does it
    in our own way, so we're free from the constrains of urllib/urllib2
    """
    def __init__(self, method, url, headers=None, body=None, redirected_by=None):
        self.method = method
        self.url = url
        self.headers = headers or dict()
        self.body = body
        self.redirect_source = redirected_by
        self.kwargs = {}
        if self.has_header('Cookie'):
            self._cookies = self.get_header('Cookie').split('; ')
        else:
            self._cookies = []

    def add_cookies(self, *cookies):
        """
        Add cookies to the request, updating the Cookie header with each one.
        """
        for each in cookies:
            if each not in self._cookies:
                self._cookies.append(each)
        self.headers['Cookie'] = '; '.join(self._cookies)

    def get_full_url(self):
        """
        Get the request's full URL
        """
        return self.full_url

    @property
    def full_url(self):
        return self.url

    @property
    def host(self):
        return parse_url(self.url).host

    @property
    def type(self):
        return parse_url(self.url).scheme

    @property
    def unverifiable(self):
        return self.is_unverifiable()

    @property
    def origin_req_host(self):
        return parse_url(self.redirect_source).host or self.host

    def is_unverifiable(self):
        """
        This determines if the request is "verifiable" for cookie handling
        purposes - generally, a request is "verifiable" if the user has an
        opportunity to change the URL pre-request. In the context of urllib3,
        this is generally not the case only if a redirect happened.
        """
        if self.redirect_source and self.redirect_source != self.url:
            return True
        else:
            return False

    def has_header(self, header):
        return header in self.headers

    def get_header(self, header, default=None):
        return self.headers.get(header, default)

    def get_kwargs(self):
        """
        Gives us a set of keywords we can **expand into urlopen
        """
        kw = {
            'method': self.method,
            'url': self.url,
            'headers': self.headers,
            'body': self.body
        }
        kw.update(self.kwargs)
        return kw


class RequestMethods(object):
    """
    Convenience mixin for classes who implement a :meth:`urlopen` method, such
    as :class:`~urllib3.connectionpool.HTTPConnectionPool` and
    :class:`~urllib3.poolmanager.PoolManager`.

    Provides behavior for making common types of HTTP request methods and
    decides which type of request field encoding to use.

    Specifically,

    :meth:`.request_encode_url` is for sending requests whose fields are
    encoded in the URL (such as GET, HEAD, DELETE).

    :meth:`.request_encode_body` is for sending requests whose fields are
    encoded in the *body* of the request using multipart or www-form-urlencoded
    (such as for POST, PUT, PATCH).

    :meth:`.request` is for making any kind of request, it will look up the
    appropriate encoding format and use one of the above two methods to make
    the request.

    Initializer parameters:

    :param headers:
        Headers to include with all requests, unless other headers are given
        explicitly.
    """

    _encode_url_methods = set(['DELETE', 'GET', 'HEAD', 'OPTIONS'])

    def __init__(self, headers=None):
        self.headers = headers or {}

    def urlopen(self, method, url, body=None, headers=None,
                encode_multipart=True, multipart_boundary=None,
                **kw):  # Abstract
        raise NotImplemented("Classes extending RequestMethods must implement "
                             "their own ``urlopen`` method.")

    def request(self, method, url, fields=None, headers=None, body=None, **urlopen_kw):
        """
        Make a request using :meth:`urlopen` with the appropriate encoding of
        ``fields`` based on the ``method`` used.

        This is a convenience method that requires the least amount of manual
        effort. It can be used in most situations, while still having the
        option to drop down to more specific methods when necessary, such as
        :meth:`request_encode_url`, :meth:`request_encode_body`,
        or even the lowest level :meth:`urlopen`.
        """
        pops = [
            'encode_multipart',
            'multipart_boundary',
            'form_fields',
            'url_params',
            'fields'
        ]
        method = method.upper()
        if headers is None:
            headers = self.headers.copy()

        url = self.encode_url(method, url, fields=fields, **urlopen_kw)

        headers, body = self.encode_body_and_headers(method, body=body, fields=fields,
                                                     headers=headers, **urlopen_kw)
        for each in pops:
            urlopen_kw.pop(each, None)

        return self.urlopen(method, url, headers=headers, body=body, **urlopen_kw)

    def encode_body_and_headers(self, method, body=None, fields=None,
                                form_fields=None, headers=None, encode_multipart=True,
                                multipart_boundary=None, **kw):
        """
        Encode and return a request body and headers to match
        """
        headers = headers or dict()
        form_fields = form_fields or []
        fields = fields or []

        if fields or form_fields:

            content_type = None

            if body is not None:
                raise TypeError(
                    "request got values for both 'fields' and 'body', can only specify one.")

            if encode_multipart and method not in self._encode_url_methods:
                fields = iter_field_objects(fields, form_fields)
                body, content_type = encode_multipart_formdata(fields, boundary=multipart_boundary)
            elif method not in self._encode_url_methods:
                body = ''
                if fields:
                    body += urlencode(fields)
                    if form_fields:
                        body += '&'
                if form_fields:
                    body += urlencode(form_fields)
                content_type = 'application/x-www-form-urlencoded'

            if content_type:
                headers.update({'Content-Type': content_type})

        return headers, body

    def encode_url(self, method, url, fields=None, url_params=None, **kw):
        """
        Encode relevant fields into the URL; we have to do them separately,
        as they might be coming in as different object types.
        """
        url_params = url_params or []
        fields = fields or []
        querystring = ''
        if method in self._encode_url_methods and fields:
            querystring += urlencode(fields)
            if querystring and url_params:
                querystring += '&'

        if url_params:
            querystring += urlencode(url_params)

        if querystring:
            url += '?' + querystring

        return url

    def redirect(self, response, method, retries, **kwargs):
        """
        Abstracts the redirect process to be used from any :class:`RequestMethods` object
        """
        url = kwargs.pop('url', '')
        redirect_location = urljoin(url, response.get_redirect_location())
        method = retries.redirect_method(method, response.status)
        try:
            pool = kwargs.pop('pool', self)
            retries = retries.increment(method, url, response=response, _pool=pool)
        except MaxRetryError:
            if retries.raise_on_redirect:
                # Release the connection for this response, since we're not
                # returning it to be released manually.
                response.release_conn()
                raise
            return response

        log.info("Redirecting %s -> %s", url, redirect_location)
        return self.urlopen(method=method, url=redirect_location, retries=retries, **kwargs)
