// n8n Code node: "Build waitlist note for doctor" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// After a cancellation: tell the doctor / approver which waitlisted patients were told about the freed time.
const r = $('Route').first().json;
const ws = $input.all().map(i => i.json);
if (!ws.length || !r.approver_chat_id) return [];
const lines = ws.slice(0, 10).map((w, i) => (i + 1) + '. ' + (w.patient_name || 'Անանուն պացիենտ') + (w.wanted_date ? ' (ցանկալի օր՝ ' + w.wanted_date + ')' : ''));
const text = '🔔 Սպասման ցուցակ\nԱզատված ժամ՝ ' + r.date + ', ' + r.selected_time + ' · ' + r.doctor_name
  + '\n\nԱյս ժամի մասին տեղեկացվել է սպասման ցուցակի ' + ws.length + ' պացիենտ՝\n' + lines.join('\n') + (ws.length > 10 ? '\n…' : '')
  + '\n\nԺամը կստանա առաջինը ամրագրողը։ Նոր հայտը կգա Ձեզ սովորական կարգով՝ հաստատելու համար։';
return [{ json: { chat_id: String(r.approver_chat_id), text } }];
