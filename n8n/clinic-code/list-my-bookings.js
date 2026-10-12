// n8n Code node: "List my bookings" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// Upcoming active bookings of this patient (max 5), one item per booking card.
const r = $('Route').first().json;
const docs = {};
$('Load doctors').all().forEach(i => { if (i.json && i.json.doctor_key) docs[i.json.doctor_key] = i.json.doctor_name; });
const now = Date.now();
const rows = $('Load my bookings').all().map(i => i.json)
  .filter(x => x && x.request_id && ['approved', 'pending'].includes(x.status) && Date.parse(x.slot_start) > now)
  .sort((a, b) => Date.parse(a.slot_start) - Date.parse(b.slot_start))
  .slice(0, 5);
if (!rows.length) return [{ json: { has: false, chat_id: r.chat_id } }];
return rows.map(x => ({ json: { has: true, chat_id: r.chat_id, request_id: x.request_id,
  text: '📅 ' + x.slot_start.slice(0, 10) + ', ' + x.slot_start.slice(11, 16) + ' (Երևան)\nԲժիշկ՝ ' + (docs[x.doctor_key] || '') + '\nԾառայություն՝ ' + (x.service || '—') + '\nԱյցելու՝ ' + (x.patient_full_name || x.patient_name || '—') + '\nԿարգավիճակ՝ ' + (x.status === 'approved' ? '✅ Հաստատված' : '⏳ Սպասում է բժշկի հաստատմանը') + '\nՀայտ՝ ' + x.request_id } }));
