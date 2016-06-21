import time

from .util.request import make_headers
from .util.url import parse_url

from .packages.six.moves.http_cookiejar import (
    DefaultCookiePolicy as PythonCookiePolicy,
    CookieJar as PythonCookieJar
)


class DefaultCookiePolicy(PythonCookiePolicy):
    """
    The default urllib3 cookie policy - similar to the Python default,
    but :param:`strict_ns_domain` is set to `DomainStrict` for security.
    """
    def __init__(self, *args, **kwargs):
        policy = PythonCookiePolicy.DomainStrict
        kwargs.setdefault('strict_ns_domain', policy)
        # Old-style class on Python 2
        PythonCookiePolicy.__init__(self, *args, **kwargs)


class CookieJar(PythonCookieJar):

    def __init__(self, policy=None):
        policy = policy or DefaultCookiePolicy()
        # Old-style class on Python 2
        PythonCookieJar.__init__(self, policy=policy)

    def add_cookie_header(self, request):
        """
        Add correct Cookie: header to Request object.
        This is copied from and slightly modified from the stdlib version.
        """
        self._cookies_lock.acquire()
        try:
            self._policy._now = self._now = int(time.time())
            cookies = self._cookies_for_request(request)
            attrs = self._cookie_attrs(cookies)
            # This is a modification; stdlib sets the entire cookie header
            # and only if it's not there already. We're less picky.
            if attrs:
                request.add_cookies(*attrs)
        finally:
            self._cookies_lock.release()
        self.clear_expired_cookies()


class CookieHandler(object):

    def __init__(self, cookie_jar=None):
        # We unfortunately have to do it this way; empty cookie jars evaluate as falsey
        if cookie_jar is not None:
            self.cookie_jar = cookie_jar
        else:
            self.cookie_jar = CookieJar()

    def apply_to(self, request):
        """
        Applies changes from the context to the supplied :class:`.request.Request`.
        """
        self.cookie_jar.add_cookie_header(request)

    def extract_from(self, response, request):
        """
        Extracts context modifications (new cookies, etc) from the response and stores them.
        """
        self.cookie_jar.extract_cookies(response, request)


class BasicAuthHandler(object):

    def __init__(self, domain=None, username=None, password=None):
        self.username = username
        self.password = password
        domain = parse_url(domain)
        self.host = domain.host
        self.scheme = domain.scheme or None

    def apply_to(self, request):
        if self.host_matches(request):
            request.headers.update(self.build_header())

    def build_header(self):
        auth_string = '{}:{}'.format(self.username or '', self.password or '')
        return make_headers(basic_auth=auth_string)

    def host_matches(self, request):
        if self.scheme is not None and self.scheme != request.type:
            return False
        else:
            return self.host == request.host