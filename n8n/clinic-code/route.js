// n8n Code node: "Route" (workflow "Clinic - Booking bot")
// Read-only copy for browsing. The real code lives inside Clinic-Booking-bot.workflow.json.

// Decides what to do with this Telegram update. No external calls here.
const p = $('Parse update').first().json;
const s = $('Load patient session').all().map(i => i.json).find(r => r && r.chat_id) || {};
const doctors = $('Load doctors').all().map(i => i.json).filter(r => r && r.doctor_key && r.active !== false);
const req = $('Load booking request').all().map(i => i.json).find(r => r && r.request_id) || null;
const now = Date.now();
const L = { chooseDoctor: '👨‍⚕️ Ընտրել բժիշկ', help: '🩺 Ընտրել ըստ ծառայության', general: 'Ընդհանուր խորհրդատվություն', pediatric: 'Մանկական ստոմատոլոգիա', ortho: 'Օրթոդոնտիա', otherDate: 'Այլ ամսաթիվ', restart: 'Սկսել սկզբից', home: '🏠 Գլխավոր մենյու', end: '✖️ Ավարտել', yesCancel: 'Այո, չեղարկել հայտը', noWait: 'Ոչ, սպասել', myBookings: '📋 Իմ ամրագրումները', back: '⬅️ Հետ', otherDay: '📅 Այլ օր', otherTime: '🕐 Այլ ժամ', guide: '❓ Ինչպես օգտվել', contact: '📞 Կապ կլինիկայի հետ', waitlist: '🔔 Սպասման ցուցակ' };
const HOME = '«🏠 Գլխավոր մենյու»';
const SERVICE = { general: 'Ընդհանուր խորհրդատվություն', pediatric: 'Մանկական ստոմատոլոգիա', orthodontics: 'Օրթոդոնտիա', surgery: 'Ատամնաբուժական վիրաբուժություն' };
// Visit length in minutes for each service. The slot search looks for a free gap this long.
const DURATION = { [SERVICE.general]: 30, [SERVICE.pediatric]: 30, [SERVICE.orthodontics]: 60, [SERVICE.surgery]: 90 };
// Why the patient is coming. Asked right after the doctor is chosen; it decides the visit length.
const REASONS = [
  { key: 'consult', label: '🩺 Խորհրդատվություն', name: 'Խորհրդատվություն / զննում', min: 30, price: '5 000 ֏', spec: ['general', 'pediatric', 'orthodontics', 'surgery'] },
  { key: 'pain', label: '⚡ Սուր ցավ', name: 'Սուր ցավ (շտապ այց)', min: 30, price: '8 000 ֏-ից', spec: ['general', 'pediatric', 'orthodontics', 'surgery'] },
  { key: 'treat', label: '🦷 Ատամի բուժում', name: 'Ատամի բուժում (կարիես, լցոնում)', min: 60, price: '15 000 ֏-ից', spec: ['general', 'pediatric'] },
  { key: 'clean', label: '🪥 Մասնագիտական մաքրում', name: 'Մասնագիտական մաքրում', min: 60, price: '20 000 ֏', spec: ['general'] },
  { key: 'ortho', label: '😁 Օրթոդոնտիկ բուժում', name: 'Օրթոդոնտիկ բուժում (բրեկետներ, կապեր)', min: 60, price: '30 000 ֏-ից', spec: ['orthodontics'] },
  { key: 'surgery', label: '🔧 Հեռացում / վիրահատություն', name: 'Ատամի հեռացում / վիրահատություն', min: 90, price: '25 000 ֏-ից', spec: ['surgery'] }
];
// One service line: name, length and (sample) price.
const svcLine = x => '• ' + x.label + ' — ' + x.min + ' րոպե · ' + x.price;
const PRICE_NOTE = 'Գները նախնական են․ վերջնական արժեքը բժիշկը կասի զննումից հետո։';
const reasonsFor = d => REASONS.filter(x => x.spec.includes(d.specialty));
const reasonOf = (d, key) => reasonsFor(d).find(x => x.key === key) || null;
const STATUS_HY = { pending: 'սպասում է', approving: 'մշակվում է', approved: 'հաստատված է', rejected: 'մերժված է', expired: 'ժամկետանց է', cancelled: 'չեղարկված է', conflict: 'ժամը զբաղված է', failed: 'սխալ' };
const NO_APPROVER = 'Ներողություն, այս բժշկի հաստատման կապը դեռ կարգավորված չէ, ուստի հայտ ուղարկել հնարավոր չէ։ Ընտրեք այլ բժշկի կամ փորձեք ավելի ուշ։';
const RESTART_MSG = 'Խնդրում ենք սկսել նորից՝ սեղմելով ' + HOME + '։';
const ymd = ms => new Date(ms + 4 * 3600e3).toISOString().slice(0, 10);
const hhmm = ms => new Date(ms + 4 * 3600e3).toISOString().slice(11, 16);
const today = ymd(now);
const out = { action: 'reply', home_kb: false, kind: p.kind, chat_id: p.chat_id, from_id: p.from_id, username: p.username || '', callback_id: p.callback_id || '', callback_text: '', text: '', first_name: p.first_name || '',
  old_request_id: s.request_id || '__none__', request_id: '__none__', doctor_key: '', doctor_name: '', calendar_id: '', filter_by_name: false, approver_chat_id: '',
  date: '', date_next: '', selected_time: '', mode: '', slot_start: '', slot_end: '', slot_key: '', expires_at: '', patient_chat_id: '', patient_name: '', full_name: s.full_name || '', saved_name: s.full_name || '', phone: '', saved_phone: s.phone || '', service: '', doctor_message: '',
  replace_request_id: s.replace_request_id || '', replaces_request_id: '', old_status: '', calendar_event_id: '', card_text: '', reset_session: false, menu_stage: '', quick_rebook: s.quick_rebook || '', duration_min: 30, visit_reason: s.visit_reason || '', visit_label: '', reason_labels: [], reason_text: '', month_offset: -1, staff_doctors: '[]', staff_menu_text: '', report: '', rating: 0, block_step: '', block_labels: [], wl_date: '' };
