"""Every URL in the dash URLconf must refuse anyone who is not an active superuser."""
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from .base import DashTestCase

PUBLIC = {'/login/'}


def _walk(patterns, prefix=''):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def sample_path(route):
    """Turn a route like 'sellers/<int:pk>/<slug:action>/' into a concrete path."""
    out = route
    for conv, value in (('<int:pk>', '1'), ('<slug:action>', 'approve'), ('<slug:direction>', 'up')):
        out = out.replace(conv, value)
    return '/' + out.lstrip('^')


class UrlSweepTests(DashTestCase):
    def paths(self):
        found = [sample_path(r) for r, _ in _walk(get_resolver('dayloop.urls_dash').url_patterns)]
        return [p for p in found if p not in PUBLIC and '<' not in p]

    def test_sweep_discovers_the_whole_surface(self):
        paths = self.paths()
        self.assertGreater(len(paths), 40)
        for expected in ('/', '/sellers/', '/products/', '/orders/', '/customers/', '/analytics/',
                         '/products/categories/', '/search/', '/api/sales/', '/admin/'):
            self.assertIn(expected, paths)

    def test_every_url_is_closed_to_non_superusers(self):
        actors = {'anonymous': None, 'customer': self.customer, 'seller': self.seller_user,
                  'staff': self.staff, 'inactive superuser': self.inactive_super}
        for name, user in actors.items():
            self.client.logout()
            if user:
                self.login_as(user)
            for path in self.paths():
                for method in ('get', 'post'):
                    for extra in ({}, {'HTTP_HX_REQUEST': 'true'}, {'HTTP_ACCEPT': 'application/json'}):
                        r = getattr(self.client, method)(path, {}, **extra)
                        label = f'{name}: {method.upper()} {path} {extra}'
                        self.assertIn(r.status_code, (302, 403), label)
                        if r.status_code == 302:
                            self.assertTrue(r['Location'].startswith('/login/'), label)
                            self.assertFalse(extra, f'machine requests must get 403, not a redirect: {label}')
                self.client.logout()
                if user:
                    self.login_as(user)   # a non-superuser session is ended on first contact; log back in

    def test_login_page_is_the_only_public_dash_page(self):
        self.assertEqual(self.client.get('/login/').status_code, 200)
