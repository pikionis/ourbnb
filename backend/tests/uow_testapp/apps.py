from django.apps import AppConfig


class UowTestAppConfig(AppConfig):
    name = "tests.uow_testapp"
    label = "uow_testapp"
    default_auto_field = "django.db.models.BigAutoField"
