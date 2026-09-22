from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from django.views.generic import TemplateView
from accounts import views

urlpatterns = [
    path("", login_required(TemplateView.as_view(template_name="home.html")), name="home"),
    path("login/", views.ThrottledLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
    path("account/password/", views.password_change, name="password_change"),
    path("admin/", views.students, name="students"),
    path("admin/students/<uuid:pk>/", views.student, name="student"),
    path("admin/students/<uuid:pk>/status/", views.student_status, name="student_status"),
    path("admin/students/<uuid:pk>/delete/", views.student_delete, name="student_delete"),
    path("scholars-bowl/", include("scholars.urls")),
]
