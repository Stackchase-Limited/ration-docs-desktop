/*
 * #432 - "Default to inches in the appropriate regions (based on OS regional settings)":
 * with the Region set to United States the editors still started in centimetres (ruler,
 * Advanced settings > Unit, page margin presets).
 *
 * Cause: each editor's loadDefaultMetricSettings (DE/PE/SSE/PDF Main.js) picks inch for
 * region US/CA, taking the region from editorConfig.location, then editorConfig.region,
 * then the interface language code ("en-US"), then navigator.language (the OS display
 * language) - never from the OS regional settings. The Windows and Linux apps already put
 * the OS country in every editor URL ("location=US", Utils::systemLocationCode), but
 * web-apps' desktop entry page (apps/api/documents/index.html.desktop getEditorConfig) did
 * not pass it on, and the macOS app did not send it at all. So an English interface on a
 * US machine gave cm, and an "en-US" interface on a German machine gave inches.
 * Fix: getEditorConfig passes a two-letter `location` URL parameter on as
 * editorConfig.location; the macOS app (ASCEditorJSVariables.mm) sends location=<country of
 * [NSLocale currentLocale]>. Only users who never chose a unit are affected (a stored
 * de-/pe-/sse-settings-unit wins as before).
 *
 * What runs: the REAL getEditorConfig of index.html.desktop and, for the document,
 * presentation and spreadsheet editors, the REAL appOptions.location line and REAL
 * loadDefaultMetricSettings of Main.js, with stubs for Common.Utils.Metric (records
 * setDefaultMetric) and navigator; on macOS also the REAL location lines of
 * ASCEditorJSVariables.mm compiled with clang against Foundation and run with
 * -AppleLocale (en_US -> US, en_GB -> GB).
 *
 * NOT claimed: the Windows value comes from GetLocaleInfo(LOCALE_SYSTEM_DEFAULT) - the
 * system locale, which is usually but not always the user's Region (not changed here, cannot
 * be built on this Mac); Linux sends "EN" for a C/POSIX locale (then cm, as before for most);
 * the GUI (needs a look at File > Advanced settings > Unit on a fresh profile).
 *
 *   RD_WEBAPPS=<web-apps> (default ../../web-apps), RD_DESKTOP_APPS=<desktop-apps>
 *   (default ../../desktop-apps). BASELINE=1 reads both at their BASE_REFs; it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const WEBAPPS = path.resolve(process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps'));
const DAPPS = path.resolve(process.env.RD_DESKTOP_APPS || path.join(ROOT, 'desktop-apps'));
// Pinned to the parents of the fix commits, never HEAD.
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '367ff6911d^';
const DAPPS_BASE_REF = process.env.DAPPS_BASE_REF || '1591170a48^';

function read(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
function blockEnd(text, open) {
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return i + 1;
	}
	throw new Error('unbalanced braces');
}
function func(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	const f = text.indexOf('function', at);
	return text.slice(f, blockEnd(text, text.indexOf('{', f)));
}

let failed = 0;
function check(name, f) {
	try { f(); console.log('ok   - ' + name); }
	catch (e) { failed++; console.log('FAIL - ' + name + '\n       ' + e.message); }
}

const entry = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/api/documents/index.html.desktop');
const getEditorConfig = new Function('return ' + func(entry, 'function getEditorConfig(urlParams)'))();

const editors = { DE: 'documenteditor', PE: 'presentationeditor', SSE: 'spreadsheeteditor' };
function defaultUnit(app, urlParams, navLang) {
	const main = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/' + app + '/main/app/controller/Main.js');
	const locLine = main.match(/this\.appOptions\.location\s*=.*;/)[0];
	const load = func(main, 'loadDefaultMetricSettings: function');
	let unit = 'cm';
	const Common = {
		Utils: { Metric: { c_MetricUnits: { cm: 'cm', inch: 'inch' }, setDefaultMetric: (u) => { unit = u; } },
			InternalSettings: { set() {} } },
		util: { LanguageInfo: { getLanguages: () => ({}), getLocalLanguageName: (v) => [v] } },
	};
	const self = { editorConfig: getEditorConfig(urlParams), appOptions: {} };
	self.appOptions.lang = self.editorConfig.lang;
	new Function('Common', locLine).call(self, Common);
	new Function('Common', 'navigator', 'console', '(' + load + ').call(this);').call(self, Common, { language: navLang }, { log() {} });
	return unit;
}

for (const [name, app] of Object.entries(editors)) {
	check(name + ': English interface on a US machine (location=US) starts in inches', () =>
		assert.strictEqual(defaultUnit(app, { lang: 'en', location: 'US' }, 'en-GB'), 'inch'));
	check(name + ': "en-US" interface on a German machine (location=DE) starts in centimetres', () =>
		assert.strictEqual(defaultUnit(app, { lang: 'en-US', location: 'DE' }, 'en-US'), 'cm'));
}
check('no or bad location (old app, Windows "unknown"): falls back to the language as before', () => {
	assert.strictEqual(defaultUnit('documenteditor', { lang: 'en-US' }, 'en-GB'), 'inch');
	assert.strictEqual(defaultUnit('documenteditor', { lang: 'en-US', location: 'unknown' }, 'en-GB'), 'inch');
	assert.strictEqual(defaultUnit('documenteditor', { lang: 'en' }, 'en-GB'), 'cm');
});

/* macOS: the real lines of ASCEditorJSVariables.mm send the Region's country */
if (os.platform() === 'darwin') {
	check('macOS app sends location=<Region country> to the editors', () => {
		const mm = read(DAPPS, DAPPS_BASE_REF, 'macos/ONLYOFFICE/Code/Utils/ASCEditorJSVariables.mm');
		const at = mm.indexOf('NSString * country = [[NSLocale currentLocale]');
		assert.notStrictEqual(at, -1, 'ASCEditorJSVariables.mm does not send the country');
		const ifAt = mm.indexOf('if ( country.length )', at);
		const snippet = mm.slice(at, blockEnd(mm, mm.indexOf('{', ifAt)));
		const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rd432-'));
		try {
			const prog = `#import <Foundation/Foundation.h>
@interface Vars : NSObject { @public NSMutableDictionary * params; }
- (void)setParameter:(NSString*)name withString:(NSString *)value;
- (void)run;
@end
@implementation Vars
- (void)setParameter:(NSString*)name withString:(NSString *)value { [params setValue:value forKey:name]; }
- (void)run {
${snippet}
}
@end
int main() { @autoreleasepool { Vars * v = [Vars new]; v->params = [NSMutableDictionary dictionary]; [v run];
  printf("%s\\n", [[v->params objectForKey:@"location"] ?: @"-" UTF8String]); } return 0; }
`;
			fs.writeFileSync(path.join(tmp, 'p.m'), prog);
			execFileSync('clang', ['-fobjc-arc', '-framework', 'Foundation', '-o', path.join(tmp, 'p'), path.join(tmp, 'p.m')]);
			const run = (loc) => execFileSync(path.join(tmp, 'p'), ['-AppleLocale', loc], { encoding: 'utf8' }).trim();
			assert.strictEqual(run('en_US'), 'US');
			assert.strictEqual(run('en_GB'), 'GB');
			assert.strictEqual(run('fr_CA'), 'CA');
		} finally {
			fs.rmSync(tmp, { recursive: true, force: true });
		}
	});
}

if (failed) {
	console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
	process.exit(1);
}
console.log('all checks passed');
