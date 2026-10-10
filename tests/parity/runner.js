// Runs the original n8n Code-node JavaScript on a list of scenarios (stdin JSON) and prints the results.
// Used by tests/test_parity.py to prove the Python port behaves exactly like the n8n workflow.
const fs = require('fs');
const path = require('path');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const code = {
  route: fs.readFileSync(path.join(__dirname, 'js/route.js'), 'utf8'),
  free: fs.readFileSync(path.join(__dirname, 'js/free_slots.js'), 'utf8'),
  dates: fs.readFileSync(path.join(__dirname, 'js/available_dates.js'), 'utf8'),
  report: fs.readFileSync(path.join(__dirname, 'js/staff_report.js'), 'utf8'),
};
const realNow = Date.now;
const results = input.map(sc => {
  Date.now = () => sc.now;
  const nodes = sc.nodes;  // node name -> array of json items
  const $ = n => ({ first: () => ({ json: (nodes[n] || [{}])[0] }), all: () => (nodes[n] || []).map(j => ({ json: j })) });
  try {
    const res = new Function('$', code[sc.kind])($);
    return res && res[0] ? res[0].json : null;
  } catch (e) {
    return { error: String(e) };
  } finally {
    Date.now = realNow;
  }
});
process.stdout.write(JSON.stringify(results));
