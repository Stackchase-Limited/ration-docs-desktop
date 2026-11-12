/*
 * #1363 - "Be transparent about opening a webpage when clicking on buttons"
 * (start page part; the editors' "Feedback & Support" button is
 * issue-1363-editor-support-hint-test.js).
 *
 * The start page's About box has links that leave the app: Changelog, Report
 * an issue, the web site, and the licence / CC / source links of the Open
 * Source Notices. They are <a target="popup">; desktop-sdk CheckPopup hands an
 * http(s) one straight to the system's web browser (link_policy.h, no prompt
 * for web links). Nothing on them said so: no tooltip, no address.
 *
 * Fix: desktop-apps common/loginpage/src/panelabout.js markWebLinks() gives
 * every http(s) link of the About body a tooltip "Opens in your web browser"
 * plus the address (new string tipOpensInBrowser in locale.js), when the body
 * is built and again when the language changes.
 *
 * This test loads the real jQuery, events.js, base.js, utils.js, locale.js and
 * the whole of panelabout.js into jsdom (AboutDialog and the sdk stubbed),
 * sends the 'app:version' native message the app sends, and checks that each
 * web link of the About body has a title naming the browser and its address
 * (baseline: no title -> FAILS), and that a non-web link (#, the update check)
 * is left alone.
 *
 * NOT claimed: how the tooltip looks (native Chromium tooltip; GUI check).
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      RD_NODE_MODULES  where jsdom lives (default /Users/osindero/dev/active/node_modules)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || '3ff2db754^';
const NODE_MODULES = process.env.RD_NODE_MODULES || '/Users/osindero/dev/active/node_modules';
const { JSDOM } = require(path.join(NODE_MODULES, 'jsdom'));

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', APPS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(APPS, rel), 'utf8');
}

const L = 'common/loginpage/';
const dom = new JSDOM(`<!doctype html><body>
	<div class="main-column tool-menu"></div><div class="main-column col-center"></div><div id="placeholder"></div>
	</body>`, { runScripts: 'dangerously', url: 'http://localhost/loginpage/index.html' });
const w = dom.window;
w.addEventListener('error', e => { w.__err = e.error; });
function run(code) {
	const s = w.document.createElement('script');
	s.textContent = code;
	w.document.body.appendChild(s);
	if (w.__err) throw w.__err;
}

run(fs.readFileSync(path.join(APPS, L + 'vendor/jquery/jquery.js'), 'utf8'));
run(src(L + 'src/events.js'));
run(src(L + 'src/base.js'));
run(src(L + 'src/utils.js'));
run(src(L + 'src/locale.js'));
run(`
	utils.Lang = l10n.en;
	var _native = [];
	window.sdk = { on: function (ev, fn) { ev === 'on_native_message' && _native.push(fn); } };
	function AboutDialog() {} AboutDialog.prototype = { show: function () {}, setBody: function () {} };
`);
run(src(L + 'src/panelabout.js'));
run('window.__about = (new ControllerAbout).init();');

const opts = { version: '9.4.0.1', appname: 'Ration Docs', link: 'https://ration.works', changelog: 'https://ration.works/changelog', rights: '' };
w.eval('_native').forEach(fn => fn('app:version', JSON.stringify(opts)));

const $body = w.eval('window.__about.view.$body');
assert.ok($body && $body.length, 'the About body was not built - test is stale');
const links = $body.find('a[target="popup"]').toArray().filter(a => /^https?:/.test(a.getAttribute('href')));
assert.ok(links.length >= 5, 'expected the About box web links - test is stale');
for (const a of links) {
	const title = a.getAttribute('title') || '';
	console.log(`${a.textContent.trim()} -> ${JSON.stringify(title)}`);
	assert.ok(/web browser/i.test(title), `"${a.textContent.trim()}" opens ${a.getAttribute('href')} in the web browser but does not say so`);
	assert.ok(title.includes(a.getAttribute('href')), `"${a.textContent.trim()}" does not show where it goes`);
}
const check = $body.find('.ver-checkupdate').get(0);
assert.ok(check && !check.hasAttribute('title'), 'a link that stays in the app got the browser note');

console.log(`PASS #1363: the ${links.length} About box links that open the web browser say so`);
