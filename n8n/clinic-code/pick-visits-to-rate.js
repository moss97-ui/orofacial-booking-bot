// n8n Code node: "Pick visits to rate" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// After-visit rating: 30 min to 24 h after an approved visit ended, once per booking.
const docs = {};
$('Load doctors for reminders').all().forEach(i => { if (i.json && i.json.doctor_key) docs[i.json.doctor_key] = i.json.doctor_name; });
const now = Date.now(), M = 60000, H = 3600e3;
const out = [];
for (const x of $('Load confirmed bookings').all().map(i => i.json)) {
  if (!x || !x.request_id || x.status !== 'approved' || x.rating_asked === true || Number(x.rating) > 0) continue;
  const end = Date.parse(x.slot_end);
  if (!Number.isFinite(end) || now - end < 30 * M || now - end > 24 * H) continue;
  const text = '🦷 Ինչպե՞ս անցավ Ձեր այցը մեր կլինիկայում\n'
    + 'Բժիշկ՝ ' + (docs[x.doctor_key] || '') + '\n'
    + 'Ամսաթիվ՝ ' + String(x.slot_start).slice(0, 10) + ', ' + String(x.slot_start).slice(11, 16)
    + '\n\nԽնդրում ենք գնահատել այցը 1-ից 5 աստղով (5՝ գերազանց)։ Դա մեզ կօգնի դառնալ ավելի լավը։';
  out.push({ json: { chat_id: String(x.chat_id), request_id: x.request_id, text } });
}
return out;
