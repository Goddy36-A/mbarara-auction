from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.ReportsDashboardView.as_view(), name="dashboard"),
    path("auctions.csv", views.AuctionsCsvView.as_view(), name="auctions_csv"),
    path("payments.csv", views.PaymentsCsvView.as_view(), name="payments_csv"),
]
