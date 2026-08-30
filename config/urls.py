"""
config URL Configuration
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls", namespace="core")),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("auctions/", include("apps.auctions.urls", namespace="auctions")),
    path("listings/", include("apps.listings.urls", namespace="listings")),
    path("bids/", include("apps.bidding.urls", namespace="bidding")),
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),
    path("payments/", include("apps.payments.urls", namespace="payments")),
    # disputes/reports/audit URLs are wired in as those apps are
    # built out (Phases 9-11).
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
