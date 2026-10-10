"""Google Calendar access (service account) and an in-memory calendar for tests / dry runs."""
from __future__ import annotations

import asyncio
import itertools
import logging

from .timeutil import parse_ms

log = logging.getLogger(__name__)


class CalendarError(Exception):
    pass


class GoogleCalendar:
    """Uses a Google service account. Share each doctor's calendar with the service account e-mail
    ("Make changes to events") so the bot can read busy times and create / delete visits."""

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, service_account_file: str, timezone: str = "Asia/Yerevan"):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(service_account_file, scopes=self.SCOPES)
        self.api = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.timezone = timezone

    def _list(self, calendar_id, time_min, time_max):
        items, token = [], None
        while True:
            res = self.api.events().list(calendarId=calendar_id, timeMin=time_min, timeMax=time_max, singleEvents=True,
                                         orderBy="startTime", timeZone=self.timezone, pageToken=token, maxResults=2500).execute()
            items += res.get("items", [])
            token = res.get("nextPageToken")
            if not token:
                return items

    async def list_events(self, calendar_id: str, time_min: str, time_max: str) -> list:
        try:
            return await asyncio.to_thread(self._list, calendar_id, time_min, time_max)
        except Exception as e:  # network / permission problems
            log.exception("calendar list failed")
            raise CalendarError(str(e)) from e

    async def create_event(self, calendar_id: str, start: str, end: str, summary: str, description: str = "") -> str:
        body = {"summary": summary, "description": description, "start": {"dateTime": start}, "end": {"dateTime": end},
                "transparency": "opaque"}
        try:
            ev = await asyncio.to_thread(lambda: self.api.events().insert(calendarId=calendar_id, body=body).execute())
            return ev["id"]
        except Exception as e:
            log.exception("calendar create failed")
            raise CalendarError(str(e)) from e

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        try:
            await asyncio.to_thread(lambda: self.api.events().delete(calendarId=calendar_id, eventId=event_id).execute())
        except Exception as e:
            log.warning("calendar delete failed: %s", e)
            raise CalendarError(str(e)) from e


class MemoryCalendar:
    """Keeps events in memory. Used by the tests and when no Google credentials are configured
    (DRY RUN: the bot works, but nothing is written to a real calendar)."""

    def __init__(self):
        self.events: dict[str, list] = {}
        self._ids = itertools.count(1)
        self.fail = False

    async def list_events(self, calendar_id, time_min, time_max):
        if self.fail:
            raise CalendarError("calendar unavailable")
        a, b = parse_ms(time_min), parse_ms(time_max)
        out = []
        for e in self.events.get(calendar_id, []):
            s, t = parse_ms(e["start"]["dateTime"]), parse_ms(e["end"]["dateTime"])
            if s < b and t > a:
                out.append(e)
        return out

    async def create_event(self, calendar_id, start, end, summary, description=""):
        if self.fail:
            raise CalendarError("calendar unavailable")
        eid = f"evt{next(self._ids)}"
        self.events.setdefault(calendar_id, []).append({"id": eid, "status": "confirmed", "summary": summary,
                                                        "description": description, "start": {"dateTime": start},
                                                        "end": {"dateTime": end}})
        return eid

    async def delete_event(self, calendar_id, event_id):
        lst = self.events.get(calendar_id, [])
        self.events[calendar_id] = [e for e in lst if e["id"] != event_id]
