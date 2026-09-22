from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from .models import User, username_validator


class LoginForm(AuthenticationForm):
    username = forms.CharField(max_length=32, widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}))
    password = forms.CharField(max_length=1024, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def clean_username(self):
        return self.cleaned_data["username"].lower()


class UsernameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]


class ChangePasswordForm(PasswordChangeForm):
    def clean_new_password1(self):
        value = self.cleaned_data["new_password1"]
        if len(value) > 1024:
            raise forms.ValidationError("Use no more than 1,024 characters.")
        if self.user.check_password(value):
            raise forms.ValidationError("Choose a password different from your current password.")
        return value


class TemporaryPasswordForm(forms.Form):
    password = forms.CharField(label="Temporary password", min_length=12, max_length=1024, strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                               help_text="Supply a unique temporary password and give it to the student outside this site.")

    def clean_password(self):
        value = self.cleaned_data["password"]
        validate_password(value)
        return value


class CreateStudentForm(TemporaryPasswordForm):
    username = forms.CharField(max_length=32, validators=[username_validator])
    field_order = ["username", "password"]

    def clean_username(self):
        value = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("This username is already in use.")
        return value
