// n8n Code node: "Parse update" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

const u = $('Telegram Trigger').first().json;
let out;
if (u.callback_query) {
  const cq = u.callback_query;
  const m = /^(ap|rj|cx|cy|nx|ch|ok|r[1-5]|ub)\|(.{1,60})$/.exec(cq.data || '');
  out = { kind: 'callback', chat_id: String((cq.message && cq.message.chat && cq.message.chat.id) || cq.from.id), from_id: String(cq.from.id), username: cq.from.username || '', callback_id: cq.id, data: cq.data || '', text: '', first_name: cq.from.first_name || '', lookup_request_id: m ? m[2] : '__none__', message_id: cq.message ? cq.message.message_id : 0, message_text: (cq.message && cq.message.text) || '', contact_phone: '', contact_user_id: '' };
} else {
  const m = u.message || u.edited_message || {};
  const c = m.contact || null;
  out = { kind: 'message', chat_id: m.chat ? String(m.chat.id) : '', from_id: m.from ? String(m.from.id) : '', username: (m.from && m.from.username) || '', callback_id: '', data: '', text: (m.text || '').trim(), first_name: (m.from && m.from.first_name) || '', lookup_request_id: '__none__', message_id: 0, message_text: '', contact_phone: c ? String(c.phone_number || '') : '', contact_user_id: c && c.user_id ? String(c.user_id) : '' };
}
// --- Language: chosen on /start (🇦🇲 / 🇬🇧 / 🇷🇺) and remembered per chat in clinic_user_langs.
const LP = $('Lang pack').first().json;
const L = Object.assign({}, LP.langs);
const CHOICE = { '🇦🇲 Հայերեն': 'hy', '🇬🇧 English': 'en', '🇷🇺 Русский': 'ru' };
out.ask_lang = false; out.set_lang = '';
if (out.kind === 'message' && CHOICE[out.text]) { out.set_lang = CHOICE[out.text]; L[out.chat_id] = out.set_lang; out.text = '/start'; }
else if (out.kind === 'message' && out.chat_id && (/^\/start(@\w+)?(\s|$)/.test(out.text) || !L[out.chat_id])) out.ask_lang = true;
out.lang = L[out.chat_id] || 'hy';
// Buttons tapped in English / Russian are turned back into the Armenian labels the rest of the bot understands.
if (out.lang !== 'hy' && out.text && !out.set_lang) {
  const t2 = (LP.R[out.lang] || []).reduce((a, p) => a.split(p[0]).join(p[1]), out.text);
  if (!/[A-Za-zА-Яа-яЁё]/.test(t2)) out.text = t2;
}
out.L = L; out.P = LP.P; out.T = LP.P[out.lang] || [];
// Doctor info buttons read "ℹ️ Արամի մասին"; Route expects "ℹ️ Արամ", so turn the genitive back into the first name.
const GEN = { 'Արամի': 'Արամ', 'Անիի': 'Անի', 'Լիլիթի': 'Լիլիթ', 'Նարեկի': 'Նարեկ', 'Մարիամի': 'Մարիամ', 'Դավթի': 'Դավիթ' };
const info = /^ℹ️ (\S+) մասին$/.exec(out.text || '');
if (info) out.text = 'ℹ️ ' + (GEN[info[1]] || info[1].replace(/ի$/, ''));
return [{ json: out }];
