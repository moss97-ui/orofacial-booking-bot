// n8n Code node: "Check hold winner" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// Two patients could pick overlapping times at the same moment. Both requests are saved,
// then the one saved first (lowest row id) keeps the time; the other is marked "conflict".
// Visits can be 30, 60 or 90 minutes, so any overlap counts, not only the same start time.
const r = $('Route').first().json;
const now = Date.now();
const s0 = Date.parse(r.slot_start), e0 = Date.parse(r.slot_end);
const active = $('Load holds for this slot').all().map(i => i.json)
  .filter(x => x && x.request_id && (['approving', 'approved'].includes(x.status) || (x.status === 'pending' && Date.parse(x.expires_at) > now)))
  .filter(x => { const a = Date.parse(x.slot_start), b = Date.parse(x.slot_end) || a + 30 * 60000; return a < e0 && b > s0; })
  .sort((a, b) => a.id - b.id);
return [{ json: { won: !!active.length && active[0].request_id === r.request_id, holders: active.map(x => x.request_id) } }];