const MONTHS = ['Հունվար', 'Փետրվար', 'Մարտ', 'Ապրիլ', 'Մայիս', 'Հունիս', 'Հուլիս', 'Օգոստոս', 'Սեպտեմբեր', 'Հոկտեմբեր', 'Նոյեմբեր', 'Դեկտեմբեր'];
const MON = ['հունվ', 'փետ', 'մարտ', 'ապր', 'մայ', 'հունիս', 'հուլ', 'օգոս', 'սեպ', 'հոկ', 'նոյ', 'դեկ'];
const curMonth = +today.slice(5, 7) - 1, nextMonth = (curMonth + 1) % 12;
const done = () => [{ json: out }];
// reply: keeps the current buttons (mid-step errors). replyHome: shows Main menu / End buttons.
const reply = t => { out.action = 'reply'; out.text = t; return done(); };
const replyHome = t => { out.action = 'reply'; out.home_kb = true; out.text = t; return done(); };
function docCtx(d) {
  out.doctor_key = d.doctor_key; out.doctor_name = d.doctor_name; out.calendar_id = d.calendar_id || '';
  out.approver_chat_id = String(d.approver_chat_id || '');
  // Several doctors sharing one calendar -> events are told apart by the doctor's name in the title.
  out.filter_by_name = doctors.filter(x => x.calendar_id && x.calendar_id === d.calendar_id).length > 1;
  const rs = reasonOf(d, out.visit_reason);
  out.duration_min = rs ? rs.min : (DURATION[serviceFor(d)] || 30);
  out.visit_label = serviceFor(d);
}
// Shows the visit-reason buttons for the chosen doctor.
function askReason(d) {
  out.visit_reason = ''; out.quick_rebook = ''; docCtx(d);
  const rs = reasonsFor(d);
  out.reason_labels = [0, 1, 2, 3].map(i => rs[i] ? rs[i].label : '·');
  out.reason_text = 'Բժիշկ՝ ' + d.doctor_name + '\nԽնդրում ենք ընտրել այցի նպատակը։ Դրանից կախված կհաշվարկենք այցի տևողությունը և կառաջարկենք համապատասխան ազատ ժամերը։\n\n' + rs.map(svcLine).join('\n') + '\n\n' + PRICE_NOTE;
  out.action = 'ask_reason'; return done();
}
function setDate(dt) { out.date = dt; const n = new Date(dt + 'T12:00:00Z'); n.setUTCDate(n.getUTCDate() + 1); out.date_next = n.toISOString().slice(0, 10); }
function checkDate(t) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t)) return 'Ընտրեք ամսաթիվը կոճակներից կամ գրեք ՏՏՏՏ-ԱԱ-ՕՕ ձևաչափով, օրինակ՝ 2026-10-12։';
  const d = new Date(t + 'T12:00:00Z');
  if (!Number.isFinite(d.getTime()) || d.toISOString().slice(0, 10) !== t) return 'Այդ ամսաթիվը գոյություն չունի։ Խնդրում ենք ընտրել վավեր ամսաթիվ։';
  if (t < today) return 'Ընտրեք այսօրվա կամ ապագա ամսաթիվ։';
  if (t > ymd(now + 62 * 86400e3)) return 'Ամրագրումը հնարավոր է առավելագույնը 2 ամիս առաջ։ Ընտրեք ավելի մոտ ամսաթիվ։';
  if ([0, 6].includes(d.getUTCDay()) && !['2026-10-10'].includes(t)) return 'Կլինիկան աշխատում է երկուշաբթիից ուրբաթ։ Ընտրեք աշխատանքային օր։';
  return '';
}
function normTime(t) {
  const m = /^(\d{1,2})[:.](\d{2})$/.exec(t) || /^(\d{2})(\d{2})$/.exec(t);
  if (!m) return '';
  const h = +m[1], mi = +m[2];
  if (h > 23 || mi > 59) return '';
  return String(h).padStart(2, '0') + ':' + String(mi).padStart(2, '0');
}
// Phone: accepts 091 123456, +374 91 123456, 37491123456, 0037491123456 or other international numbers.
function normPhone(raw) {
  let x = String(raw || '').replace(/[\s\-().]/g, '');
  if (x.startsWith('00')) x = '+' + x.slice(2);
  if (/^0\d{8}$/.test(x)) x = '+374' + x.slice(1);
  else if (/^\d{8}$/.test(x)) x = '+374' + x;
  else if (/^\d{9,15}$/.test(x)) x = '+' + x;
  return /^\+\d{8,15}$/.test(x) ? x : '';
}
// Service: the visit type chosen in the help menu if it fits this doctor, otherwise the doctor's own specialty.
function serviceFor(d) {
  const rs = reasonOf(d, out.visit_reason);
  if (rs) return rs.name;
  const chosen = s.service || '';
  const fits = (chosen === SERVICE.general && d.specialty === 'general') || (chosen === SERVICE.pediatric && d.specialty === 'pediatric') || (chosen === SERVICE.orthodontics && d.specialty === 'orthodontics');
  return fits ? chosen : (SERVICE[d.specialty] || '');
}
function buildRequest(d, hm, fullName, phone) {
  setDate(s.appointment_date); out.selected_time = hm; out.mode = 'time'; out.action = 'check_availability';
  out.full_name = fullName; out.patient_name = fullName; out.phone = phone; out.service = serviceFor(d);
  out.replaces_request_id = s.replace_request_id || '';
  out.slot_start = s.appointment_date + 'T' + hm + ':00+04:00';
  const startMs = Date.parse(out.slot_start);
  out.slot_end = s.appointment_date + 'T' + hhmm(startMs + out.duration_min * 60000) + ':00+04:00';
  out.slot_key = d.doctor_key + '|' + out.slot_start;
  // Readable code: month+day - time - 3 random digits, e.g. 1015-1330-482
  out.request_id = s.appointment_date.slice(5, 7) + s.appointment_date.slice(8, 10) + '-' + hm.replace(':', '') + '-' + String(Math.floor(100 + Math.random() * 900));
  const exp = Math.min(now + 2 * 3600e3, startMs);
  out.expires_at = new Date(exp).toISOString();
  out.patient_chat_id = p.chat_id;
  const who = fullName + (p.username ? ' (@' + p.username + ')' : '');
  // A time change shows the old date/time (decoded from the old request code "MMDD-HHMM-xxx") instead of the code.
  const om = /^(\d{2})(\d{2})-(\d{2})(\d{2})-/.exec(out.replaces_request_id || '');
  const oldWhen = om ? (+today.slice(0, 4) + (+om[1] < +today.slice(5, 7) ? 1 : 0)) + '-' + om[1] + '-' + om[2] + ', ' + om[3] + ':' + om[4] : '';
  out.doctor_message = (out.replaces_request_id ? '🔁 Ժամի փոփոխության հայտ' + (oldWhen ? '\nՆախկին ժամ՝ ' + oldWhen + '\nՆոր ժամ՝ ' + s.appointment_date + ', ' + hm + '–' + out.slot_end.slice(11, 16) + ' (Երևան)' : '') : '🦷 Նոր ամրագրման հայտ') + '\nՀայտ՝ ' + out.request_id + '\nՊացիենտ՝ ' + who + '\nՀեռախոս՝ ' + phone + '\nԾառայություն՝ ' + out.service + '\nԲժիշկ՝ ' + d.doctor_name + (oldWhen ? '' : '\nԱմսաթիվ՝ ' + s.appointment_date + '\nԺամ՝ ' + hm + '–' + out.slot_end.slice(11, 16) + ' (Երևան)') + (out.replaces_request_id ? '\n⚠️ Հաստատելու դեպքում նախկին ժամը (' + (oldWhen || 'նախորդ ամրագրումը') + ') ինքնաբերաբար կչեղարկվի։' : '') + '\nՀայտը վավեր է մինչև ' + ymd(exp) + ' ' + hhmm(exp) + '։';
  return done();
}
function fillFromRequest(r, d) {
  out.visit_reason = (REASONS.find(x => x.name === r.service) || {}).key || '';
  docCtx(d);
  out.request_id = r.request_id; out.patient_chat_id = String(r.chat_id);
  out.patient_name = r.patient_full_name || r.patient_name || ''; out.full_name = out.patient_name;
  out.phone = r.patient_phone || ''; out.service = r.service || ''; out.username = r.telegram_username || '';
  out.slot_start = r.slot_start; out.slot_end = r.slot_end; out.slot_key = r.slot_key;
  out.selected_time = String(r.slot_start).slice(11, 16); setDate(String(r.slot_start).slice(0, 10));
  const len = Math.round((Date.parse(r.slot_end) - Date.parse(r.slot_start)) / 60000); if (len > 0) out.duration_min = len;
  out.old_status = r.status; out.calendar_event_id = r.calendar_event_id || ''; out.replaces_request_id = r.replaces_request_id || '';
}

