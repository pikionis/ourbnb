# Phase 2b (ADR 0018): the bank account holder's name and the bank's payee check.

from django.db import migrations, models


def holder_name_from_owner_name(apps, schema_editor):
    """Owners registered before Phase 2b get their own name as the account holder's name; the
    admin corrects it to the bank's spelling when needed (a new name is verified again)."""
    Owner = apps.get_model("properties", "Owner")
    for owner in Owner.objects.filter(bank_holder_name=""):
        owner.bank_holder_name = " ".join(owner.name.split())[:70]
        owner.save(update_fields=["bank_holder_name"])


class Migration(migrations.Migration):
    dependencies = [
        ("properties", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="owner",
            name="bank_holder_name",
            field=models.CharField(default="", max_length=70, verbose_name="account holder"),
            preserve_default=False,
        ),
        migrations.RunPython(holder_name_from_owner_name, migrations.RunPython.noop),
        migrations.AddField(
            model_name="owner",
            name="bank_payee_check",
            field=models.CharField(
                blank=True,
                choices=[
                    ("match", "The name matches"),
                    ("close_match", "The name almost matches"),
                    ("not_possible", "The check was not possible"),
                    ("no_match", "The name does not match (not sent)"),
                ],
                max_length=16,
                verbose_name="payee check",
            ),
        ),
        migrations.AddField(
            model_name="owner",
            name="bank_payee_check_name",
            field=models.CharField(
                blank=True, max_length=70, verbose_name="name returned by the bank"
            ),
        ),
        migrations.AlterField(
            model_name="owner",
            name="bank_account_status",
            field=models.CharField(
                choices=[
                    ("unverified", "Unverified"),
                    ("pending", "Waiting for the test transfer"),
                    ("transfer_sent", "Transfer sent, waiting for the code"),
                    ("verified", "Verified"),
                ],
                default="unverified",
                max_length=16,
                verbose_name="bank account",
            ),
        ),
    ]
