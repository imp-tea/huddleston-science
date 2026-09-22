from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from .models import LoginBucket, User
from .services import create_student, reset_student, set_student_active

ADMIN_PASSWORD = "Forest-anchor-test-784!"
TEMP_PASSWORD = "Orbit-silver-test-928!"
NEW_PASSWORD = "Cedar-river-test-462!"


class AccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("teacher", ADMIN_PASSWORD)
        cls.student = create_student("student-one", TEMP_PASSWORD)
        cls.other = User.objects.create_user("student-two", NEW_PASSWORD, must_change_password=False)

    def test_model_omits_identity_and_secondary_roles(self):
        names = {field.name for field in get_user_model()._meta.fields}
        self.assertFalse(names & {"email", "first_name", "last_name", "date_of_birth", "is_staff", "is_superuser"})
        self.assertNotEqual(self.student.password, TEMP_PASSWORD)
        self.assertTrue(self.student.check_password(TEMP_PASSWORD))

    def test_no_registration_or_anonymous_creation(self):
        for path in ["/register/", "/signup/", "/accounts/register/"]:
            self.assertEqual(self.client.post(path, {}).status_code, 404)
        response = self.client.post(reverse("students"), {"username": "intruder", "password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="intruder").exists())

    def test_single_admin_database_constraint_bypasses_model_validation(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(username="teacher-two", is_admin=True)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.other.pk).update(is_admin=True)
        self.assertEqual(User.objects.filter(is_admin=True).count(), 1)

    def test_admin_cannot_be_removed_demoted_or_disabled_in_database(self):
        for action in [lambda: User.objects.filter(pk=self.admin.pk).delete(),
                       lambda: User.objects.filter(pk=self.admin.pk).update(is_admin=False),
                       lambda: User.objects.filter(pk=self.admin.pk).update(is_active=False)]:
            with self.assertRaises(DatabaseError), transaction.atomic():
                action()
        self.assertTrue(User.objects.get(pk=self.admin.pk).is_admin)

    def test_first_login_gates_every_private_route_and_post(self):
        self.client.login(username=self.student.username, password=TEMP_PASSWORD)
        for route in ["home", "account", "students", "scholars:dashboard", "scholars:history", "scholars:start"]:
            for method in [self.client.get, self.client.post]:
                response = method(reverse(route))
                self.assertRedirects(response, reverse("password_change"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)

    def test_temporary_password_cannot_be_reused_as_permanent(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("password_change"), {"old_password": TEMP_PASSWORD,
            "new_password1": TEMP_PASSWORD, "new_password2": TEMP_PASSWORD})
        self.assertContains(response, "different from your current password")
        self.student.refresh_from_db()
        self.assertTrue(self.student.must_change_password)

    def test_password_change_requires_old_password_and_persists(self):
        self.client.force_login(self.student)
        values = {"old_password": "wrong", "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        self.assertEqual(self.client.post(reverse("password_change"), values).status_code, 200)
        values["old_password"] = TEMP_PASSWORD
        self.assertRedirects(self.client.post(reverse("password_change"), values), reverse("scholars:dashboard"))
        self.student.refresh_from_db()
        self.assertFalse(self.student.must_change_password)
        self.assertTrue(self.student.check_password(NEW_PASSWORD))

    def test_students_cannot_administer_or_promote_themselves(self):
        self.client.force_login(self.other)
        paths = [reverse("students"), reverse("student", args=[self.student.pk]),
                 reverse("student_status", args=[self.student.pk]), reverse("student_delete", args=[self.student.pk])]
        for path in paths:
            self.assertEqual(self.client.post(path, {"password": NEW_PASSWORD, "active": "no"}).status_code, 403)
        self.client.post(reverse("account"), {"username": "changed-name", "is_admin": "true", "id": self.admin.pk,
                                             "is_staff": "true", "must_change_password": "false"})
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_admin)
        self.assertEqual(self.other.username, "changed-name")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.username, "teacher")

    def test_admin_creation_ignores_role_injection_and_requires_unique_temporary_password(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("students"), {"username": "created-student", "password": NEW_PASSWORD,
                                                           "is_admin": "true", "must_change_password": "false"})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="created-student")
        self.assertFalse(user.is_admin)
        self.assertTrue(user.must_change_password)
        response = self.client.post(reverse("students"), {"username": "another-student", "password": NEW_PASSWORD})
        self.assertContains(response, "already been issued")
        self.assertFalse(User.objects.filter(username="another-student").exists())
        self.assertNotContains(response, NEW_PASSWORD)

    def test_username_collision_and_format(self):
        self.client.force_login(self.other)
        for username in [self.student.username, "TEACHER", "<script>", "a"]:
            response = self.client.post(reverse("account"), {"username": username})
            self.assertEqual(response.status_code, 200)
            self.other.refresh_from_db()
            self.assertEqual(self.other.username, "student-two")

    def test_reset_invalidates_all_sessions_and_forces_change(self):
        first, second = Client(), Client()
        first.force_login(self.other)
        second.force_login(self.other)
        reset_student(self.other.pk, "Temporary-reset-586!")
        for browser in [first, second]:
            self.assertRedirects(browser.get(reverse("account")), "/login/?next=/account/", fetch_redirect_response=False)
        self.assertFalse(first.login(username=self.other.username, password=NEW_PASSWORD))
        self.assertTrue(first.login(username=self.other.username, password="Temporary-reset-586!"))
        self.assertRedirects(first.get(reverse("scholars:history")), reverse("password_change"), fetch_redirect_response=False)

    def test_disable_then_enable_never_revives_an_old_session(self):
        self.client.force_login(self.other)
        set_student_active(self.other.pk, False)
        self.assertFalse(Client().login(username=self.other.username, password=NEW_PASSWORD))
        set_student_active(self.other.pk, True)
        self.assertEqual(self.client.get(reverse("account")).status_code, 302)
        self.assertTrue(Client().login(username=self.other.username, password=NEW_PASSWORD))

    def test_own_password_change_signs_out_other_devices(self):
        first, second = Client(), Client()
        first.force_login(self.other)
        second.force_login(self.other)
        first.post(reverse("password_change"), {"old_password": NEW_PASSWORD,
            "new_password1": "Different-password-555!", "new_password2": "Different-password-555!"})
        self.assertEqual(first.get(reverse("account")).status_code, 200)
        self.assertEqual(second.get(reverse("account")).status_code, 302)

    def test_csrf_and_logout_method(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(reverse("login"), {"username": "teacher", "password": ADMIN_PASSWORD}).status_code, 403)
        browser.force_login(self.admin)
        for route in ["students", "account", "password_change", "logout", "scholars:start"]:
            self.assertEqual(browser.post(reverse(route), {}).status_code, 403)
        self.assertEqual(browser.get(reverse("logout")).status_code, 405)

    @override_settings(LOGIN_ACCOUNT_LIMIT=2, LOGIN_NETWORK_LIMIT=20)
    def test_login_throttle_shared_across_browsers_and_case_variants(self):
        for name in [" TEACHER ", "teacher"]:
            self.assertEqual(Client().post(reverse("login"), {"username": name, "password": "wrong"}).status_code, 200)
        response = Client().post(reverse("login"), {"username": "teacher", "password": ADMIN_PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "900")
        self.assertNotIn("teacher", str(list(LoginBucket.objects.values())))

    @override_settings(LOGIN_ACCOUNT_LIMIT=20, LOGIN_NETWORK_LIMIT=2)
    def test_network_throttle_covers_username_spraying(self):
        for name in ["nobody-one", "nobody-two"]:
            Client().post(reverse("login"), {"username": name, "password": "wrong"})
        self.assertEqual(Client().post(reverse("login"), {"username": "nobody-three", "password": "wrong"}).status_code, 429)

    def test_bootstrap_refuses_existing_admin_and_recovery_keeps_identity(self):
        with self.assertRaises(CommandError):
            call_command("bootstrap_admin", "new-admin", stdout=StringIO())
        with patch("accounts.management.commands.recover_admin.getpass", return_value=NEW_PASSWORD):
            call_command("recover_admin", stdout=StringIO())
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(NEW_PASSWORD))
        self.assertEqual(User.objects.filter(is_admin=True).count(), 1)

    def test_admin_can_inspect_disable_reset_and_delete_student(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("student", args=[self.other.pk])).status_code, 200)
        self.client.post(reverse("student_status", args=[self.other.pk]), {"active": "no"})
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_active)
        self.client.post(reverse("student", args=[self.other.pk]), {"password": "Admin-reset-credential-12"})
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_password("Admin-reset-credential-12"))
        self.client.post(reverse("student_delete", args=[self.other.pk]), {"confirm": str(self.other.pk)})
        self.assertFalse(User.objects.filter(pk=self.other.pk).exists())
        self.assertEqual(self.client.post(reverse("student_delete", args=[self.admin.pk]), {"confirm": str(self.admin.pk)}).status_code, 404)

    def test_private_responses_prevent_browser_cache(self):
        self.client.force_login(self.other)
        self.assertIn("no-store", self.client.get(reverse("account"))["Cache-Control"])

    def test_class_of_32_can_sign_in_twice_on_one_school_network(self):
        for number in range(32):
            user = User.objects.create_user(f"classmate-{number}", NEW_PASSWORD, must_change_password=False)
            for _ in range(2):
                response = Client().post(reverse("login"), {"username": user.username, "password": NEW_PASSWORD})
                self.assertEqual(response.status_code, 302)


class BootstrapTests(TestCase):
    def test_bootstrap_prompts_and_creates_exactly_one_administrator(self):
        with patch("accounts.management.commands.bootstrap_admin.getpass", return_value=ADMIN_PASSWORD):
            call_command("bootstrap_admin", "class-admin", stdout=StringIO())
        user = User.objects.get()
        self.assertTrue(user.is_admin)
        self.assertFalse(user.must_change_password)
        self.assertTrue(user.check_password(ADMIN_PASSWORD))
