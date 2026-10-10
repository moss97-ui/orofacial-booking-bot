// Free start times for a visit of the chosen length (30/60/90 min) = doctor's shift inside clinic hours, weekdays only,
// minus calendar events (visits, lunch, "not working"), minus active booking holds, minus past times.
const r = $('Route').first().json;
const events = $('Read day events').all().map(i => i.json).filter(e => e && e.id && e.status !== 'cancelled' && e.transparency !== 'transparent');
const holds = $('Load slot holds').all().map(i => i.json).filter(x => x && x.request_id);
const SHIFTS = { aram: ['09:00', '15:00'], ani: ['12:00', '18:00'], narek: ['10:00', '17:00', '16:00'], mariam: ['09:00', '16:00'], davit: ['11:00', '18:00', '17:00'], lilit: ['10:00', '16:00'] }; // [start, end, Friday end]
// TEST ONLY: extra working days for a doctor (date -> doctor -> [start, end]). Remove after testing.
const TEST_DAYS = { '2026-10-10': { aram: ['09:00', '21:00'] } };
const CLINIC = ['09:00', '18:00'];
const STEP = 30 * 60000, DUR = (Number(r.duration_min) || 30) * 60000, LEAD = 15 * 60000, now = Date.now();
const at = hm => Date.parse(r.date + 'T' + hm + ':00+04:00');
const hm = ms => new Date(ms + 4 * 3600e3).toISOString().slice(11, 16);
const DAYS = ['Կիրակի', 'Երկուշաբթի', 'Երեքշաբթի', 'Չորեքշաբթի', 'Հինգշաբթի', 'Ուրբաթ', 'Շաբաթ'];
const dow = new Date(r.date + 'T12:00:00Z').getUTCDay();
const sh = SHIFTS[r.doctor_key];
const extra = (TEST_DAYS[r.date] || {})[r.doctor_key];
const free = [];
let problem = '';
if (!sh) problem = 'no_shift';
else if ((dow === 0 || dow === 6) && !extra) problem = 'weekend';
else {
  const start = extra ? at(extra[0]) : Math.max(at(sh[0]), at(CLINIC[0]));
  const end = extra ? at(extra[1]) : Math.min(at(dow === 5 && sh[2] ? sh[2] : sh[1]), at(CLINIC[1]));
  const mine = events.filter(e => !r.filter_by_name || String(e.summary || '').includes(r.doctor_name));
  const blocks = mine.map(e => (e.start && e.start.date)
    ? [Date.parse(e.start.date + 'T00:00:00+04:00'), Date.parse(((e.end && e.end.date) || e.start.date) + 'T00:00:00+04:00')]
    : [Date.parse(e.start && e.start.dateTime), Date.parse(e.end && e.end.dateTime)]);
  if (blocks.some(b => !Number.isFinite(b[0]) || !Number.isFinite(b[1]))) problem = 'bad_event';
  const held = holds.filter(x => x.request_id !== r.request_id && (['approving', 'approved'].includes(x.status) || (x.status === 'pending' && Date.parse(x.expires_at) > now)))
    .map(x => [Date.parse(x.slot_start), Date.parse(x.slot_end) || Date.parse(x.slot_start) + STEP]);
  // Times the doctor already rejected for this patient are not offered to them again.
  if (r.mode !== 'approve') holds.filter(x => x.status === 'rejected' && String(x.chat_id) === String(r.chat_id)).forEach(x => held.push([Date.parse(x.slot_start), Date.parse(x.slot_start) + 1]));
  if (!problem) for (let t = start; t + DUR <= end; t += STEP) {
    if (t < now + LEAD) continue;
    if (blocks.some(b => t < b[1] && t + DUR > b[0])) continue;
    if (held.some(b => t < b[1] && t + DUR > b[0])) continue;
    free.push(hm(t));
  }
}
const ok = r.mode === 'date' ? free.length > 0 : free.includes(r.selected_time);
const dayLabel = r.date + ' (' + DAYS[dow] + ')';
let reply;
if (problem === 'bad_event') reply = 'Ներողություն, օրացույցում սխալ գրառում կա, և չեմ կարող ստուգել ազատ ժամերը։ Փորձեք այլ ամսաթիվ կամ ավելի ուշ։';
else if (free.length) reply = (r.mode === 'time' ? 'Ցավոք, ' + r.selected_time + '-ն այլևս ազատ չէ։\n\n' : '') + 'Բժիշկ՝ ' + r.doctor_name + '\nԱմսաթիվ՝ ' + dayLabel + '\nԱյց՝ ' + (r.visit_label || '—') + '\nՏևողությունը՝ ' + (Number(r.duration_min) || 30) + ' րոպե։\nԸնտրեք այցի սկզբի ժամը ստորև նշված կոճակներից։';
else reply = 'Ցավոք, ' + dayLabel + '-ին ' + r.doctor_name + '-ի մոտ ազատ ժամ չկա։\nՍեղմեք «Այլ ամսաթիվ»։';
// Fixed 4x4 button grid: free times first, unused cells show a dot.
const labels = [];
for (let i = 0; i < 16; i++) labels.push(free[i] || '·');
return [{ json: { mode: r.mode, ok, free, has_free: free.length > 0, free_json: JSON.stringify(free), next_stage: free.length ? 'awaiting_time' : 'awaiting_date', reply, labels, problem, events_checked: events.length } }];