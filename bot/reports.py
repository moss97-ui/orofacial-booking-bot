"""Staff reports: dashboard, today / tomorrow / next 7 days, pending requests."""
from __future__ import annotations

import json

from .texts import SHORT_DAYS
from .timeutil import DAY, HOUR, hhmm, parse_ms, weekday, ymd


def build_staff_report(r: dict, rows: list, now: int) -> dict:
    names = {d["k"]: d["n"] for d in json.loads(r.get("staff_doctors") or "[]")}
    rows = [x for x in rows if x and x.get("request_id") and x.get("doctor_key") in names]
    today, tomorrow, week_end, week_ago = ymd(now), ymd(now + DAY), ymd(now + 7 * DAY), now - 7 * DAY
    day_of = lambda x: str(x["slot_start"])[:10]
    day_label = lambda d: d[8:10] + "." + d[5:7] + " " + SHORT_DAYS[weekday(d)]
    approved = sorted([x for x in rows if x["status"] == "approved"], key=lambda x: str(x["slot_start"]))
    pending = sorted([x for x in rows if x["status"] == "pending" and (parse_ms(x.get("expires_at")) or 0) > now
                      and (parse_ms(x.get("slot_start")) or 0) > now], key=lambda x: str(x["slot_start"]))
    who = lambda x: x.get("patient_full_name") or x.get("patient_name") or "—"
    ends_later = lambda x: (parse_ms(x.get("slot_end")) or 0) > now

    def line(x):
        return ("• " + str(x["slot_start"])[11:16] + "–" + str(x["slot_end"])[11:16] + " · " + names[x["doctor_key"]]
                + "\n   " + who(x) + " · " + (x.get("service") or "—")
                + "\n   ☎ " + (x.get("patient_phone") or "—") + (" · ✅ հաստատել է" if x.get("patient_confirmed") else "") + " · " + x["request_id"])

    def day_list(day, title):
        xs = [x for x in approved if day_of(x) == day]
        return title + " — " + day_label(day) + "\nԸնդամենը՝ " + str(len(xs)) + " այց" + ("\n\n" + "\n".join(map(line, xs)) if xs else "\n\nԱյցեր չկան։")

    rep = r.get("report")
    if rep == "today":
        text = "📅 " + day_list(today, "Այսօր")
    elif rep == "tomorrow":
        text = "📆 " + day_list(tomorrow, "Վաղը")
    elif rep == "week":
        xs = [x for x in approved if today <= day_of(x) < week_end and ends_later(x)]
        days = list(dict.fromkeys(day_of(x) for x in xs))
        text = "🗓 Առաջիկա 7 օրը\nԸնդամենը՝ " + str(len(xs)) + " այց" + ("" if xs else "\n\nԱյցեր չկան։")
        for d in days:
            ds = [x for x in xs if day_of(x) == d]
            text += "\n\n▫️ " + day_label(d) + " (" + str(len(ds)) + ")\n" + "\n".join(map(line, ds))
    elif rep == "pending":
        text = "⏳ Սպասող հայտեր՝ " + str(len(pending)) + ("\nՅուրաքանչյուր հայտ ուղարկվում է առանձին՝ հաստատելու կամ մերժելու կոճակներով։" if pending else "\n\nՍպասող հայտեր չկան։")
    else:
        changed = lambda x: (parse_ms(x.get("updatedAt") or x.get("createdAt")) or 0) > week_ago
        today_x = [x for x in approved if day_of(x) == today]
        left = [x for x in today_x if ends_later(x)]
        tom_x = [x for x in approved if day_of(x) == tomorrow]
        week_x = [x for x in approved if today <= day_of(x) < week_end and ends_later(x)]
        cancelled = len([x for x in rows if x["status"] == "cancelled" and changed(x)])
        rejected = len([x for x in rows if x["status"] == "rejected" and changed(x)])
        rated = [x for x in rows if int(x.get("rating") or 0) > 0 and (parse_ms(x.get("slot_start")) or 0) > now - 30 * DAY]
        low = len([x for x in rated if int(x["rating"]) <= 3])
        per = "\n".join("   " + n + "՝ " + str(len([x for x in week_x if x["doctor_key"] == k])) for k, n in names.items())
        nxt = [x for x in approved if (parse_ms(x.get("slot_start")) or 0) > now][:3]
        rating = (f"{sum(int(x['rating']) for x in rated) / len(rated):.1f}/5 ({len(rated)} գնահատական" + (f", ցածր՝ {low}" if low else "") + ")") if rated else "դեռ չկա"
        text = ("📊 Վահանակ — " + day_label(today) + ", " + hhmm(now)
                + "\n\n📅 Այսօր՝ " + str(len(today_x)) + " այց (մնացել է՝ " + str(len(left)) + ", գալը հաստատել են՝ " + str(len([x for x in today_x if x.get("patient_confirmed")])) + ")"
                + "\n📆 Վաղը՝ " + str(len(tom_x)) + " այց"
                + "\n🗓 Առաջիկա 7 օրը՝ " + str(len(week_x)) + " այց"
                + "\n⏳ Սպասող հայտեր՝ " + str(len(pending))
                + "\n❌ Վերջին 7 օրում՝ չեղարկված " + str(cancelled) + ", մերժված " + str(rejected)
                + "\n⭐ Գնահատական (վերջին 30 օր)՝ " + rating
                + "\n\n👨‍⚕️ Առաջիկա 7 օրը ըստ բժիշկների՝\n" + per
                + "\n\n⏭ Հաջորդ այցերը՝" + (("\n" + "\n".join("• " + day_label(day_of(x)) + " " + str(x["slot_start"])[11:16] + " · " + names[x["doctor_key"]] + " · " + who(x) for x in nxt)) if nxt else " չկան"))
    if len(text) > 3900:
        text = text[:3850] + "\n… (ցուցակը կրճատված է)"
    cards = []
    if rep == "pending":
        for x in pending[:15]:
            exp = parse_ms(x["expires_at"])
            cards.append({"request_id": x["request_id"], "text":
                          ("⏳ 🔁 Սպասող ժամի փոփոխության հայտ" if x.get("replaces_request_id") else "⏳ Սպասող հայտ")
                          + "\nՀայտ՝ " + x["request_id"] + "\nՊացիենտ՝ " + who(x) + (" (@" + x["telegram_username"] + ")" if x.get("telegram_username") else "")
                          + "\nՀեռախոս՝ " + (x.get("patient_phone") or "—") + "\nԾառայություն՝ " + (x.get("service") or "—")
                          + "\nԲժիշկ՝ " + names[x["doctor_key"]] + "\nԱմսաթիվ՝ " + day_of(x) + "\nԺամ՝ " + str(x["slot_start"])[11:16] + "–" + str(x["slot_end"])[11:16]
                          + " (Երևան)\nՀայտը վավեր է մինչև " + ymd(exp) + " " + hhmm(exp) + "։"})
    return {"text": text, "cards": cards}
