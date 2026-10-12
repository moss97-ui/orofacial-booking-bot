"""Languages: Armenian (built in), English and Russian.

Works exactly like the n8n "Clinic - Booking bot":
* The bot logic and all texts stay in Armenian. Just before a message is sent, every Armenian fragment is replaced
  with its translation for the receiver's language ("pack" = list of [Armenian, translation] pairs, longest first).
* When a patient taps a translated button, the text is turned back into the Armenian label ("reverse pack"), so the
  router sees the same input as in Armenian.
* Translations come from n8n/clinic-i18n.json (the same file the n8n workflow downloads from GitHub).
  Date labels ("հոկ 15 Հնգ"), month names and weekday names are generated here, as in the n8n "Lang pack" node.

Port of the n8n Code nodes "Lang pack" and the language part of "Parse update".
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .timeutil import now_ms

H = 3600 * 1000
CHOICE = {"🇦🇲 Հայերեն": "hy", "🇬🇧 English": "en", "🇷🇺 Русский": "ru"}
LANG_BUTTONS = [["🇦🇲 Հայերեն"], ["🇬🇧 English"], ["🇷🇺 Русский"]]
ASK_TEXT = "🌐 Ընտրեք լեզուն\nChoose your language\nВыберите язык"
_START = re.compile(r"^/start(@[A-Za-z0-9_]+)?(\s|\Z)")
_LATIN_CYR = re.compile(r"[A-Za-zА-Яа-яЁё]")


def js_len(s: str) -> int:
    """String length as JavaScript counts it (UTF-16 code units), so the sort order matches n8n exactly."""
    return len(s.encode("utf-16-le")) // 2


def apply(pairs, text) -> str:
    """Same as JS pairs.reduce((a, p) => a.split(p[0]).join(p[1]), String(text))."""
    s = "" if text is None else str(text)
    for a, b in pairs:
        if a:
            s = s.replace(a, b)
    return s


def _ymd(ms: int) -> str:
    return datetime.fromtimestamp((ms + 4 * H) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def build_packs(data: dict | None, now: int) -> tuple[dict, dict]:
    """Returns (P, R): forward packs {lang: [[hy, tr], ...]} and reverse packs {lang: [[tr, hy], ...]}."""
    P = {"hy": [], "en": [], "ru": []}
    R = {"hy": [], "en": [], "ru": []}
    if not data:
        return P, R
    for lg in ("en", "ru"):
        X, k = data[lg], (1 if lg == "en" else 2)
        pairs = [[s[0], s[k]] for s in data["static"]]
        for i, m in enumerate(data["hyMonths"]):
            pairs.append(["📅 " + m, "📅 " + X["months"][i]])
            pairs.append(["Ցավոք, " + m + "ին ազատ ժամ չկա Ձեր այցի համար։\nՍեղմեք «", X["noFree"][0] + X["monthsIn"][i] + X["noFree"][1]])
            pairs.append(["»՝ " + m + "ի օրերը տեսնելու համար, կամ «⬅️ Հետ»՝ այլ ամիս ընտրելու համար։", X["seeDays"][0] + X["monthsOf"][i] + X["seeDays"][1]])
        for i, d in enumerate(data["hyDays"]):
            pairs.append(["(" + d + ")", "(" + X["days"][i] + ")"])
        for i, d in enumerate(data["hyShort"]):
            pairs.append(["(" + d + ")", "(" + X["short"][i] + ")"])
        for i in range(-7, 101):
            dd = _ymd(now + i * 24 * H)
            w = (datetime.strptime(dd, "%Y-%m-%d").weekday() + 1) % 7  # JS getUTCDay(): Sunday = 0
            mi, day = int(dd[5:7]) - 1, int(dd[8:10])
            pairs.append([data["hyMon"][mi] + " " + str(day) + " " + data["hyShort"][w], X["mon"][mi] + " " + str(day) + " " + X["short"][w]])
            pairs.append([dd[8:10] + "." + dd[5:7] + " " + data["hyShort"][w], dd[8:10] + "." + dd[5:7] + " " + X["short"][w]])
        seen, fwd = set(), []
        for p in pairs:
            if p[0] and p[1] and p[0] != p[1] and p[0] not in seen:
                seen.add(p[0])
                fwd.append(p)
        fwd.sort(key=lambda p: -js_len(p[0]))  # stable, like JS Array.prototype.sort
        P[lg] = fwd + [list(x) for x in (X.get("punct") or [])]
        rs, rev = set(), []
        for p in fwd:
            if js_len(p[1]) >= 3 and _LATIN_CYR.search(p[1]) and p[1] not in rs:
                rs.add(p[1])
                rev.append([p[1], p[0]])
        rev.sort(key=lambda p: -js_len(p[0]))
        R[lg] = rev
    return P, R


def load_vocab(path: str | Path | None) -> dict:
    """Business vocabulary (e.g. a beauty salon: doctor -> master, patient -> client, clinic -> salon).
    File: {"hy": [[from, to], ...], "en": [...], "ru": [...]}. Applied to every outgoing text after the
    bot has written it in Armenian; longer phrases are replaced first."""
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {lg: sorted(([a, b] for a, b in raw.get(lg, []) if a), key=lambda p: -len(p[0])) for lg in ("hy", "en", "ru")}


class I18n:
    """Holds the translation file and the per-day packs. `enabled` is False for an Armenian-only clinic.
    `extra`: more [hy, en, ru] rows (a business's own services, names, address).
    `vocab`: business vocabulary (see load_vocab); `labels`: Armenian button labels to map back exactly."""

    def __init__(self, path: str | Path | None, languages: list[str], extra: str | Path | None = None,
                 vocab: str | Path | None = None, labels: list[str] | None = None):
        self.languages = languages
        self.enabled = len(languages) > 1
        self.data = None
        if self.enabled and path:
            self.data = json.loads(Path(path).read_text(encoding="utf-8"))
            if extra:
                self.data["static"] = self.data["static"] + json.loads(Path(extra).read_text(encoding="utf-8"))["static"]
        self.vocab = load_vocab(vocab)
        # Button labels as the business shows them -> the label the router knows.
        self.back = {}
        if self.vocab:
            for lb in labels or []:
                shown = apply(self.vocab["hy"], lb)
                if shown != lb:
                    self.back[shown] = lb
        self._day = None
        self._packs = ({"hy": [], "en": [], "ru": []}, {"hy": [], "en": [], "ru": []})

    def _with_vocab(self, P: dict) -> tuple[dict, dict]:
        """Packs whose Armenian side already uses the business vocabulary, and whose translations do too."""
        P2, R2 = {"hy": [], "en": [], "ru": []}, {"hy": [], "en": [], "ru": []}
        for lg in ("en", "ru"):
            punct = P[lg][len(P[lg]) - len((self.data or {}).get(lg, {}).get("punct") or []):] if self.data else []
            body = P[lg][:len(P[lg]) - len(punct)]
            seen, fwd = set(), []
            for a, b in body:
                a2, b2 = apply(self.vocab["hy"], a), apply(self.vocab[lg], b)
                if a2 and b2 and a2 != b2 and a2 not in seen:
                    seen.add(a2)
                    fwd.append([a2, b2])
            fwd.sort(key=lambda p: -js_len(p[0]))
            P2[lg] = fwd + punct
            rs, rev = set(), []
            for a, b in fwd:
                if js_len(b) >= 3 and _LATIN_CYR.search(b) and b not in rs:
                    rs.add(b)
                    rev.append([b, a])
            rev.sort(key=lambda p: -js_len(p[0]))
            R2[lg] = rev
        return P2, R2

    def packs(self) -> tuple[dict, dict]:
        now = now_ms()
        day = _ymd(now)  # date labels cover 7 days back .. 100 days ahead of today; rebuilt once a day
        if day != self._day:
            packs = build_packs(self.data, now)
            self._packs, self._day = (self._with_vocab(packs[0]) if self.vocab else packs), day
        return self._packs

    def translate(self, text, lang: str) -> str:
        if text is None:
            return text
        if self.vocab:
            text = apply(self.vocab["hy"], text)
        if not self.enabled or lang == "hy":
            return text
        return apply(self.packs()[0].get(lang) or [], text)

    def translate_keyboard(self, rows, lang: str):
        """Translates button labels; URL / callback data stay as they are."""
        if not rows or (not self.vocab and (not self.enabled or lang == "hy")):
            return rows
        out = []
        for row in rows:
            new = []
            for b in row:
                if isinstance(b, dict):
                    new.append({**b, "text": self.translate(b["text"], lang)})
                elif isinstance(b, str):
                    new.append(self.translate(b, lang))
                else:
                    new.append(b)
            out.append(new)
        return out

    def incoming(self, p: dict, langs: dict) -> dict:
        """Language step of "Parse update". `langs` = {chat_id: lang} saved so far.
        Adds ask_lang / set_lang / lang to p and turns translated button taps back into Armenian."""
        p = dict(p)
        p["ask_lang"], p["set_lang"] = False, ""
        if not self.enabled:
            p["lang"] = "hy"
            if self.back and p.get("text") in self.back:
                p["text"] = self.back[p["text"]]
            return p
        chat = p.get("chat_id") or ""
        if p["kind"] == "message" and p.get("text") in CHOICE:
            p["set_lang"] = CHOICE[p["text"]]
            langs = {**langs, chat: p["set_lang"]}
            p["text"] = "/start"
        elif p["kind"] == "message" and chat and (_START.search(p.get("text") or "") or not langs.get(chat)):
            p["ask_lang"] = True
        p["lang"] = langs.get(chat) or "hy"
        if p["lang"] != "hy" and p.get("text") and not p["set_lang"]:
            t2 = apply(self.packs()[1].get(p["lang"]) or [], p["text"])
            if not _LATIN_CYR.search(t2):
                p["text"] = t2
        if self.back and p.get("text") in self.back:
            p["text"] = self.back[p["text"]]
        return p
