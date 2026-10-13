// Runs the n8n Clinic bot's "Lang pack" and the language part of "Parse update" (tests/parity/n8n-code/*.js) on test cases
// from stdin and prints the results, so tests/test_i18n.py can compare them with bot/i18n.py.
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, 'n8n-code');
const langPack = fs.readFileSync(path.join(dir, 'lang-pack.js'), 'utf8');
let parse = fs.readFileSync(path.join(dir, 'parse-update.js'), 'utf8');
// The doctor-info part after the language block is handled by the Python router itself; compare up to that point.
parse = parse.split('// Doctor info buttons read')[0] + '\nreturn [{ json: out }];';
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const realNow = Date.now;
  const out = [];
  for (const c of input.cases) {
    Date.now = () => c.now;
    const store = { i18n: input.data, i18nAt: c.now };
    const nodes = { 'Telegram Trigger': [c.update || {}] };
    const $ = n => ({ first: () => { if (!nodes[n]) throw new Error('no node ' + n); return { json: nodes[n][0] }; }, all: () => (nodes[n] || []).map(j => ({ json: j })) });
    const $input = { all: () => c.rows.map(j => ({ json: j })), first: () => ({ json: c.rows[0] }) };
    const ctx = { helpers: { httpRequest: async () => { throw new Error('offline'); } } };
    const lp = (await new AsyncFunction('$', '$input', '$getWorkflowStaticData', langPack).call(ctx, $, $input, () => store))[0].json;
    nodes['Lang pack'] = [lp];
    const pu = (await new AsyncFunction('$', '$input', parse).call(ctx, $, $input))[0].json;
    out.push({ P: c.want_packs ? lp.P : null, R: c.want_packs ? lp.R : null,
               out: { kind: pu.kind, ask_lang: pu.ask_lang, set_lang: pu.set_lang, lang: pu.lang, text: pu.text } });
  }
  Date.now = realNow;
  process.stdout.write(JSON.stringify(out));
})();
