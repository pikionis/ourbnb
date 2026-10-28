"""ORM tables of the properties context. Infrastructure only: the rules live in `domain/`.

Rows are mapped to aggregates in `adapters/repository.py`; nothing else writes these tables (the
admin sends commands). `version` serves optimistic concurrency (ADR 0016). Lockbox codes are
encrypted at rest (DOMAIN §2.3).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from kospm.shared.adapters.fields import EncryptedTextField


class BankAccountStatusChoices(models.TextChoices):
    UNVERIFIED = "unverified", _("Unverified")
    PENDING = "pending", _("Waiting for the test transfer")
    TRANSFER_SENT = "transfer_sent", _("Transfer sent, waiting for the code")
    VERIFIED = "verified", _("Verified")


class PayeeCheckChoices(models.TextChoices):
    """The bank's Verification of Payee answer when the test transfer is sent (ADR 0018)."""

    MATCH = "match", _("The name matches")
    CLOSE_MATCH = "close_match", _("The name almost matches")
    NOT_POSSIBLE = "not_possible", _("The check was not possible")
    NO_MATCH = "no_match", _("The name does not match (not sent)")


class PropertyStatusChoices(models.TextChoices):
    ONBOARDING = "onboarding", _("In progress")
    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")
    OFFBOARDED = "offboarded", _("Offboarded")


class Owner(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    name = models.CharField(_("name"), max_length=200)
    email = models.EmailField(_("email"), unique=True)
    phone = models.CharField(_("phone"), max_length=32)
    afm = models.CharField(_("tax number (AFM)"), max_length=9, unique=True)
    iban = models.CharField(_("IBAN"), max_length=34)
    bank_holder_name = models.CharField(_("account holder"), max_length=70)
    bank_payee_check = models.CharField(
        _("payee check"), max_length=16, choices=PayeeCheckChoices.choices, blank=True
    )
    bank_payee_check_name = models.CharField(
        _("name returned by the bank"), max_length=70, blank=True
    )
    bank_account_status = models.CharField(
        _("bank account"),
        max_length=16,
        choices=BankAccountStatusChoices.choices,
        default=BankAccountStatusChoices.UNVERIFIED,
    )
    bank_verification_code = models.CharField(
        _("code of the test transfer"), max_length=6, blank=True
    )
    bank_verification_failed_attempts = models.PositiveSmallIntegerField(default=0)
    show_on_website = models.BooleanField(_("shown on the website"), default=False)
    website_consent_requested = models.BooleanField(_("website consent asked"), default=False)
    created_at = models.DateTimeField(_("registered at"), auto_now_add=True)
    version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("name",)
        verbose_name = _("owner")
        verbose_name_plural = _("owners")

    def __str__(self) -> str:
        return self.name


class Property(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    owner = models.ForeignKey(
        Owner, on_delete=models.PROTECT, related_name="properties", verbose_name=_("owner")
    )
    code = models.CharField(_("code"), max_length=16, unique=True)
    name = models.CharField(_("name"), max_length=200)
    status = models.CharField(
        _("status"),
        max_length=16,
        choices=PropertyStatusChoices.choices,
        default=PropertyStatusChoices.ONBOARDING,
    )
    address = models.CharField(_("address"), max_length=300, blank=True)
    lat = models.DecimalField(_("latitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(_("longitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    default_check_in_time = models.TimeField(_("check-in time"))
    default_check_out_time = models.TimeField(_("check-out time"))
    linen_par_level = models.PositiveSmallIntegerField(_("linen sets kept on site"))
    preferred_cleaner_id = models.UUIDField(_("preferred cleaner"), null=True, blank=True)

    directions_el = models.TextField(_("directions (Greek)"), blank=True)
    directions_en = models.TextField(_("directions (English)"), blank=True)
    map_url = models.URLField(_("map link"), blank=True)
    exterior_photo = models.FileField(
        _("exterior photo"), upload_to="properties/photos/", blank=True
    )
    lockbox_photo = models.FileField(_("lockbox photo"), upload_to="properties/photos/", blank=True)
    guest_lockbox_code = EncryptedTextField(_("lockbox code for guests"), null=True, blank=True)
    cleaner_lockbox_code = EncryptedTextField(_("lockbox code for cleaners"), null=True, blank=True)
    amenities_included = models.JSONField(_("amenities included"), default=list, blank=True)
    amenities_not_included = models.JSONField(_("amenities not included"), default=list, blank=True)
    ical_feeds = models.JSONField(_("calendar feeds"), default=list, blank=True)

    contract_draft_document = models.FileField(
        _("contract to sign"), upload_to="contracts/drafts/", blank=True
    )
    contract_draft_commission_rate = models.DecimalField(
        _("commission rate of the contract to sign"),
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    contract_draft_owner_cleaning_charge = models.DecimalField(
        _("owner cleaning charge of the contract to sign (€)"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    contract_commission_rate = models.DecimalField(
        _("commission rate"), max_digits=5, decimal_places=4, null=True, blank=True
    )
    contract_owner_cleaning_charge = models.DecimalField(
        _("owner cleaning charge (€)"), max_digits=10, decimal_places=2, null=True, blank=True
    )
    contract_signed_at = models.DateTimeField(_("contract signed at"), null=True, blank=True)
    contract_document = models.FileField(_("signed contract"), upload_to="contracts/", blank=True)
    sublease_declaration_number = models.CharField(
        _("sublease declaration number"), max_length=64, blank=True
    )
    ama_number = models.CharField(_("AMA number"), max_length=64, blank=True)

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("code",)
        verbose_name = _("property")
        verbose_name_plural = _("properties")

    def __str__(self) -> str:
        return f"{self.code} {self.name}"
