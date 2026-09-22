from django.urls import path
from . import views

app_name = "scholars"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("library/", views.library, name="library"),
    path("attribution/", views.attribution, name="attribution"),
    path("topics/<str:pk>/", views.topic, name="topic"),
    path("topics/<str:pk>/studied/", views.studied, name="studied"),
    path("progress/", views.progress, name="progress"),
    path("progress/goal/", views.goal, name="goal"),
    path("progress/students/<uuid:pk>/", views.student_progress, name="student_progress"),
    path("practice/start/", views.start, name="start"),
    path("practice/<uuid:pk>/", views.session_view, name="session"),
    path("practice/<uuid:pk>/end/", views.abandon, name="abandon"),
    path("practice/<uuid:pk>/<int:position>/reveal/", views.reveal, name="reveal"),
    path("practice/<uuid:pk>/<int:position>/answer/", views.answer, name="answer"),
    path("practice/<uuid:pk>/<int:position>/feedback/", views.feedback, name="feedback"),
    path("practice/<uuid:pk>/<int:position>/evidence/", views.evidence, name="evidence"),
    path("results/", views.history, name="history"),
    path("results/<uuid:pk>/", views.results, name="results"),
]
