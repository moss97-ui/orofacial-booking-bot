// n8n Code node: "Pending cards" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// One item per pending request, so each gets its own message with approve / reject buttons.
return $('Build staff report').first().json.cards.map(c => ({ json: c }));
