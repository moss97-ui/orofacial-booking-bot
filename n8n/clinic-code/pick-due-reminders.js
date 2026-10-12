// n8n Code node: "Pick due reminders" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// Day-before reminder: 24h..2h before the visit (only if booked more than ~26h ahead).
// Two-hour reminder: within 2h of the visit (only if booked more than 2h ahead).
const docs = {};
$('Load doctors for reminders').all().forEach(i => { if (i.json && i.json.doctor_key) docs[i.json.doctor_key] = i.json.doctor_name; });
const now = Date.now(), H = 3600e3;
const ymd = ms => new Date(ms + 4 * H).toISOString().slice(0, 10);
const out = [];
for (const x of $('Load confirmed bookings').all().map(i => i.json)) {
  if (!x || !x.request_id || x.status !== 'approved') continue;
  const start = Date.parse(x.slot_start);
  if (!(start > now)) continue;
  const lead = start - now;
  const ahead = start - (Date.parse(x.createdAt) || 0);
  const sent24 = x.reminder_24h_sent === true, sent2 = x.reminder_2h_sent === true;
  let kind = '';
  if (!sent2 && lead <= 2 * H && ahead > 2 * H) kind = '2h';
  else if (!sent24 && lead <= 24 * H && lead > 2 * H && ahead > 26 * H) kind = '24h';
  if (!kind) continue;
  const day = ymd(start) === ymd(now) ? 'այսօր' : 'վաղը';
  const head = kind === '2h' ? '⏰ Հիշեցում՝ Ձեր այցը սկսվում է մոտ 2 ժամից։' : '⏰ Հիշեցում՝ ' + day + ' Ձեր այցն է մեր կլինիկայում։';
  const text = head
    + '\nԱմսաթիվ՝ ' + x.slot_start.slice(0, 10) + ', ' + x.slot_start.slice(11, 16) + ' (Երևան)'
    + '\nԲժիշկ՝ ' + (docs[x.doctor_key] || '')
    + '\nԾառայություն՝ ' + (x.service || '—')
    + '\nԱյցելու՝ ' + (x.patient_full_name || x.patient_name || '—')
    + '\nՀայտ՝ ' + x.request_id
    + '\nԽնդրում ենք հաստատել, որ կգաք, կամ չեղարկել / փոխել ժամը։';
  out.push({ json: { chat_id: String(x.chat_id), request_id: x.request_id, kind, text, set24: true, set2: kind === '2h' } });
}
return out;