// ----- button taps under a message (doctor approval or patient booking card) -----
if (p.kind === 'callback') {
  const deny = t => { out.action = 'deny_callback'; out.callback_text = t; return done(); };
  const m = /^(ap|rj|cx|cy|nx|ch|ok|r[1-5]|ub)\|/.exec(p.data || '');
  // Staff undo of a blocked day/time: "ub|<doctor_key>|<calendar event id>".
  if (m && m[1] === 'ub') {
    const parts = String(p.data).split('|');
    const bd = doctors.find(x => x.doctor_key === parts[1]);
    if (!bd || !parts[2] || String(bd.approver_chat_id) !== p.from_id) return deny('Այս գործողությունը հասանելի չէ։');
    docCtx(bd); out.calendar_event_id = parts[2]; out.card_text = String(p.message_text || '').split('\n\n')[0];
    out.action = 'staff_unblock'; out.callback_text = 'Փակումը չեղարկվում է…'; return done();
  }
  if (!m || !req) return deny('Հայտը չի գտնվել։');
  const verb = m[1];
  const d = doctors.find(x => x.doctor_key === req.doctor_key);
  if (!d) return deny('Բժիշկը չի գտնվել։');
  out.card_text = String(p.message_text || '').split('\n\n')[0];
  if (verb === 'ap' || verb === 'rj') {
    if (!d.approver_chat_id || String(d.approver_chat_id) !== p.from_id) return deny('Դուք իրավասու չեք մշակելու այս հայտը։');
    fillFromRequest(req, d); out.mode = 'approve';
    if (req.status !== 'pending') return deny('Այս հայտն արդեն մշակված է՝ ' + (STATUS_HY[req.status] || req.status) + '։');
    if (verb === 'rj') { out.action = 'reject'; out.callback_text = 'Հայտը մերժվում է…'; return done(); }
    if (!(Date.parse(req.expires_at) > now) || !(Date.parse(req.slot_start) > now)) { out.action = 'expire'; out.callback_text = 'Հայտի ժամկետը լրացել է։ Այցը չի ստեղծվել։'; return done(); }
    out.action = 'approve'; out.callback_text = 'Ստուգում եմ ժամը և ստեղծում այցը…'; return done();
  }
  // Patient actions: only the person who made the booking may use them.
  if (String(req.chat_id) !== p.from_id) return deny('Այս ամրագրումը Ձերը չէ։');
  fillFromRequest(req, d);
  const note = t => { out.action = 'patient_note'; out.text = t; return done(); };
  // Rating after the visit: "r1|<request>" … "r5|<request>".
  if (/^r[1-5]$/.test(verb)) {
    if (req.status !== 'approved') return note('ℹ️ Այս այցը չի կայացել, ուստի գնահատել հնարավոր չէ։');
    if (Number(req.rating) > 0) return note('ℹ️ Դուք արդեն գնահատել եք այս այցը (' + req.rating + '/5)։ Շնորհակալություն։');
    out.rating = Number(verb[1]); out.action = 'rate'; out.callback_text = 'Շնորհակալություն գնահատականի համար'; return done();
  }
  const active = ['approved', 'pending'].includes(req.status) && Date.parse(req.slot_start) > now;
  if (!active) return note('ℹ️ Այս ամրագրումն այլևս ակտիվ չէ (' + (STATUS_HY[req.status] || req.status) + ')։');
  if (verb === 'nx') return note('👍 Այցը մնում է ուժի մեջ։');
  if (verb === 'ok') {
    if (req.status !== 'approved') return note('ℹ️ Այս հայտը դեռ սպասում է բժշկի հաստատմանը։');
    out.action = 'patient_confirm'; out.callback_text = 'Շնորհակալություն'; out.text = '✅ Շնորհակալություն, Ձեր ներկայությունը հաստատված է։ Սպասում ենք Ձեզ։'; return done();
  }
  if (verb === 'cx') { out.action = 'patient_cancel_ask'; return done(); }
  if (verb === 'cy') { out.action = 'patient_cancel'; out.callback_text = 'Չեղարկում եմ…'; out.reset_session = s.request_id === req.request_id; return done(); }
  if (verb === 'ch') { out.quick_rebook = 'yes'; out.action = 'change_booking'; out.callback_text = 'Ընտրեք նոր ամսաթիվ'; out.date = ''; return done(); }
  return deny('Անհայտ գործողություն։');
}

