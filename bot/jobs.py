"""Scheduled work (every 30 minutes): visit reminders and the after-visit rating request."""
from __future__ import annotations

import logging

from .actions import Bot, btn
from .timeutil import HOUR, MIN, now_ms, parse_ms, ymd

log = logging.getLogger(__name__)


async def run_scheduled(bot: Bot) -> dict:
    """Day-before reminder: 24h..2h before the visit (only if booked more than ~26h ahead).
    Two-hour reminder: within 2h of the visit (only if booked more than 2h ahead).
    Rating: 30 min to 24 h after an approved visit ended, once per booking."""
    names = {d["doctor_key"]: d["doctor_name"] for d in bot.clinic.doctors}
    links = bot.clinic.info.get("links", {})
    now = now_ms()
    sent_reminders = sent_ratings = 0
    for x in bot.db.requests_by_status("approved"):
        start, end = parse_ms(x["slot_start"]), parse_ms(x["slot_end"])
        # --- reminders
        if start and start > now:
            lead = start - now
            ahead = start - (parse_ms(x.get("createdAt")) or 0)
            kind = ""
            if not x["reminder_2h_sent"] and lead <= 2 * HOUR and ahead > 2 * HOUR:
                kind = "2h"
            elif not x["reminder_24h_sent"] and 2 * HOUR < lead <= 24 * HOUR and ahead > 26 * HOUR:
                kind = "24h"
            if kind:
                day = "այսօր" if ymd(start) == ymd(now) else "վաղը"
                head = "⏰ Հիշեցում՝ Ձեր այցը սկսվում է մոտ 2 ժամից։" if kind == "2h" else "⏰ Հիշեցում՝ " + day + " Ձեր այցն է " + bot.clinic.info["name"] + " կլինիկայում։"
                text = (head + "\nԱմսաթիվ՝ " + x["slot_start"][:10] + ", " + x["slot_start"][11:16] + " (Երևան)\nԲժիշկ՝ " + names.get(x["doctor_key"], "")
                        + "\nԾառայություն՝ " + (x["service"] or "—") + "\nԱյցելու՝ " + (x["patient_full_name"] or x["patient_name"] or "—")
                        + "\nՀայտ՝ " + x["request_id"] + "\nԽնդրում ենք հաստատել, որ կգաք, կամ չեղարկել / փոխել ժամը։")
                inline = [[btn("✅ Կգամ", callback_data="ok|" + x["request_id"]), btn("❌ Չեմ կարող գալ", callback_data="cx|" + x["request_id"])],
                          [btn("🔁 Փոխել ժամը", callback_data="ch|" + x["request_id"])]]
                if links.get("route"):
                    inline.append([btn("🚗 Երթուղի դեպի կլինիկա", url=links["route"])])
                await bot.send(x["chat_id"], text, inline=inline)
                bot.db.update_request(x["request_id"], None, reminder_24h_sent=True, reminder_2h_sent=(kind == "2h"))
                sent_reminders += 1
        # --- rating after the visit
        if end and not x["rating_asked"] and not int(x.get("rating") or 0) and 30 * MIN <= now - end <= 24 * HOUR:
            text = ("🦷 Ինչպե՞ս անցավ Ձեր այցը " + bot.clinic.info["name"] + "-ում\nԲժիշկ՝ " + names.get(x["doctor_key"], "")
                    + "\nԱմսաթիվ՝ " + x["slot_start"][:10] + ", " + x["slot_start"][11:16]
                    + "\n\nԽնդրում ենք գնահատել այցը 1-ից 5 աստղով (5՝ գերազանց)։ Դա մեզ կօգնի դառնալ ավելի լավը։")
            await bot.send(x["chat_id"], text, inline=[[btn(f"{i}⭐", callback_data=f"r{i}|" + x["request_id"]) for i in range(1, 6)]])
            bot.db.update_request(x["request_id"], None, rating_asked=True)
            sent_ratings += 1
    if sent_reminders or sent_ratings:
        log.info("scheduled run: %s reminders, %s rating requests", sent_reminders, sent_ratings)
    return {"reminders": sent_reminders, "ratings": sent_ratings}
