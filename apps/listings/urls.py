from django.urls import path
from . import views

app_name = "listings"

urlpatterns = [
    path("mine/", views.MyListingsView.as_view(), name="my_listings"),
    path("new/", views.AuctionCreateView.as_view(), name="create"),
    path("<int:pk>/edit/", views.AuctionEditView.as_view(), name="edit"),
    path("<int:pk>/submit/", views.SubmitListingView.as_view(), name="submit"),
    path("approval-queue/", views.ApprovalQueueView.as_view(), name="approval_queue"),
    path("<int:pk>/approve/", views.ApproveListingView.as_view(), name="approve"),
    path("<int:pk>/reject/", views.RejectListingView.as_view(), name="reject"),
]