// ----- ordinary message -----
if (!p.chat_id) return [];
const t = p.text;
// ----- staff (approver) menu: dashboard and reservation lists -----
const staffDocs = doctors.filter(d => d.approver_chat_id && String(d.approver_chat_id) === String(p.chat_id));
const STAFF_GUIDE = '📖 Ուղեցույց բժշկի / ադմինիստրատորի համար\n\n'
  + '1️⃣ Նոր հայտ\nԵրբ պացիենտը ժամ է ընտրում, Դուք ստանում եք հաղորդագրություն՝ անուն, հեռախոս, բժիշկ, օր և ժամ։\n\n'
  + '2️⃣ Հաստատել կամ մերժել\nՍեղմեք հաղորդագրության տակի կոճակը․\n✅ Հաստատել — այցը կավելանա օրացույցում, պացիենտը կստանա հաստատում և հիշեցումներ։\n❌ Մերժել — պացիենտին կառաջարկվի ընտրել այլ օր կամ ժամ։\n\n'
  + '3️⃣ Մենյուի կոճակները\n🚫 Փակել օր / ժամ — արձակուրդ, ընդմիջում կամ զբաղված ժամ․ այդ ժամերը պացիենտներին չեն առաջարկվի\n📊 Վահանակ — ամփոփ պատկեր մեկ հայացքով\n📅 Այսօրվա այցերը — այսօրվա ցուցակը\n📆 Վաղվա այցերը — վաղվա ցուցակը\n🗓 Առաջիկա 7 օրը — շաբաթվա այցերը\n⏳ Սպասող հայտեր — դեռ չպատասխանված հայտերը՝ կրկին հաստատելու կամ մերժելու կոճակներով\n🧑 Ամրագրել որպես պացիենտ — տեսնել բոտը պացիենտի աչքերով\n\n'
  + '💡 Մենյուն կորե՞լ է։ Ուղարկեք /start կամ սեղմեք 🏠։\n'
  + '💡 Խորհուրդ՝ պատասխանեք հայտերին որքան հնարավոր է շուտ, որպեսզի ժամը չզբաղեցվի ուրիշի կողմից։';
