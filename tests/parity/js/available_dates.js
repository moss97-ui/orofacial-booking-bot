// Lists the working days of the current (or next) month on which the chosen doctor still has
// at least one free gap long enough for the visit (30/60/90 min).
const r = $('Route').first().json;
const events = $('Read upcoming events').all().map(i => i.json).filter(e => e && e.id && e.status !== 'cancelled' && e.transparency !== 'transparent');
const holds = $('Load doctor holds').all().map(i => i.json).filter(x => x && x.request_id);
const SHIFTS = { aram: ['09:00', '15:00'], ani: ['12:00', '18:00'], narek: ['10:00', '17:00', '16:00'], mariam: ['09:00', '16:00'], davit: ['11:00', '18:00', '17:00'], lilit: ['10:00', '16:00'] };
// TEST ONLY: extra working days for a doctor (date -> doctor -> [start, end]). Remove after testing.
const TEST_DAYS = { '2026-10-10': { aram: ['09:00', '21:00'] } };
const CLINIC = ['09:00', '18:00'];
const STEP = 30 * 60000, DUR = (Number(r.duration_min) || 30) * 60000, LEAD = 15 * 60000, now = Date.now();
const DAYS = ['Կիրակի', 'Երկուշաբթի', 'Երեքշաբթի', 'Չորեքշաբթի', 'Հինգշաբթի', 'Ուրբաթ', 'Շաբաթ'];
const ymd = ms => new Date(ms + 4 * 3600e3).toISOString().slice(0, 10);
const mine = events.filter(e => !r.filter_by_name || String(e.summary || '').includes(r.doctor_name));
const blocks = mine.map(e => (e.start && e.start.date)
  ? [Date.parse(e.start.date + 'T00:00:00+04:00'), Date.parse(((e.end && e.end.date) || e.start.date) + 'T00:00:00+04:00')]
  : [Date.parse(e.start && e.start.dateTime), Date.parse(e.end && e.end.dateTime)]);
