from django.urls import path
from . import views

app_name = "auctions"

urlpatterns = [
    path("", views.browse, name="browse"),
    path("<int:pk>/", views.detail, name="detail"),
]
