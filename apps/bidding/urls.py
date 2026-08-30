from django.urls import path
from . import views

app_name = "bidding"

urlpatterns = [
    path("<int:auction_id>/place/", views.PlaceBidView.as_view(), name="place_bid"),
    path("mine/", views.MyBidsView.as_view(), name="my_bids"),
]