const S = { block: '🚫 Փակել օր / ժամ', whole: '🚫 Ամբողջ օրը', guide: '❓ Ուղեցույց', dash: '📊 Վահանակ', today: '📅 Այսօրվա այցերը', tomorrow: '📆 Վաղվա այցերը', week: '🗓 Առաջիկա 7 օրը', pending: '⏳ Սպասող հայտեր', patient: '🧑 Ամրագրել որպես պացիենտ', staff: '👨‍⚕️ Բժշկի մենյու' };
if (staffDocs.length) {
  out.staff_doctors = JSON.stringify(staffDocs.map(d => ({ k: d.doctor_key, n: d.doctor_name })));
  out.staff_menu_text = '👨‍⚕️ Բժշկի / ադմինիստրատորի մենյու\nՁեր բժիշկները՝ ' + staffDocs.map(d => d.doctor_name).join(', ') + '\n\nԸնտրեք բաժինը ստորև։\nԱռաջին անգա՞մ եք․ սեղմեք «' + S.guide + '»։\nՊացիենտի մենյուն փորձարկելու համար սեղմեք «' + S.patient + '»։ Այստեղ վերադառնալու համար ուղարկեք /start։';
  if (/^\/(start|staff)(@\w+)?(\s|$)/.test(t) || t === S.staff || t === L.home || t === L.restart) { out.action = 'staff_menu'; return done(); }
  const rep = { [S.dash]: 'dash', [S.today]: 'today', [S.tomorrow]: 'tomorrow', [S.week]: 'week', [S.pending]: 'pending' }[t];
  if (rep) { out.action = 'staff_report'; out.report = rep; return done(); }
  if (t === S.patient) { out.action = 'welcome'; return done(); }
  if (t === S.guide || /^\/help(@\w+)?$/.test(t || '')) return reply(STAFF_GUIDE);
  // Block a day or a time range for a doctor: doctor -> date -> whole day / time range -> calendar event "⛔ Փակ".
  const SHORT = ['Կիր', 'Երկ', 'Երք', 'Չրք', 'Հնգ', 'Ուրբ', 'Շբթ'];
  const askDoc = () => { out.action = 'staff_block_ask'; out.block_step = 'doctor'; out.menu_stage = 'staff_block_doctor';
    out.block_labels = [0, 1, 2, 3, 4, 5].map(i => staffDocs[i] ? staffDocs[i].doctor_name : '·');
    out.text = '🚫 Ժամերի փակում\nՈ՞ր բժշկի համար եք փակում օրը կամ ժամը։'; return done(); };
  const askDate = d => { docCtx(d); out.action = 'staff_block_ask'; out.block_step = 'date'; out.menu_stage = 'staff_block_date';
    const labels = []; for (let i = 0; labels.length < 8 && i < 20; i++) { const ms = now + i * 86400e3, dd = ymd(ms), w = new Date(dd + 'T12:00:00Z').getUTCDay(); if (w !== 0 && w !== 6) labels.push(MON[+dd.slice(5, 7) - 1] + ' ' + (+dd.slice(8, 10)) + ' ' + SHORT[w]); }
    out.block_labels = labels;
    out.text = '🚫 Բժիշկ՝ ' + d.doctor_name + '\nԸնտրեք օրը ստորև կամ գրեք ամսաթիվը, օրինակ՝ 25.10'; return done(); };
  const askTime = (d, dt) => { docCtx(d); setDate(dt); out.action = 'staff_block_ask'; out.block_step = 'time'; out.menu_stage = 'staff_block_time';
    out.text = '🚫 Բժիշկ՝ ' + d.doctor_name + '\nՕր՝ ' + dt + ' (' + SHORT[new Date(dt + 'T12:00:00Z').getUTCDay()] + ')\n\nԸնտրեք՝ ամբողջ օրը կամ միջակայքը, կամ գրեք Ձեր ժամերը, օրինակ՝ 14:00-16:00'; return done(); };
  if (t === S.block) return staffDocs.length === 1 ? askDate(staffDocs[0]) : askDoc();
  const bst = String(s.stage || '');
  if (bst.startsWith('staff_block_')) {
    if (t === L.back) { out.action = 'staff_menu'; return done(); }
    const bdoc = staffDocs.find(d => d.doctor_key === s.doctor_key);
    if (bst === 'staff_block_doctor') {
      const d = staffDocs.find(x => x.doctor_name === t);
      return d ? askDate(d) : reply('Խնդրում ենք ընտրել բժշկին կոճակներից։');
    }
    if (bst === 'staff_block_date' && bdoc) {
      let dt = '';
      const lm = /^(\S+) (\d{1,2})(?: |$)/.exec(t || ''), dm2 = /^(\d{1,2})[.\/](\d{1,2})(?:[.\/](\d{4}))?$/.exec(t || ''), iso = /^\d{4}-\d{2}-\d{2}$/.test(t || '') ? t : '';
      const mk = (dd, mm, yy) => (yy || (+today.slice(0, 4) + (mm < +today.slice(5, 7) ? 1 : 0))) + '-' + String(mm).padStart(2, '0') + '-' + String(dd).padStart(2, '0');
      if (iso) dt = iso; else if (dm2) dt = mk(+dm2[1], +dm2[2], dm2[3] ? +dm2[3] : 0); else if (lm && MON.indexOf(lm[1]) >= 0) dt = mk(+lm[2], MON.indexOf(lm[1]) + 1, 0);
      const ok = dt && new Date(dt + 'T12:00:00Z').toISOString().slice(0, 10) === dt;
      if (!ok) return reply('Չհասկացա ամսաթիվը։ Ընտրեք կոճակներից կամ գրեք, օրինակ՝ 25.10');
      if (dt < today) return reply('Այդ օրն արդեն անցել է։ Ընտրեք այսօրվա կամ ապագա օր։');
      if (dt > ymd(now + 92 * 86400e3)) return reply('Կարելի է փակել առավելագույնը 3 ամիս առաջ։');
      return askTime(bdoc, dt);
    }
    if (bst === 'staff_block_time' && bdoc && s.appointment_date) {
      let a = '', b = '';
      if (t === S.whole) { a = '00:00'; b = '23:59'; }
      else { const rm = /(\d{1,2})(?:[:.](\d{2}))?\s*[-–—]\s*(\d{1,2})(?:[:.](\d{2}))?/.exec(t || ''); if (rm) { a = normTime(rm[1] + ':' + (rm[2] || '00')); b = normTime(rm[3] + ':' + (rm[4] || '00')); } }
      if (!a || !b || b <= a) return reply('Գրեք ժամային միջակայքը այսպես՝ 14:00-16:00, կամ ընտրեք կոճակներից։');
      const dt = s.appointment_date;
      if (Date.parse(dt + 'T' + b + ':00+04:00') <= now) return reply('Այդ ժամն արդեն անցել է։ Ընտրեք ավելի ուշ ժամ։');
      docCtx(bdoc); setDate(dt);
      out.slot_start = dt + 'T' + a + ':00+04:00'; out.slot_end = dt + 'T' + b + ':00+04:00'; out.menu_stage = 'idle';
      out.text = '✅ Փակված է\nԲժիշկ՝ ' + bdoc.doctor_name + '\nՕր՝ ' + dt + '\nԺամ՝ ' + (t === S.whole ? 'ամբողջ օրը' : a + '–' + b)
        + '\n\nԱյս ժամերը պացիենտներին այլևս չեն առաջարկվի։ Արդեն ամրագրված այցերը ինքնաբերաբար չեն չեղարկվում։\nՍխալմամբ փակելու դեպքում սեղմեք ստորև։';
      out.staff_menu_text = 'Ի՞նչ եք ցանկանում անել հետո։';
      out.action = 'staff_block_create'; return done();
    }
  }
}
if (t === L.end) { out.action = 'end_chat'; return done(); }
if (t === L.noWait) return replyHome('Լավ, Ձեր հայտը մնում է ուժի մեջ։ Բժշկի պատասխանը կստանաք այստեղ։');
if (t === L.myBookings) { out.action = 'my_bookings'; return done(); }
if (t === L.contact || /^\/contact(@\w+)?$/.test(t || '')) { out.action = 'contact'; return done(); }
// Patient guide: a short, simple manual (main menu button or /help).
if (t === L.guide || /^\/help(@\w+)?$/.test(t || '')) return reply('📖 Ինչպես ամրագրել այց — 4 քայլ\n\n'
  + '1️⃣ Ընտրեք բժշկին\n«👨‍⚕️ Ընտրել բժիշկ» — եթե գիտեք՝ ում մոտ եք ուզում գնալ։\n«🩺 Ընտրել ըստ ծառայության» — եթե չգիտեք, բոտը կառաջարկի ճիշտ բժշկին։\nℹ️ կոճակով կարող եք կարդալ բժշկի մասին։\n\n'
  + '2️⃣ Ընտրեք այցի նպատակը\nՕրինակ՝ խորհրդատվություն կամ սուր ցավ։ Բոտը ինքը կհաշվի, թե որքան ժամանակ է պետք։\n\n'
  + '3️⃣ Ընտրեք ամիսը, օրը և ժամը\nՑույց են տրվում միայն ազատ ժամերը։\n\n'
  + '4️⃣ Գրեք Ձեր անունը և հեռախոսը\nՀայտը կուղարկվի բժշկին։ Երբ բժիշկը հաստատի, Դուք կստանաք հաղորդագրություն այստեղ, ինչպես նաև հիշեցում այցից առաջ (սեղմեք «✅ Կգամ»՝ հաստատելու համար) և կլինիկա հասնելու երթուղին։\n\n'
  + '📋 «Իմ ամրագրումները» — տեսնել, փոխել կամ չեղարկել Ձեր այցը։\n🔔 Ազատ ժամ չկա՞․ միացեք սպասման ցուցակին, և կտեղեկացնենք, երբ ժամ ազատվի։\n📞 «Կապ կլինիկայի հետ» — զանգ, Telegram, WhatsApp, Viber։\n\n'
  + '🔘 Օգտակար կոճակներ\n⬅️ Հետ — մեկ քայլ հետ\n🏠 Գլխավոր մենյու — սկսել սկզբից\n✖️ Ավարտել — փակել զրույցը\n\n'
  + '💡 Գրելու կարիք չկա․ պարզապես սեղմեք կոճակները։ Եթե բժիշկը չի կարող ընդունել ընտրված ժամին, Դուք կարող եք ընտրել այլ օր կամ ժամ։');
