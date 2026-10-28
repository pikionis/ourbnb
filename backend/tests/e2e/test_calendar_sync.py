"""Reservations end to end: from the admin's property to the reservations copy (DOMAIN §4.1)."""

import io
from typing import Any

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from kospm.reservations import models
from tests.e2e.owners import add_property_in_admin, register_owner_in_admin

pytestmark = pytest.mark.django_db

AIRBNB_URL = "https://www.airbnb.com/calendar/ical/1001.ics?s=test"


def admin_property_with_feed(admin_client: Client) -> Any:
    owner = register_owner_in_admin(admin_client)
    prop = add_property_in_admin(admin_client, owner, code="KOS-001", name="Villa Elena")
    data = {
        "owner": str(owner.pk),
        "code": prop.code,
        "name": prop.name,
        "default_check_in_time": "15:00",
        "default_check_out_time": "11:00",
        "linen_par_level": "3",
        "airbnb_ical_url": AIRBNB_URL,
        "contract_signed_at_0": "",
        "contract_signed_at_1": "",
        "version": "0",
    }
    saved = admin_client.post(reverse("admin:properties_property_change", args=[prop.pk]), data)
    assert saved.status_code == 302, saved.content.decode()[:2000]
    return prop


class TestPropertyCopy:
    def test_the_admins_property_reaches_the_reservations_context(
        self, admin_client: Client
    ) -> None:
        prop = admin_property_with_feed(admin_client)

        copy = models.PropertyCalendar.objects.get(property_id=prop.pk)
        assert (copy.code, copy.name, copy.active) == ("KOS-001", "Villa Elena", False)
        assert list(copy.feeds.values_list("channel", "url")) == [("airbnb", AIRBNB_URL)]

    def test_properties_from_before_are_announced_by_a_command(self, admin_client: Client) -> None:
        prop = admin_property_with_feed(admin_client)
        models.CalendarFeed.objects.all().delete()
        models.PropertyCalendar.objects.all().delete()  # as before the reservations context

        call_command("announce_calendar_settings", stdout=io.StringIO())
        call_command("announce_calendar_settings", stdout=io.StringIO())  # again: no harm

        copy = models.PropertyCalendar.objects.get(property_id=prop.pk)
        assert list(copy.feeds.values_list("url", flat=True)) == [AIRBNB_URL]
