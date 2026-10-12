// n8n Code node: "Lang pack" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// Languages: Armenian (original), English, Russian.
// Translations live in the GitHub file n8n/clinic-i18n.json (edit them there). The file is cached in this
// workflow's static data and reloaded every 6 hours; if GitHub can't be reached, the last copy is used.
const SRC = 'https://raw.githubusercontent.com/moss97-ui/orofacial-booking-bot/main/n8n/clinic-i18n.json';
const store = $getWorkflowStaticData('global');
let D = store.i18n || null;
if (!D || !store.i18nAt || Date.now() - store.i18nAt > 6 * 3600e3) {
  try {
    const r = await this.helpers.httpRequest({ url: SRC, json: true, timeout: 8000 });
    const data = typeof r === 'string' ? JSON.parse(r) : r;
    if (data && Array.isArray(data.static)) { D = data; store.i18n = data; store.i18nAt = Date.now(); }
  } catch (e) {
    if (D) store.i18nAt = Date.now() - 5.5 * 3600e3; // keep the old copy, try again in ~30 min
  }
}
const rows = $input.all().map(i => i.json).filter(r => r && r.chat_id && r.lang);
const langs = {};
rows.forEach(r => { langs[String(r.chat_id)] = r.lang; });
let from_telegram = true;
try { $('Telegram Trigger').first(); } catch (e) { from_telegram = false; }
const P = { hy: [], en: [], ru: [] }, R = { hy: [], en: [], ru: [] };
if (D) {
  const H = 3600e3, now = Date.now();
  const ymd = ms => new Date(ms + 4 * H).toISOString().slice(0, 10);
  for (const lg of ['en', 'ru']) {
    const X = D[lg], k = lg === 'en' ? 1 : 2;
    const pairs = D.static.map(s => [s[0], s[k]]);
    D.hyMonths.forEach((m, i) => {
      pairs.push(['📅 ' + m, '📅 ' + X.months[i]]);
      pairs.push(['Ցավոք, ' + m + 'ին ազատ ժամ չկա Ձեր այցի համար։\nՍեղմեք «', X.noFree[0] + X.monthsIn[i] + X.noFree[1]]);
      pairs.push(['»՝ ' + m + 'ի օրերը տեսնելու համար, կամ «⬅️ Հետ»՝ այլ ամիս ընտրելու համար։', X.seeDays[0] + X.monthsOf[i] + X.seeDays[1]]);
    });
    D.hyDays.forEach((d, i) => pairs.push(['(' + d + ')', '(' + X.days[i] + ')']));
    D.hyShort.forEach((d, i) => pairs.push(['(' + d + ')', '(' + X.short[i] + ')']));
    for (let i = -7; i <= 100; i++) {
      const dd = ymd(now + i * 24 * H), w = new Date(dd + 'T12:00:00Z').getUTCDay(), mi = +dd.slice(5, 7) - 1, day = +dd.slice(8, 10);
      pairs.push([D.hyMon[mi] + ' ' + day + ' ' + D.hyShort[w], X.mon[mi] + ' ' + day + ' ' + X.short[w]]);
      pairs.push([dd.slice(8, 10) + '.' + dd.slice(5, 7) + ' ' + D.hyShort[w], dd.slice(8, 10) + '.' + dd.slice(5, 7) + ' ' + X.short[w]]);
    }
    const seen = new Set();
    const fwd = pairs.filter(p => p[0] && p[1] && p[0] !== p[1] && !seen.has(p[0]) && seen.add(p[0])).sort((a, b) => b[0].length - a[0].length);
    P[lg] = fwd.concat(X.punct || []);
    const rs = new Set();
    R[lg] = fwd.filter(p => p[1].length >= 3 && /[A-Za-zА-Яа-яЁё]/.test(p[1]) && !rs.has(p[1]) && rs.add(p[1]))
      .map(p => [p[1], p[0]]).sort((a, b) => b[0].length - a[0].length);
  }
}
return [{ json: { langs, L: langs, P, R, from_telegram } }];
