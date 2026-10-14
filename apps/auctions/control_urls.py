from django.urls import path

from . import control

app_name = "control"

urlpatterns = [
    path("", control.ControlDashboardView.as_view(), name="dashboard"),
    path("sweep/", control.SweepView.as_view(), name="sweep"),
    path("<int:pk>/", control.AuctionControlView.as_view(), name="auction"),
    path("<int:pk>/start/", control.StartNowView.as_view(), name="start"),
    path("<int:pk>/reschedule/", control.RescheduleView.as_view(), name="reschedule"),
    path("<int:pk>/pause/", control.PauseView.as_view(), name="pause"),
    path("<int:pk>/resume/", control.ResumeView.as_view(), name="resume"),
    path("<int:pk>/cancel/", control.CancelView.as_view(), name="cancel"),
    path("<int:pk>/end/", control.EndNowView.as_view(), name="end"),
]
