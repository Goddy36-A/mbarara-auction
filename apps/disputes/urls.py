from django.urls import path

from . import views

app_name = "disputes"

urlpatterns = [
    path("mine/", views.MyDisputesView.as_view(), name="mine"),
    path("queue/", views.DisputeQueueView.as_view(), name="queue"),
    path("new/<int:auction_id>/", views.DisputeCreateView.as_view(), name="create"),
    path("<int:pk>/", views.DisputeDetailView.as_view(), name="detail"),
    path("<int:pk>/review/", views.TakeDisputeView.as_view(), name="take"),
    path("<int:pk>/resolve/", views.ResolveDisputeView.as_view(), name="resolve"),
]
