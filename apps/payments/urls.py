from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("queue/", views.PaymentQueueView.as_view(), name="queue"),
    path("<int:pk>/paid/", views.RecordPaymentPaidView.as_view(), name="mark_paid"),
    path("<int:pk>/failed/", views.RecordPaymentFailedView.as_view(), name="mark_failed"),
    path("mine/", views.MyPaymentsView.as_view(), name="my_payments"),
    path("received/", views.SellerPaymentsView.as_view(), name="seller_payments"),
]
