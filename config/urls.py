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
    path("control/", include("apps.auctions.control_urls", namespace="control")),
    path("listings/", include("apps.listings.urls", namespace="listings")),
    path("bids/", include("apps.bidding.urls", namespace="bidding")),
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),
    path("payments/", include("apps.payments.urls", namespace="payments")),
    path("disputes/", include("apps.disputes.urls", namespace="disputes")),
    path("reports/", include("apps.reports.urls", namespace="reports")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
