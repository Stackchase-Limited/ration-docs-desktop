/*
 * #1355 "More localizations support" - languages the app has but does not
 * let you use.
 *
 * The editors (web-apps apps/*\/main/locale) are translated into 45 languages,
 * and the blank-document templates (document-templates/new) exist for them,
 * but the interface-language list - ASCLinguist availableLanguages on macOS,
 * CLangater m_langs on Windows/Linux - left out three: Azerbaijani (az, 60%
 * of the document editor's strings), Basque (eu, 78%) and Malay (ms, 64%),
 * though it offers less complete ones (vi 38%, lo 61%, gl 65%). They could not
 * be chosen; on macOS a system set to one of them already got the translated
 * editors, on Windows/Linux never.
 *
 * Now az-Latn-AZ, eu-ES and ms-MY are in both lists, named as the templates
 * are, and on Windows/Linux resources.qrc gives them the English native
 * translation (CLangater only switches to a language with a .qm), so the start
 * page and native dialogs stay English while the editors are translated.
 *
 * This reads the REAL lists (ASCLinguist.m, clangater.cpp, resources.qrc), the
 * REAL web-apps locale folders and document-templates/new, and checks: every
 * language the editors are translated into can be chosen on both platforms;
 * every Windows/Linux entry has a .qm in resources.qrc (else choosing it does
 * nothing); every new entry has a blank-document template of exactly that name.
 *
 * NOT claimed: no GUI run; the start page has no az/eu/ms strings (English);
 * on Linux a system locale of az/eu/ms now picks that language at first start
 * (as macOS already does) instead of English.
 *
 *   node fork-fix-tests/issue-1355-interface-languages-test.js
 *   RD_REPO=<desktop-apps> (default ../desktop-apps)  RD_WEBAPPS (../web-apps)  RD_TEMPLATES (../document-templates)
 *   BASELINE=1 reads desktop-apps at BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'desktop-apps');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
const TEMPLATES = process.env.RD_TEMPLATES || path.resolve(__dirname, '..', 'document-templates');
const BASE_REF = process.env.BASE_REF || '76994a700^';
const BASELINE = !!process.env.BASELINE;

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8' })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}
function block(text, marker, open, close) {
	const at = text.indexOf(marker);
	if (at < 0) throw new Error('not found: ' + marker);
	const i = text.indexOf(open, at);
	let depth = 0;
	for (let j = i; j < text.length; j++) {
		if (text[j] === open) depth++;
		else if (text[j] === close && --depth === 0) return text.slice(i, j + 1);
	}
	throw new Error('unbalanced after ' + marker);
}
const strip = (s) => s.replace(/^\s*\/\/.*$/mg, '');

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

const mac = [...strip(block(src('macos/ONLYOFFICE/Code/Controllers/Common/ASCLinguist.m'), '+ (NSDictionary *)availableLanguages', '{', '}').replace(/^[^@]*@\{/, ''))
	.matchAll(/@"([A-Za-z-]+)"\s*:\s*@\{@"name"/g)].map(m => m[1]);
const win = [...strip(block(src('win-linux/src/clangater.cpp'), 'm_langs{', '{', '}'))
	.matchAll(/\{"([A-Za-z-]+)",\s*\{"/g)].map(m => m[1]);
const qrc = [...src('win-linux/resources.qrc').matchAll(/<file alias="([A-Za-z-]+)\.qm">/g)].map(m => m[1]);
check(mac.length > 40 && win.length > 40, `language lists read (macOS ${mac.length}, Windows/Linux ${win.length})`);

const base = (code) => code.split('-')[0].toLowerCase();
const editorLangs = fs.readdirSync(path.join(WEBAPPS, 'apps/documenteditor/main/locale'))
	.filter(f => f.endsWith('.json')).map(f => f.slice(0, -5)).filter(c => c !== 'en');
for (const c of editorLangs) {
	const b = base(c);
	check(mac.some(k => base(k) === b) && win.some(k => base(k) === b), `editors translated into "${c}": selectable on macOS and Windows/Linux`);
}
for (const k of win)
	check(qrc.includes(k), `Windows/Linux "${k}" has a native translation in resources.qrc`);
const templates = new Set(fs.readdirSync(path.join(TEMPLATES, 'new')));
for (const k of ['az-Latn-AZ', 'eu-ES', 'ms-MY'])
	check(mac.includes(k) && win.includes(k) && templates.has(k), `"${k}" is offered under the name of its blank-document template`);

console.log(failed ? `FAILED (${failed})` : 'PASS');
process.exit(failed ? 1 : 0);
