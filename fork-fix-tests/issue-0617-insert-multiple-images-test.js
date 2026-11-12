/*
 * #617 - "Insert multiple images at once": in the desktop app Insert > Image >
 * From file let you pick one picture only.
 *
 * Cause: sdkjs word/Local/api.js (document + PDF editor), slide/Local/api.js,
 * cell/Local/api.js - the desktop asc_addImage called
 * AscDesktopEditor.OpenFilenameDialog("images", false, ...) (single file) and
 * kept only file[0]; and on macOS desktop-apps macos/ONLYOFFICE/AppDelegate.mm
 * onCEFOpenFileDialog forced allowsMultipleSelection = NO and answered with
 * [openPanel URL] only, so even multiselect requests got one file.
 * Fix: multiselect request + every picked file to _addImageUrl (shared helper
 * AscCommon.getDesktopImageUrls in common/Local/common.js); the macOS panel
 * honours isMulti and returns all URLs in get_Files().
 *
 * This test
 *  1. extracts the real desktop asc_addImage of each editor (and the helper,
 *     when present) and runs it against a stub AscDesktopEditor whose dialog
 *     answers the way the native side does (array when multiselect was asked,
 *     a single path otherwise): picking two images must hand both urls to
 *     _addImageUrl (baseline: single-select dialog, one url -> FAILS); a
 *     cancelled dialog must add nothing;
 *  2. extracts onCEFOpenFileDialog from AppDelegate.mm and checks the panel's
 *     multiple selection follows isMulti and that all panel URLs are put into
 *     get_Files() (baseline: NO / one URL -> FAILS). This part is a source
 *     check: the Objective-C was compiled (-fsyntax-only) but not run.
 *
 * NOT claimed: the native dialogs on screen (GUI check), image layout after
 * inserting several images (that is the editors' existing AddImages path, the
 * same the online editors use).
 *
 * Env: RD_REPO   sdkjs checkout        (default ../sdkjs)
 *      RD_APPS   desktop-apps checkout (default ../desktop-apps)
 *      BASELINE=1 reads both from BASE_REF / APPS_BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const APPS = path.resolve(process.env.RD_APPS || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || '4dcd75bc18^';
const APPS_BASE_REF = process.env.APPS_BASE_REF || '2fceb40b24^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}

function fnAfter(text, marker) {
	const at = text.indexOf(marker);
	assert.ok(at !== -1, marker + ' not found - test is stale');
	return 'function(obj) ' + block(text, text.indexOf('function(obj)', at));
}

/* ---- 1. sdkjs desktop asc_addImage ---- */
const commonLocal = src(SDKJS, BASE_REF, 'common/Local/common.js');
const helperAt = commonLocal.indexOf('AscCommon.getDesktopImageUrls = function(files)');
const helperSrc = helperAt === -1 ? '' : 'function(files) ' + block(commonLocal, helperAt);

const editors = [
	{ name: 'document/PDF', file: 'word/Local/api.js', marker: "Asc['asc_docs_api'].prototype.AddImage = Asc['asc_docs_api'].prototype.asc_addImage =" },
	{ name: 'presentation', file: 'slide/Local/api.js', marker: "Asc['asc_docs_api'].prototype.AddImage = Asc['asc_docs_api'].prototype.asc_addImage =" },
	{ name: 'spreadsheet', file: 'cell/Local/api.js', marker: 'spreadsheet_api.prototype.asc_showImageFileDialog = spreadsheet_api.prototype.asc_addImage =' },
];

function run(ed, picked) {
	const added = [];
	const asked = [];
	const desktop = {
		OpenFilenameDialog: (filter, multi, cb) => {
			asked.push({ filter, multi });
			// what the native side answers (client_renderer_wrapper on_open_filename_dialog)
			if (picked === null) cb(multi ? [] : '');
			else cb(multi ? picked.slice() : picked[0]);
		},
		LocalFileGetImageUrl: (p) => 'media/' + path.basename(p),
	};
	const AscCommon = { g_oDocumentUrls: { getImageUrl: (u) => 'doc://' + u } };
	const window = { AscDesktopEditor: desktop };
	if (helperSrc)
		AscCommon.getDesktopImageUrls = new Function('window', 'AscCommon', 'return ' + helperSrc)(window, AscCommon);
	const api = {
		_addImageUrl: (urls, obj) => added.push(...urls),
		// the presentation editor's old path inserted one url this way
		AddImageUrlAction: (url) => added.push(url),
	};
	const fn = new Function('window', 'AscCommon', 'editor', 'return ' + fnAfter(src(SDKJS, BASE_REF, ed.file), ed.marker))(window, AscCommon, api);
	fn.call(api, undefined);
	return { asked, added };
}

for (const ed of editors) {
	const two = run(ed, ['/home/u/scan1.png', '/home/u/scan2.jpg']);
	console.log(`${ed.name}: dialog multiselect=${two.asked[0].multi}, picked 2 -> inserted ${JSON.stringify(two.added)}`);
	assert.strictEqual(two.asked[0].filter, 'images', 'stub harness broken: image dialog not opened');
	assert.deepStrictEqual(two.added, ['doc://media/scan1.png', 'doc://media/scan2.jpg'],
		`${ed.name} editor: picking several images does not insert them all`);
	const none = run(ed, null);
	assert.deepStrictEqual(none.added, [], `${ed.name} editor: a cancelled dialog must insert nothing`);
}

/* ---- 2. macOS open panel ---- */
const app = src(APPS, APPS_BASE_REF, 'macos/ONLYOFFICE/AppDelegate.mm');
const mAt = app.indexOf('- (void)onCEFOpenFileDialog:(NSNotification *)notification');
assert.ok(mAt !== -1, 'onCEFOpenFileDialog not found - test is stale');
const method = block(app, mAt);
const multiSel = (method.match(/openPanel\.allowsMultipleSelection\s*=\s*([^;]+);/) || [])[1];
const allUrls = /for\s*\(\s*NSURL\s*\*\s*\w+\s+in\s+\[openPanel URLs\]\s*\)[\s\S]*?get_Files|get_Files\(\)[\s\S]*?\[openPanel URLs\]/.test(method);
console.log(`macOS panel: allowsMultipleSelection = ${multiSel}, all URLs into get_Files: ${allUrls}`);
assert.strictEqual(multiSel && multiSel.trim(), 'isMulti', 'the macOS file dialog ignores a multiselect request');
assert.ok(allUrls, 'the macOS file dialog answers a multiselect request with one file');

console.log('PASS #617: Insert > Image > From file inserts every picked image (document, PDF, presentation, spreadsheet)');
