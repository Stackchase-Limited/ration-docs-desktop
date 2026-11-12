// #1144: the Recover list must show each file's autosave date. bdbd5c35 (desktop-sdk) put the date
// into the rows; the start page's stylesheet hid the .col-date column of #box-recovery, so users still
// saw names only. Reads the real styles.less (working tree, or BASE_REF with BASELINE=1).
//   RD_REPO=<desktop-apps>  default ../desktop-apps     BASELINE=1 must fail
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'desktop-apps');
const BASE_REF = process.env.BASE_REF || '68827a107^';
const REL = 'common/loginpage/src/css/styles.less';
const src = process.env.BASELINE
	? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8' })
	: fs.readFileSync(path.join(REPO, REL), 'utf8');
// the rule of its own ("#box-recent, #box-recovery {" earlier in the file is a shared one)
const mm = /^#box-recovery \{/m.exec(src); const at = mm ? mm.index : -1;
if (at < 0) { console.log('FAIL: #box-recovery block not found - the test needs updating'); process.exit(2); }
let depth = 0, end = at;
for (let i = src.indexOf('{', at); i < src.length; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) { end = i; break; } }
const block = src.slice(at, end + 1);
// every selector list whose rule sets display: none
const hidden = [...block.matchAll(/([^{};]+)\{\s*display:\s*none;?\s*\}/g)].map(m => m[1]);
const hidesDate = hidden.some(sel => /\.col-date\b/.test(sel));
console.log((process.env.BASELINE ? `baseline ${BASE_REF}` : 'working tree') + ': hidden selectors in #box-recovery: ' + JSON.stringify(hidden.map(s => s.trim())));
if (hidesDate) { console.log('FAIL #1144: the Recover list hides .col-date, so the autosave date never shows'); process.exit(1); }
console.log('PASS #1144: the Recover list shows its date column');
