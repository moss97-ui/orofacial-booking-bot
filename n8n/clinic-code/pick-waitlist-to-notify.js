// n8n Code node: "Pick waitlist to notify" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// A booking was cancelled: tell waitlisted patients of this doctor (any day, or exactly this day) that a time is free.
const r = $('Route').first().json;
const now = Date.now();
if (!(Date.parse(r.slot_start) > now + 30 * 60000)) return [];
const seen = new Set();
const out = [];
for (const w of $('Load waitlist for doctor').all().map(i => i.json)) {
  if (!w || !w.chat_id || w.status !== 'waiting') continue;
  if (String(w.chat_id) === String(r.patient_chat_id || r.chat_id)) continue;
  if (w.wanted_date && w.wanted_date !== r.date) continue;
  if (seen.has(String(w.chat_id))) continue;
  seen.add(String(w.chat_id));
  out.push({ json: { chat_id: String(w.chat_id), doctor_key: r.doctor_key, doctor_name: r.doctor_name, patient_name: w.patient_name || '', wanted_date: w.wanted_date || '',
    text: '🔔 Լավ լուր․ ժամ է ազատվել\nԲժիշկ՝ ' + r.doctor_name + '\nԱմսաթիվ՝ ' + r.date + ', ժամ՝ ' + r.selected_time
      + '\n\nԱմրագրելու համար սեղմեք բժշկի անունը ստորև և ընտրեք ժամը։ Ժամը կստանա առաջինը ամրագրողը։' } });
}
return out;
