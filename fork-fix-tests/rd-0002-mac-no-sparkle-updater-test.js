/*
 * macOS: Ration Docs ships no appcast (debc6134b removed SUFeedURL and set
 * SUEnableAutomaticChecks=false in every Info.plist), yet Main.storyboard
 * still instantiated Sparkle's SUUpdater at launch and the app menu had an
 * enabled "Check for Updates..." (Cmd+U) wired to it. Triage "### #644":
 * a fresh profile showed Sparkle's "Check for updates automatically?" and the
 * menu item led to an updater with no feed.
 *
 * Fix (desktop-apps): the SUUpdater object, the menu item and its outlet are
 * gone from Main.storyboard, so Sparkle is never started (the framework stays
 * linked, unused).
 *
 * What runs: the REAL Main.storyboard is checked as text (no SUUpdater /
 * SPUStandardUpdaterController object, no checkForUpdates: action, no outlet
 * to a missing object, the app menu still has About and Preferences), and
 * when xcrun is present it is compiled with ibtool exactly as Xcode does and
 * the compiled MainMenu.nib must not name SUUpdater. Control: no Info.plist
 * has SUFeedURL.
 *
 *   RD_REPO=<desktop-apps checkout>  default ../desktop-apps
 *   BASELINE=1  read the files at BASE_REF (default 09c48fb4e^); must FAIL
 *
 * NOT claimed: the prompt itself was not reproduced here (no GUI launch this
 * round); with SUEnableAutomaticChecks=false in Info.plist Sparkle 2.0.0
 * should not ask, so a GUI check of a fresh profile is still wanted. The
 * Windows/Linux updaters are untouched. Stale "ud7-wC-A79.title" strings in
 * the *.lproj/Main.strings files are left (ibtool ignores keys of missing
 * objects).
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'desktop-apps');
const BASE_REF = process.env.BASE_REF || '09c48fb4e^';
const BASELINE = !!process.env.BASELINE;
const read = (rel) => BASELINE
	? execFileSync('git', ['-C', REPO, 'show', BASE_REF + ':' + rel], { maxBuffer: 1 << 26 }).toString('utf8')
	: fs.readFileSync(path.join(REPO, rel), 'utf8');

let failed = 0;
const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); failed += !ok; };

console.log(BASELINE ? 'BASELINE ' + BASE_REF : 'repo ' + REPO);
const SB = 'macos/ONLYOFFICE/Base.lproj/Main.storyboard';
const sb = read(SB);

check(!/customClass="(SUUpdater|SPUStandardUpdaterController)"/.test(sb), 'Main.storyboard instantiates no Sparkle updater');
check(!/selector="checkForUpdates:"/.test(sb), 'no menu item is wired to checkForUpdates:');
const ids = new Set([...sb.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
const dangling = [...sb.matchAll(/(?:destination|target)="([^"]+)"/g)].map(m => m[1]).filter(id => !ids.has(id));
check(dangling.length === 0, 'no outlet/action points at a removed object' + (dangling.length ? ': ' + dangling.join(',') : ''));
check(/selector="onMenuAbout:"/.test(sb) && /selector="onPreferences:"/.test(sb), 'control: app menu still has About and Preferences');

for (const arch of ['ONLYOFFICE-arm', 'ONLYOFFICE-v8', 'ONLYOFFICE-x86_64']) {
	const plist = read('macos/ONLYOFFICE/Resources/' + arch + '/Info.plist');
	check(!/<key>SUFeedURL<\/key>/.test(plist), 'control: ' + arch + '/Info.plist has no SUFeedURL');
}

let ibtool = true;
try { execFileSync('xcrun', ['--find', 'ibtool'], { stdio: 'ignore' }); } catch (e) { ibtool = false; }
if (ibtool) {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rd-sparkle-'));
	const src = path.join(dir, 'Main.storyboard');
	fs.writeFileSync(src, sb);
	const out = path.join(dir, 'Main.storyboardc');
	execFileSync('xcrun', ['ibtool', '--errors', '--compile', out, src], { stdio: 'ignore' });
	const nib = path.join(out, 'MainMenu.nib');
	const files = fs.statSync(nib).isDirectory() ? fs.readdirSync(nib).map(f => path.join(nib, f)) : [nib];
	const named = files.some(f => fs.readFileSync(f).includes('SUUpdater'));
	check(!named, 'ibtool-compiled MainMenu.nib does not create SUUpdater');
	fs.rmSync(dir, { recursive: true, force: true });
} else
	console.log('skip ibtool (no Xcode)');

console.log(failed ? 'FAILED (' + failed + ')' : 'PASSED');
process.exit(failed ? 1 : 0);
