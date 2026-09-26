from functools import wraps
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST, require_http_methods
from .forms import ChangePasswordForm, CreateStudentForm, LoginForm, TemporaryPasswordForm, UsernameForm
from .models import User
from .services import consume_login_attempt, create_student, reset_student, set_student_active


class ThrottledLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if not consume_login_attempt(request.POST.get("username", "").strip().lower()[:32], request.META.get("REMOTE_ADDR", "")):
            form = self.get_form_class()(request)
            form.errors  # Initialize errors without attempting authentication.
            form.cleaned_data = {}
            form.add_error(None, "Too many sign-in attempts. Wait 15 minutes, then try again.")
            response = self.render_to_response(self.get_context_data(form=form))
            response.status_code = 429
            response["Retry-After"] = "900"
            return response
        return super().post(request, *args, **kwargs)


def administrator_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_admin:
            return HttpResponseForbidden("Administrator access required.")
        return view(request, *args, **kwargs)
    return wrapped


@login_required
@require_http_methods(["GET", "POST"])
def account(request):
    # Explicit field allowlist; IDs and role flags in POST cannot alter privileges.
    form = UsernameForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                User.objects.filter(pk=request.user.pk).update(username=form.cleaned_data["username"])
        except IntegrityError:
            form.add_error("username", "This username is already in use.")
        else:
            messages.success(request, "Username updated.")
            return redirect("account")
    from scholars.study_views import interests_form
    return render(request, "accounts/account.html", {"form": form, "interests_form": interests_form(request.user)})


@sensitive_post_parameters()
@login_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        form = ChangePasswordForm(user, request.POST or None)
        if request.method == "POST" and form.is_valid():
            user = form.save(commit=False)
            user.must_change_password = False
            user.save(update_fields=["password", "must_change_password"])
            update_session_auth_hash(request, user)
            messages.success(request, "Password updated.")
            return redirect("scholars:dashboard")
    return render(request, "accounts/password_change.html", {"form": form})


@sensitive_post_parameters()
@administrator_required
@require_http_methods(["GET", "POST"])
def students(request):
    form = CreateStudentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_student(**form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        except IntegrityError:
            form.add_error(None, "The username is already in use.")
        else:
            messages.success(request, "Student created. Share their username and temporary password privately.")
            return redirect("students")
    return render(request, "accounts/students.html", {"form": form, "students": Paginator(
        User.objects.filter(is_admin=False).order_by("username"), 50).get_page(request.GET.get("page"))})


@sensitive_post_parameters()
@administrator_required
@require_http_methods(["GET", "POST"])
def student(request, pk):
    user = get_object_or_404(User, pk=pk, is_admin=False)
    form = TemporaryPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            reset_student(user.pk, form.cleaned_data["password"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Password reset. Existing sessions are invalid; a new password is required at next login.")
            return redirect("student", pk=pk)
    return render(request, "accounts/student.html", {"student": user, "form": form,
        "sessions": Paginator(user.practice_sessions.order_by("-started_at"), 25).get_page(request.GET.get("page"))})


@administrator_required
@require_POST
def student_status(request, pk):
    user = get_object_or_404(User, pk=pk, is_admin=False)
    set_student_active(user.pk, request.POST.get("active") == "yes")
    messages.success(request, "Account status updated; previous sessions were invalidated.")
    return redirect("student", pk=pk)


@administrator_required
@require_http_methods(["GET", "POST"])
def student_delete(request, pk):
    user = get_object_or_404(User, pk=pk, is_admin=False)
    if request.method == "POST" and request.POST.get("confirm") == str(user.pk):
        user.delete()
        messages.success(request, "Student account and learning history deleted.")
        return redirect("students")
    return render(request, "accounts/delete.html", {"student": user})
