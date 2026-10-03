from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from phonenumbers import timezone as pn_timezone

from app.db import utcnow


def aware(dt: datetime | None) -> datetime | None:
    """Treat naive datetimes as UTC (SQLite drops tzinfo)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_now(tz_name: str | None) -> datetime:
    return utcnow().astimezone(zone(tz_name))


def normalize_phone(raw: str) -> str:
    """WhatsApp sends digits without '+'. Store E.164."""
    raw = raw.strip()
    if not raw.startswith("+"):
        raw = "+" + raw
    try:
        num = phonenumbers.parse(raw, None)
        return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        return raw


# phonenumbers still returns a few pre-rename IANA names
LEGACY_ZONES = {
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon",
    "Europe/Kiev": "Europe/Kyiv",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
}


def guess_timezone(phone_e164: str) -> str:
    """Best guess from the phone number's country; the user can change it in chat."""
    try:
        num = phonenumbers.parse(phone_e164, None)
        zones = pn_timezone.time_zones_for_number(num)
        if not zones or zones[0] == "Etc/Unknown":
            # Unallocated or unusual ranges: fall back to the country's typical zone.
            region = phonenumbers.region_code_for_country_code(num.country_code)
            example = phonenumbers.example_number(region) if region else None
            zones = pn_timezone.time_zones_for_number(example) if example else ()
        if len(zones) > 1:
            # Several candidates (e.g. UK mobiles: Guernsey, Isle of Man, Jersey, London):
            # prefer the zone of the country's typical landline.
            region = phonenumbers.region_code_for_country_code(num.country_code)  # main country, e.g. GB not GG
            example = phonenumbers.example_number(region) if region else None
            main = pn_timezone.time_zones_for_number(example) if example else ()
            if main and main[0] in zones:
                zones = (main[0],)
        if zones and zones[0] != "Etc/Unknown":
            return LEGACY_ZONES.get(zones[0], zones[0])
    except phonenumbers.NumberParseException:
        pass
    return "UTC"


def human_when(dt: datetime | None, tz_name: str | None) -> str:
    if dt is None:
        return "no date"
    local = aware(dt).astimezone(zone(tz_name))
    now = local_now(tz_name)
    days = (local.date() - now.date()).days
    if days == 0:
        return f"today {local:%H:%M}" if (local.hour or local.minute) else "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    if -7 < days < 0:
        return f"{-days} days ago"
    if 0 < days < 7:
        return local.strftime("%A")
    return local.strftime("%d %b")