const bad = blocks.some(b => !Number.isFinite(b[0]) || !Number.isFinite(b[1]));
const held = holds.filter(x => ['approving', 'approved'].includes(x.status) || (x.status === 'pending' && Date.parse(x.expires_at) > now)).map(x => [Date.parse(x.slot_start), Date.parse(x.slot_end) || Date.parse(x.slot_start) + STEP]);
// Times the doctor already rejected for this patient are not offered to them again.
holds.filter(x => x.status === 'rejected' && String(x.chat_id) === String(r.chat_id)).forEach(x => held.push([Date.parse(x.slot_start), Date.parse(x.slot_start) + 1]));
const sh = SHIFTS[r.doctor_key];
const MONTHS = ['Հունվար', 'Փետրվար', 'Մարտ', 'Ապրիլ', 'Մայիս', 'Հունիս', 'Հուլիս', 'Օգոստոս', 'Սեպտեմբեր', 'Հոկտեմբեր', 'Նոյեմբեր', 'Դեկտեմբեր'];
const SHORT = ['Կիր', 'Երկ', 'Երք', 'Չրք', 'Հնգ', 'Ուրբ', 'Շբթ'];
const MON = ['հունվ', 'փետ', 'մարտ', 'ապր', 'մայ', 'հունիս', 'հուլ', 'օգոս', 'սեպ', 'հոկ', 'նոյ', 'դեկ'];
const today = ymd(now);
const todayMs = Date.parse(today + 'T12:00:00+04:00');
function monthOf(off) {
  const m0 = +today.slice(5, 7) - 1 + off;
  const y = +today.slice(0, 4) + Math.floor(m0 / 12), m = ((m0 % 12) + 12) % 12;
  return { key: y + '-' + String(m + 1).padStart(2, '0'), name: MONTHS[m], year: y };
}
function daysIn(off) {
  const mk = monthOf(off), list = [];
  if (!sh || bad) return list;
  for (let d = 0; d < 63; d++) {
    const date = ymd(todayMs + d * 86400e3);
    if (date.slice(0, 7) !== mk.key) continue;
    const dow = new Date(date + 'T12:00:00Z').getUTCDay();
    const extra = (TEST_DAYS[date] || {})[r.doctor_key];
    if ((dow === 0 || dow === 6) && !extra) continue;
    const at = h => Date.parse(date + 'T' + h + ':00+04:00');
    const start = extra ? at(extra[0]) : Math.max(at(sh[0]), at(CLINIC[0]));
    const end = extra ? at(extra[1]) : Math.min(at(dow === 5 && sh[2] ? sh[2] : sh[1]), at(CLINIC[1]));
    let n = 0;
    for (let t = start; t + DUR <= end; t += STEP) {
      if (t < now + LEAD) continue;
      if (blocks.some(b => t < b[1] && t + DUR > b[0])) continue;
      if (held.some(b => t < b[1] && t + DUR > b[0])) continue;
      n++;
    }
    if (n) list.push({ date, label: MON[+date.slice(5, 7) - 1] + ' ' + (+date.slice(8, 10)) + ' ' + SHORT[dow], free: n });
  }
  return list;
}
const visit = 'Բժիշկ՝ ' + r.doctor_name + '\nԱյց՝ ' + (r.visit_label || '—') + ' (' + (Number(r.duration_min) || 30) + ' րոպե)';
// Step 1 (month_offset = -1): choose the month. Step 2 (0 = this month, 1 = next month): choose the date.
const m0 = monthOf(0), m1 = monthOf(1);
if (Number(r.month_offset) === -1 || r.month_offset === undefined || r.month_offset === '') {
  const n0 = daysIn(0).length, n1 = daysIn(1).length;
  const lab = (m, n) => '📅 ' + m.name + ' ' + m.year + (n ? '' : ' (ազատ օր չկա)');
  const reply = bad
    ? 'Ներողություն, օրացույցում սխալ գրառում կա, և չեմ կարող ստուգել ազատ ժամերը։ Փորձեք ավելի ուշ։'
    : visit + '\n\nԸնտրեք ամիսը։';
  return [{ json: { pick_month: true, reply, month_labels: [lab(m0, n0), lab(m1, n1)], has_dates: true, labels: [], rows: 0, toggle: '' } }];
}
const off = Number(r.month_offset) === 1 ? 1 : 0;
const days = daysIn(off);
const cur = off === 0 ? m0 : m1, other = off === 0 ? m1 : m0;
// Button that switches to the other month.
const toggle = off === 0 ? '📅 ' + other.name + ' →' : '← 📅 ' + other.name;
const reply = bad
  ? 'Ներողություն, օրացույցում սխալ գրառում կա, և չեմ կարող ստուգել ազատ ժամերը։ Փորձեք ավելի ուշ։'
  : days.length
    ? visit + '\n\n📅 ' + cur.name + ' ' + cur.year + '\nԸնտրեք ամսաթիվը ստորև․ ցուցադրված են միայն այն օրերը, երբ կա ազատ ժամ Ձեր այցի համար։'
    : visit + '\n\nՑավոք, ' + cur.name + 'ին ազատ ժամ չկա Ձեր այցի համար։\nՍեղմեք «' + toggle + '»՝ ' + other.name + 'ի օրերը տեսնելու համար, կամ «⬅️ Հետ»՝ այլ ամիս ընտրելու համար։';
// Up to 6 rows of 4 date buttons; the right keyboard size is picked by the number of rows.
const labels = [];
for (let i = 0; i < 24; i++) labels.push(days[i] ? days[i].label : '·');
return [{ json: { pick_month: false, reply, labels, has_dates: days.length > 0, days, rows: Math.max(1, Math.ceil(days.length / 4)), toggle, month_key: cur.key, month_labels: [] } }];