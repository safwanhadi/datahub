from django.urls import path

from . import views


app_name = "myaccount"

urlpatterns = [
    path("simadu/launch/", views.simadu_launch, name="simadu-launch"),
    path("simadu/login/", views.simadu_login, name="simadu-login"),
    path("callback/", views.simadu_callback, name="simadu-callback"),
    path("", views.account_detail, name="detail"),
]
