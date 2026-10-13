"""Loads config/clinic.yaml: doctors, services, prices, hours and contacts."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Clinic:
    info: dict
    booking: dict
    specialties: dict          # key -> {name, minutes}
    service_menu: list         # specialty keys shown in "choose by service"
    reasons: list              # [{key, label, name, minutes, price, specialties}]
    price_note: str
    doctors: list              # [{doctor_key, doctor_name, specialty, calendar_id, approver_chat_id, ...}]
    extra_days: dict = field(default_factory=dict)
    phrases: dict = field(default_factory=dict)   # clinic-name wording used inside fixed texts
    languages: list = field(default_factory=lambda: ["hy"])  # more than one -> language choice on /start

    # --- lookups -------------------------------------------------------------
    def active_doctors(self) -> list:
        return [d for d in self.doctors if d.get("active", True)]

    def doctor(self, key: str) -> dict | None:
        return next((d for d in self.active_doctors() if d["doctor_key"] == key), None)

    def service_name(self, specialty: str) -> str:
        return (self.specialties.get(specialty) or {}).get("name", "")

    def duration_by_service(self, service_name: str) -> int | None:
        for sp in self.specialties.values():
            if sp.get("name") == service_name:
                return int(sp.get("minutes") or 30)
        return None

    def reasons_for(self, doctor: dict) -> list:
        return [r for r in self.reasons if doctor["specialty"] in r["specialties"]]

    def shift(self, doctor_key: str):
        d = self.doctor(doctor_key)
        return (d or {}).get("shift")


def load_clinic(path: str | Path) -> Clinic:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    # Placeholders in the config ("REPLACE_WITH_…") can be filled from variables, so a shared config file works as is
    # when all doctors use one calendar and one approver (CALENDAR_ID, APPROVER_CHAT_ID).
    def fill(value, env_name):
        value = str(value or "")
        return os.environ.get(env_name, "").strip() or value if value.startswith("REPLACE_WITH") else value

    doctors = []
    for d in raw.get("doctors", []):
        doctors.append({
            "doctor_key": d["key"],
            "doctor_name": d["name"],
            "specialty": d["specialty"],
            "calendar_id": fill(d.get("calendar_id", ""), "CALENDAR_ID"),
            "approver_chat_id": fill(d.get("approver_chat_id", ""), "APPROVER_CHAT_ID"),
            "active": d.get("active", True),
            "info_label": d.get("info_label") or ("ℹ️ " + d["name"].split(" ")[0]),
            "shift": d.get("shift"),
            "hours_text": d.get("hours_text", ""),
            "bio": d.get("bio", ""),
        })
    reasons = [{"key": r["key"], "label": r["label"], "name": r["name"], "min": int(r["minutes"]),
                "price": r.get("price", ""), "specialties": list(r["specialties"])} for r in raw.get("reasons", [])]
    booking = {"step_minutes": 30, "lead_minutes": 15, "max_days_ahead": 62, "request_ttl_hours": 2, "event_title_prefix": ""}
    booking.update(raw.get("booking") or {})
    name = raw["clinic"]["name"]
    # Wording that contains the clinic name. Defaults give the OroFacial texts; a generic clinic overrides them
    # in clinic.phrases (see tests/clinic_generic_test.yaml).
    phrases = {
        "welcome_place": name + " ատամնաբուժական կլինիկա",   # Բարի գալուստ ___։
        "thanks_to": name + " կլինիկային",                     # Շնորհակալություն, որ դիմեցիք ___ 🦷
        "contact_title": "Կապ " + name + " կլինիկայի հետ",     # 📞 ___
        "reminder_at": name + " կլինիկայում",                  # ⏰ Հիշեցում՝ վաղը Ձեր այցն է ___։
        "rating_at": name + "-ում",                            # 🦷 Ինչպե՞ս անցավ Ձեր այցը ___
        "created_by": name + " բոտի",                          # (calendar) Ստեղծվել է ___ կողմից …
    }
    phrases.update(raw["clinic"].get("phrases") or {})
    languages = [str(x) for x in (raw.get("languages") or ["hy"])]
    return Clinic(
        info=raw["clinic"],
        booking=booking,
        specialties=raw["specialties"],
        service_menu=raw.get("service_menu", []),
        reasons=reasons,
        price_note=raw.get("price_note", ""),
        doctors=doctors,
        extra_days=raw.get("extra_days") or {},
        phrases=phrases,
        languages=languages,
    )