// Doctor info buttons ("ℹ️ Արամ") next to each doctor on the doctor lists: show a short profile and keep the same buttons.
const BIO = {
  aram: 'Ընդհանուր ստոմատոլոգ · 12 տարվա փորձ\nԱխտորոշում, կարիեսի բուժում, լցոնումներ, կանխարգելիչ զննումներ։',
  ani: 'Ընդհանուր ստոմատոլոգ · 8 տարվա փորձ\nԳեղագիտական վերականգնումներ, լցոնումներ, ատամների մաքրում։',
  lilit: 'Ընդհանուր ստոմատոլոգ · 6 տարվա փորձ\nԿարիեսի բուժում, մասնագիտական մաքրում, խորհրդատվություն։',
  narek: 'Օրթոդոնտ · 10 տարվա փորձ\nԿծվածքի շտկում, բրեկետ-համակարգեր, կապեր, ելուստներ։',
  mariam: 'Մանկական ստոմատոլոգ · 9 տարվա փորձ\nԵրեխաների ատամների բուժում և կանխարգելում՝ հանգիստ և ընկերական մթնոլորտում։',
  davit: 'Վիրաբույժ-ստոմատոլոգ · 15 տարվա փորձ\nԱտամների հեռացում, իմաստության ատամներ, վիրահատական միջամտություններ։'
};
const HOURS = { aram: 'Երկ–Ուրբ 09:00–15:00', ani: 'Երկ–Ուրբ 12:00–18:00', narek: 'Երկ–Հնգ 10:00–17:00, Ուրբ 10:00–16:00', mariam: 'Երկ–Ուրբ 09:00–16:00', davit: 'Երկ–Հնգ 11:00–18:00, Ուրբ 11:00–17:00', lilit: 'Երկ–Ուրբ 10:00–16:00' };
if (/^ℹ️ /.test(t || '')) {
  const di = doctors.find(d => 'ℹ️ ' + String(d.doctor_name).split(' ')[0] === t);
  if (di) return reply('👨‍⚕️ ' + di.doctor_name + '\n' + (BIO[di.doctor_key] || (SERVICE[di.specialty] || ''))
    + '\n\n🦷 Ծառայություններ և գներ՝\n' + reasonsFor(di).map(svcLine).join('\n') + '\n' + PRICE_NOTE
    + (HOURS[di.doctor_key] ? '\n\n🕘 Ընդունելության ժամեր՝ ' + HOURS[di.doctor_key] : '')
    + '\n\nԱմրագրելու համար սեղմեք «' + di.doctor_name + '» կոճակը։');
}
const SVC_ACTION = { [SERVICE.general]: 'service_general', [SERVICE.pediatric]: 'service_pediatric', [SERVICE.orthodontics]: 'service_ortho' };
// Back: return exactly one step, based on where the patient is now.
if (t === L.back) {
  const st = s.stage || '';
  const bd = doctors.find(d => d.doctor_key === s.doctor_key);
  if (st === 'awaiting_approval') { out.action = 'confirm_cancel'; return done(); }
  if (st === 'menu_service_doctors') { out.action = 'service_menu'; out.menu_stage = 'menu_services'; return done(); }
  if (bd && st === 'awaiting_month') {
    if (s.replace_request_id) { out.action = 'my_bookings'; return done(); }
    return askReason(bd);
  }
  if (bd && st === 'awaiting_date') {
    if (s.replace_request_id) { out.action = 'my_bookings'; return done(); }
    docCtx(bd); out.month_offset = -1; out.action = 'doctor_chosen'; return done();
  }
  if (bd && st === 'awaiting_reason') {
    const sa = SVC_ACTION[s.service || ''];
    out.action = sa || 'doctor_menu'; out.service = sa ? s.service : ''; out.menu_stage = sa ? 'menu_service_doctors' : 'menu_doctors';
    return done();
  }
  if (bd && st === 'awaiting_time') { docCtx(bd); out.month_offset = s.appointment_date && s.appointment_date.slice(0, 7) !== today.slice(0, 7) ? 1 : 0; out.action = 'doctor_chosen'; return done(); }
  if (bd && st === 'awaiting_name' && s.appointment_date) { docCtx(bd); setDate(s.appointment_date); out.mode = 'date'; out.action = 'check_availability'; return done(); }
  if (bd && st === 'awaiting_phone' && s.selected_time && s.appointment_date) { docCtx(bd); setDate(s.appointment_date); out.selected_time = s.selected_time; out.action = 'ask_name'; return done(); }
  out.action = 'welcome'; return done();
}
// After a rejection / taken slot / expiry: try again with the same doctor.
if (t === L.otherDay || t === L.otherTime) {
  if (s.stage === 'awaiting_approval') { out.action = 'confirm_cancel'; return done(); }
  const od = doctors.find(d => d.doctor_key === s.doctor_key);
  if (!od || !od.calendar_id) { out.action = 'welcome'; return done(); }
  docCtx(od); out.quick_rebook = 'yes';
  if (t === L.otherTime && s.appointment_date && !checkDate(s.appointment_date)) { setDate(s.appointment_date); out.mode = 'date'; out.action = 'check_availability'; return done(); }
  out.action = 'doctor_chosen'; return done();
}
// Waitlist: offered when there is no free date / time. Notified when a booking with this doctor is cancelled.
if (t === L.waitlist) {
  const wd = doctors.find(d => d.doctor_key === s.doctor_key);
  if (!wd || !['awaiting_month', 'awaiting_date', 'awaiting_time'].includes(s.stage)) return replyHome('Սպասման ցուցակին կարելի է միանալ բժիշկ և օր ընտրելիս, երբ ազատ ժամ չկա։');
  docCtx(wd); out.wl_date = s.stage === 'awaiting_time' && s.appointment_date ? s.appointment_date : '';
  out.patient_name = s.full_name || p.first_name || '';
  out.action = 'waitlist_join'; out.home_kb = true;
  out.text = '🔔 Դուք ավելացվեցիք սպասման ցուցակում\nԲժիշկ՝ ' + wd.doctor_name + '\nՕր՝ ' + (out.wl_date || 'ցանկացած')
    + '\n\nԵրբ այս բժշկի մոտ ժամ ազատվի, անմիջապես կտեղեկացնենք այստեղ։ Ժամը կստանա առաջինը ամրագրողը։';
  return done();
}
// Main menu while a request is still waiting: ask before cancelling it.
if ((t === L.home || t === L.restart) && s.stage === 'awaiting_approval') { out.action = 'confirm_cancel'; return done(); }
if (/^\/start(@\w+)?(\s|$)/.test(t) || t === L.restart || t === L.home || t === L.yesCancel) { out.action = 'welcome'; return done(); }
if (/^\/myid(@\w+)?$/.test(t)) return replyHome('Ձեր Telegram chat ID-ն՝ ' + p.chat_id);

