"""
ASGI config for the Mbarara Online Auction System.

Plain ASGI for now (Section 54 of the specification notes Django Channels /
WebSockets as a future enhancement, not required for the MVP's polling-based
bid updates).
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_asgi_application()
