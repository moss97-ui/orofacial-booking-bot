// Builds the staff reports: dashboard, today / tomorrow / next 7 days, pending requests.
const r = $('Route').first().json;
const names = {};
JSON.parse(r.staff_doctors || '[]').forEach(d => { names[d.k] = d.n; });
const rows = $('Load all bookings').all().map(i => i.json).filter(x => x && x.request_id && names[x.doctor_key]);
const H = 3600e3, now = Date.now();
const ymd = ms => new Date(ms + 4 * H).toISOString().slice(0, 10);
const today = ymd(now), tomorrow = ymd(now + 24 * H), weekEnd = ymd(now + 7 * 24 * H), weekAgo = now - 7 * 24 * H;
const DAYS = ['Կիր', 'Երկ', 'Երք', 'Չրք', 'Հնգ', 'Ուրբ', 'Շբթ'];
const dayOf = x => String(x.slot_start).slice(0, 10);
const dayLabel = d => d.slice(8, 10) + '.' + d.slice(5, 7) + ' ' + DAYS[new Date(d + 'T12:00:00Z').getUTCDay()];
const byTime = (a, b) => String(a.slot_start) < String(b.slot_start) ? -1 : 1;
const approved = rows.filter(x => x.status === 'approved').sort(byTime);
const pending = rows.filter(x => x.status === 'pending' && Date.parse(x.expires_at) > now && Date.parse(x.slot_start) > now).sort(byTime);
const who = x => x.patient_full_name || x.patient_name || '—';
const line = x => '• ' + String(x.slot_start).slice(11, 16) + '–' + String(x.slot_end).slice(11, 16) + ' · ' + names[x.doctor_key]
  + '\n   ' + who(x) + ' · ' + (x.service || '—')
  + '\n   ☎ ' + (x.patient_phone || '—') + (x.patient_confirmed ? ' · ✅ հաստատել է' : '') + ' · ' + x.request_id;
function dayList(day, title) {
  const xs = approved.filter(x => dayOf(x) === day);
  return title + ' — ' + dayLabel(day) + '\nԸնդամենը՝ ' + xs.length + ' այց' + (xs.length ? '\n\n' + xs.map(line).join('\n') : '\n\nԱյցեր չկան։');
}
let text = '';
if (r.report === 'today') text = '📅 ' + dayList(today, 'Այսօր');
else if (r.report === 'tomorrow') text = '📆 ' + dayList(tomorrow, 'Վաղը');
else if (r.report === 'week') {
  const xs = approved.filter(x => dayOf(x) >= today && dayOf(x) < weekEnd && Date.parse(x.slot_end) > now);
  const days = [...new Set(xs.map(dayOf))];
  text = '🗓 Առաջիկա 7 օրը\nԸնդամենը՝ ' + xs.length + ' այց' + (xs.length ? '' : '\n\nԱյցեր չկան։');
  days.forEach(d => { text += '\n\n▫️ ' + dayLabel(d) + ' (' + xs.filter(x => dayOf(x) === d).length + ')\n' + xs.filter(x => dayOf(x) === d).map(line).join('\n'); });
} else if (r.report === 'pending') {
  text = '⏳ Սպասող հայտեր՝ ' + pending.length + (pending.length ? '\nՅուրաքանչյուր հայտ ուղարկվում է առանձին՝ հաստատելու կամ մերժելու կոճակներով։' : '\n\nՍպասող հայտեր չկան։');
} else {
  const todayX = approved.filter(x => dayOf(x) === today);
  const left = todayX.filter(x => Date.parse(x.slot_end) > now);
  const tomX = approved.filter(x => dayOf(x) === tomorrow);
  const weekX = approved.filter(x => dayOf(x) >= today && dayOf(x) < weekEnd && Date.parse(x.slot_end) > now);
  const cancelled = rows.filter(x => x.status === 'cancelled' && Date.parse(x.updatedAt || x.createdAt) > weekAgo).length;
  const rejected = rows.filter(x => x.status === 'rejected' && Date.parse(x.updatedAt || x.createdAt) > weekAgo).length;
  const rated = rows.filter(x => Number(x.rating) > 0 && Date.parse(x.slot_start) > now - 30 * 24 * H);
  const low = rated.filter(x => Number(x.rating) <= 3).length;
  const per = Object.keys(names).map(k => '   ' + names[k] + '՝ ' + weekX.filter(x => x.doctor_key === k).length).join('\n');
  const next = approved.filter(x => Date.parse(x.slot_start) > now).slice(0, 3);
  text = '📊 Վահանակ — ' + dayLabel(today) + ', ' + new Date(now + 4 * H).toISOString().slice(11, 16)
    + '\n\n📅 Այսօր՝ ' + todayX.length + ' այց (մնացել է՝ ' + left.length + ', գալը հաստատել են՝ ' + todayX.filter(x => x.patient_confirmed).length + ')'
    + '\n📆 Վաղը՝ ' + tomX.length + ' այց'
    + '\n🗓 Առաջիկա 7 օրը՝ ' + weekX.length + ' այց'
    + '\n⏳ Սպասող հայտեր՝ ' + pending.length
    + '\n❌ Վերջին 7 օրում՝ չեղարկված ' + cancelled + ', մերժված ' + rejected
    + '\n⭐ Գնահատական (վերջին 30 օր)՝ ' + (rated.length ? (rated.reduce((a, x) => a + Number(x.rating), 0) / rated.length).toFixed(1) + '/5 (' + rated.length + ' գնահատական' + (low ? ', ցածր՝ ' + low : '') + ')' : 'դեռ չկա')
    + '\n\n👨‍⚕️ Առաջիկա 7 օրը ըստ բժիշկների՝\n' + per
    + '\n\n⏭ Հաջորդ այցերը՝' + (next.length ? '\n' + next.map(x => '• ' + dayLabel(dayOf(x)) + ' ' + String(x.slot_start).slice(11, 16) + ' · ' + names[x.doctor_key] + ' · ' + who(x)).join('\n') : ' չկան');
}
if (text.length > 3900) text = text.slice(0, 3850) + '\n… (ցուցակը կրճատված է)';
const cards = r.report === 'pending' ? pending.slice(0, 15).map(x => ({
  request_id: x.request_id,
  text: '⏳ Սպասող հայտ\nՀայտ՝ ' + x.request_id + '\nՊացիենտ՝ ' + who(x) + (x.telegram_username ? ' (@' + x.telegram_username + ')' : '') + '\nՀեռախոս՝ ' + (x.patient_phone || '—') + '\nԾառայություն՝ ' + (x.service || '—') + '\nԲժիշկ՝ ' + names[x.doctor_key] + '\nԱմսաթիվ՝ ' + dayOf(x) + '\nԺամ՝ ' + String(x.slot_start).slice(11, 16) + '–' + String(x.slot_end).slice(11, 16) + ' (Երևան)\nՀայտը վավեր է մինչև ' + ymd(Date.parse(x.expires_at)) + ' ' + new Date(Date.parse(x.expires_at) + 4 * H).toISOString().slice(11, 16) + '։'
})) : [];
return [{ json: { text, cards, has_cards: cards.length > 0 } }];