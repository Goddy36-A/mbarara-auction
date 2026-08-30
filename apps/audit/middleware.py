import threading

_local = threading.local()


def get_current_user():
    """
    Lets service-layer code (which doesn't have direct access to the
    request) attribute an AuditLog entry to the acting user without every
    service function needing an explicit `actor` parameter threaded through.
    Prefer passing `actor` explicitly where practical; this is a fallback.
    """
    return getattr(_local, "user", None)


class AuditContextMiddleware:
    """Stashes the current request's user in thread-local storage for the
    duration of the request so background-triggered-by-request audit writes
    can find out who was acting, without coupling the service layer to
    Django's request object."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.user = getattr(request, "user", None)
        try:
            response = self.get_response(request)
        finally:
            _local.user = None
        return response