// Phone step (a shared contact arrives without text, so this comes before the text check).
if (s.stage === 'awaiting_phone') {
  const nd = doctors.find(d => d.doctor_key === s.doctor_key);
  if (!nd || !s.selected_time || !s.appointment_date || !s.full_name) return replyHome(RESTART_MSG);
  docCtx(nd);
  if (t === L.otherDate) { out.action = 'doctor_chosen'; return done(); }
  if (p.contact_phone && p.contact_user_id && p.contact_user_id !== p.from_id) return reply('Խնդրում ենք կիսվել Ձեր սեփական համարով կամ գրել այն, օրինակ՝ +374 91 123456։');
  const phone = normPhone(p.contact_phone || t);
  if (!phone) return reply('Խնդրում ենք գրել ճիշտ հեռախոսահամար, օրինակ՝ +374 91 123456 կամ 091 123456, կամ սեղմել «📱 Կիսվել իմ համարով»։');
  if (!out.approver_chat_id) return replyHome(NO_APPROVER);
  return buildRequest(nd, s.selected_time, s.full_name, phone);
}
if (!t) return replyHome('Ես հասկանում եմ միայն տեքստային հաղորդագրություններ և կոճակներ։');

// Name step first, so a typed name is never mistaken for a menu button.
if (s.stage === 'awaiting_name') {
  const nd = doctors.find(d => d.doctor_key === s.doctor_key);
  if (!nd || !s.selected_time || !s.appointment_date) return replyHome(RESTART_MSG);
  docCtx(nd);
  if (t === L.otherDate) { out.action = 'doctor_chosen'; return done(); }
  const name = t.replace(/\s+/g, ' ').trim();
  if (name.length < 3 || name.length > 60 || !/^[\p{L}][\p{L}'’.-]*(?: [\p{L}][\p{L}'’.-]*)+$/u.test(name)) return reply('Խնդրում ենք գրել անունը և ազգանունը տառերով, օրինակ՝ Անի Պետրոսյան։');
  if (!out.approver_chat_id) return replyHome(NO_APPROVER);
  // Next: ask for a phone number.
  out.action = 'ask_phone'; out.full_name = name; out.selected_time = s.selected_time; setDate(s.appointment_date);
  return done();
}

