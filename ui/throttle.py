"""Cache-based failed-login throttle shared by dash and seller (no extra dependency)."""
from django.core.cache import cache

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60


def client_ip(request):
    return request.META.get('REMOTE_ADDR', 'unknown')


class LoginThrottle:
    def __init__(self, prefix, max_attempts=MAX_ATTEMPTS, window=WINDOW_SECONDS):
        self.prefix, self.max_attempts, self.window = prefix, max_attempts, window

    def _key(self, request, username):
        return f'{self.prefix}:{client_ip(request)}:{(username or "").strip().lower()}'

    def is_throttled(self, request, username):
        return cache.get(self._key(request, username), 0) >= self.max_attempts

    def record_failure(self, request, username):
        key = self._key(request, username)
        try:
            cache.add(key, 0, self.window)
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, self.window)

    def clear(self, request, username):
        cache.delete(self._key(request, username))