const menu = { [L.chooseDoctor]: 'doctor_menu', [L.help]: 'service_menu', 'Ցանկանում եմ ընտրել բժշկին': 'doctor_menu', 'Չգիտեմ՝ ում ընտրել': 'service_menu', [L.general]: 'service_general', [L.pediatric]: 'service_pediatric', [L.ortho]: 'service_ortho' };
const MENU_SERVICE = { doctor_menu: '', service_general: SERVICE.general, service_pediatric: SERVICE.pediatric, service_ortho: SERVICE.orthodontics };
const MENU_STAGE = { doctor_menu: 'menu_doctors', service_menu: 'menu_services', service_general: 'menu_service_doctors', service_pediatric: 'menu_service_doctors', service_ortho: 'menu_service_doctors' };
const pickedDoc = doctors.find(d => d.doctor_name === t);
if ((menu[t] || pickedDoc) && s.stage === 'awaiting_approval') { out.action = 'confirm_cancel'; return done(); }
if (menu[t]) { out.action = menu[t]; out.menu_stage = MENU_STAGE[out.action] || ''; if (out.action in MENU_SERVICE) out.service = MENU_SERVICE[out.action]; return done(); }
if (pickedDoc) {
  docCtx(pickedDoc); out.quick_rebook = '';
  if (!pickedDoc.calendar_id) return reply('Այս բժշկի ժամանակացույցը դեռ միացված չէ։ Ընտրեք մեկ այլ բժշկի։');
  return askReason(pickedDoc);
}
// Visit reason chosen -> work out the length and show the free dates.
if (s.stage === 'awaiting_reason') {
  const rd = doctors.find(d => d.doctor_key === s.doctor_key);
  if (!rd) return replyHome(RESTART_MSG);
  const rs = reasonsFor(rd).find(x => x.label === t);
  if (!rs) return reply('Խնդրում ենք ընտրել այցի նպատակը ստորև նշված կոճակներից։');
  out.visit_reason = rs.key; docCtx(rd); out.action = 'doctor_chosen'; return done();
}
const sdoc = doctors.find(d => d.doctor_key === s.doctor_key);
if (s.stage === 'awaiting_month' || s.stage === 'awaiting_date' || s.stage === 'awaiting_time') {
  if (!sdoc) return replyHome(RESTART_MSG);
  docCtx(sdoc);
  if (t === L.otherDate) { out.action = 'doctor_chosen'; return done(); }
  // Month buttons ("📅 Հոկտեմբեր · 15 ազատ օր") and the month switch on the date screen.
  if (t.includes('📅')) {
    if (t.includes(MONTHS[curMonth])) { out.month_offset = 0; out.action = 'doctor_chosen'; return done(); }
    if (t.includes(MONTHS[nextMonth])) { out.month_offset = 1; out.action = 'doctor_chosen'; return done(); }
  }
  if (s.stage === 'awaiting_month') return reply('Խնդրում ենք ընտրել ամիսը ստորև նշված կոճակներից։');
  const dm = /^(\d{4}-\d{1,2}-\d{1,2})/.exec(t);
  // Date buttons look like "հոկ 14 Չրք" (older ones "Չրք 14.10"); the year is this year, or next year for an earlier month.
  const db = /(\d{1,2})\.(\d{1,2})$/.exec(t) || ((x) => x && MON.indexOf(x[1]) >= 0 ? [x[0], x[2], String(MON.indexOf(x[1]) + 1)] : null)(/^(\S+) (\d{1,2})(?: |$)/.exec(t));
  let btnDate = '';
  if (db) { const mm = +db[2], y = +today.slice(0, 4) + (mm < +today.slice(5, 7) ? 1 : 0); btnDate = y + '-' + String(mm).padStart(2, '0') + '-' + String(+db[1]).padStart(2, '0'); }
  if (s.stage === 'awaiting_date' || dm || btnDate) {
    const dt = dm ? dm[1] : (btnDate || t);
    const err = checkDate(dt);
    if (err) return reply(err);
    setDate(dt); out.mode = 'date'; out.action = 'check_availability'; return done();
  }
  let opts = []; try { opts = JSON.parse(s.slot_options || '[]'); } catch (e) { opts = []; }
  const hm = normTime(t);
  if (!hm || !opts.includes(hm)) return reply('Խնդրում ենք ընտրել ազատ ժամերից մեկը կոճակներից։\nԱզատ ժամեր՝ ' + (opts.join(', ') || '—'));
  if (!out.approver_chat_id) return replyHome(NO_APPROVER);
  // Trying again after a rejection, or changing a booking: reuse the saved name and phone.
  const savedPhone = normPhone(s.phone);
  if (s.quick_rebook === 'yes' && s.full_name && savedPhone) return buildRequest(sdoc, hm, s.full_name, savedPhone);
  // Ask who the visit is for before sending the request.
  out.action = 'ask_name'; out.selected_time = hm; setDate(s.appointment_date);
  return done();
}
if (s.stage === 'awaiting_approval') return replyHome('Ձեր հայտը սպասում է բժշկի հաստատմանը։ Պատասխանը կստանաք այստեղ։');
if (staffDocs.length) { out.action = 'staff_menu'; return done(); }
return replyHome('Չհասկացա։ Սկսելու համար սեղմեք ' + HOME + '։');
