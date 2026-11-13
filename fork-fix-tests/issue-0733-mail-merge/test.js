/*
 * DesktopEditors #733 - mail merge in the desktop editors ("Mail Merge is missing from the desktop version").
 *
 * Before: off whenever the document is a local file. documenteditor controller/Main.js set
 * canUseMailMerge = canLicense && canEdit && !isOffline, so the Collaboration tab had no Mail Merge button and
 * the right panel no Mail Merge settings; and every step that touches a file went through the document server
 * (sdkjs word/api.js asc_StartMailMerge: downloadAs to JSON; asc_DownloadAsMailMerge: downloadAs to DOCX/PDF).
 * Now (desktop app, local file; no server): Mail Merge > "From file" opens the native picker (spreadsheets) and
 * reads the picked file the ways the desktop already reads a picked file - a spreadsheet through the local
 * converter (AscDesktopEditor.convertFile -> x2t to the same JSON rows the server makes), CSV/TSV as bytes
 * (loadLocalFile; convertFile cannot pass x2t the delimiter/encoding text needs) parsed with sdkjs's CSV parser
 * (UTF-8, delimiter guessed from the header line). Fields are inserted and previewed with the existing panel
 * and sdkjs API. "Merge to" offers only "New document"; Merge writes the existing Get_MailMergedDocument (one
 * section per record) as Editor.bin and the host opens it as a new unsaved tab (OpenBinaryAsNewFile, as #2045
 * Duplicate). "From URL" (needs the server) is hidden offline; E-mail and PDF outputs are not offered offline.
 *
 * What runs: the REAL document editor - web-apps source tree under test in dev mode with a built sdkjs, in
 * headless Chromium, opened like the desktop app (api/documents/index.html.desktop -> DocsAPI iframe, stubbed
 * AscDesktopEditor, core's empty docx). The host's convertFile runs the REAL x2t (RD_CORE_BIN) with the same
 * parameters desktop-sdk CConvertFileInEditor writes (no CSV options). Steps:
 *   - Collaboration tab has Mail Merge; its menu shows "From file" only (URL and storage hidden);
 *   - "From file" asks the host for a "cell" dialog; the picked .xlsx goes to x2t as JSON (0x0808); the panel
 *     opens with 3 recipients and fields Name, City, Amount;
 *   - text is typed and the three fields are inserted from the panel's "Insert merge field" menu;
 *   - Preview, then Next: record 2 is shown in the document text;
 *   - "Merge to" lists only "New document"; the button says Merge; clicking it hands the host one binary;
 *   - that binary opened as a new tab (a second editor, as OpenBinaryAsNewFile does) has one section per
 *     record with that record's text, and x2t saves it as DOCX (the save of the new tab) with all three;
 *   - a semicolon CSV with a UTF-8 BOM, a quoted field with the delimiter and non-ASCII text is read through
 *     loadLocalFile (not x2t) with the right rows.
 *                         (BASELINE: no Mail Merge offline, no local reading or merge in sdkjs -> FAILS)
 * NOT claimed: the native picker, convertFile and OpenBinaryAsNewFile themselves (desktop-sdk, unchanged; the
 * new tab's handling of the binary is #2045's); the look in the real app (GUI check); "Edit recipients"
 * (the embedded spreadsheet editor) offline; CSV in encodings other than UTF-8 (read as UTF-8).
 *
 * Env: RD_REPO           web-apps checkout (default ../../web-apps)
 *      RD_SDKJS          built sdkjs deploy/sdkjs of the fix (default ../../sdkjs/deploy/sdkjs)
 *      RD_SDKJS_REPO     sdkjs checkout, for BASELINE (default ../../sdkjs)
 *      RD_WEBAPPS_DEPLOY a built web-apps deploy/web-apps for app.css + sprites (default ../../web-apps/deploy/web-apps)
 *      RD_CORE           core checkout for Common/empty/docx.bin (default ../../core)
 *      RD_CORE_BIN, RD_CORE_LIB  x2t and its frameworks (default RD_CORE/build/{bin,lib}/mac_arm64)
 *      RD_FONTS          fonts cache dir with AllFonts.js + font_selection.bin (default ../../../.rd-work/fonts-cache;
 *                        copied - x2t may rewrite AllFonts.js in its font dir)
 *      RD_PLAYWRIGHT, RD_CHROME, RD_TMP
 *      BASELINE=1        web-apps from `git archive BASE_REF` (in RD_REPO) and sdkjs built (build/build.py) from
 *                        `git archive SDKJS_BASE_REF` (in RD_SDKJS_REPO); must FAIL.
 */
'use strict';
const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const { openEditor } = require('./open');

const HERE = __dirname;
const REPO = path.resolve(process.env.RD_REPO || path.join(HERE, '..', '..', 'web-apps'));
const SDKJS = path.resolve(process.env.RD_SDKJS || path.join(HERE, '..', '..', 'sdkjs', 'deploy', 'sdkjs'));
const SDKJS_REPO = path.resolve(process.env.RD_SDKJS_REPO || path.join(HERE, '..', '..', 'sdkjs'));
const DEPLOY = path.resolve(process.env.RD_WEBAPPS_DEPLOY || path.join(REPO, 'deploy', 'web-apps'));
const CORE = path.resolve(process.env.RD_CORE || path.join(HERE, '..', '..', 'core'));
const CORE_BIN = path.resolve(process.env.RD_CORE_BIN || path.join(CORE, 'build', 'bin', 'mac_arm64'));
const CORE_LIB = path.resolve(process.env.RD_CORE_LIB || path.join(CORE, 'build', 'lib', 'mac_arm64'));
const FONTS = path.resolve(process.env.RD_FONTS || path.join(HERE, '..', '..', '..', '.rd-work', 'fonts-cache'));
const BASE_REF = process.env.BASE_REF || '088b831418^';
const SDKJS_BASE_REF = process.env.SDKJS_BASE_REF || 'cdbb399929^';

let failed = 0;
function check(name, ok, detail) {
	if (ok) console.log('ok   - ' + name);
	else { failed++; console.log('FAIL - ' + name + (detail !== undefined ? '\n       ' + JSON.stringify(detail) : '')); }
	return ok;
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function gitArchive(repo, ref, dir, paths) {
	fs.mkdirSync(dir, { recursive: true });
	execFileSync('bash', ['-c', 'set -o pipefail; git -C "$1" archive "$2" "${@:4}" | tar -x -C "$3"', 'bash', repo, ref, dir].concat(paths || []),
		{ stdio: ['ignore', 'ignore', 'inherit'], shell: false });
}

function prepare(tmp) {
	if (!process.env.BASELINE) return { webapps: REPO, sdkjs: SDKJS };
	const webapps = path.join(tmp, 'web-apps');
	gitArchive(REPO, BASE_REF, webapps, ['apps', 'vendor']);
	const sdk = path.join(tmp, 'sdkjs');
	gitArchive(SDKJS_REPO, SDKJS_BASE_REF, sdk);
	execFileSync('python3', [path.join(sdk, 'build', 'build.py'), '--beta=false', '--minimize', '--desktop', '--product', 'word'], { cwd: path.join(sdk, 'build'), stdio: 'ignore' });
	return { webapps, sdkjs: path.join(sdk, 'deploy', 'sdkjs') };
}

// --- a tiny .xlsx (shared strings, as Excel writes them) - zip "stored", no dependencies --------------------
const CRC = (() => { const t = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t.push(c >>> 0); } return t; })();
const crc32 = (b) => { let c = 0xFFFFFFFF; for (const x of b) c = CRC[(c ^ x) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
function zip(files) {
	const locals = [], centrals = [];
	let off = 0;
	for (const [name, text] of Object.entries(files)) {
		const n = Buffer.from(name), d = Buffer.from(text), crc = crc32(d);
		const h = Buffer.alloc(30); h.writeUInt32LE(0x04034b50, 0); h.writeUInt16LE(20, 4); h.writeUInt32LE(crc, 14);
		h.writeUInt32LE(d.length, 18); h.writeUInt32LE(d.length, 22); h.writeUInt16LE(n.length, 26);
		const c = Buffer.alloc(46); c.writeUInt32LE(0x02014b50, 0); c.writeUInt16LE(20, 4); c.writeUInt16LE(20, 6); c.writeUInt32LE(crc, 16);
		c.writeUInt32LE(d.length, 20); c.writeUInt32LE(d.length, 24); c.writeUInt16LE(n.length, 28); c.writeUInt32LE(off, 42);
		locals.push(h, n, d); centrals.push(c, n); off += 30 + n.length + d.length;
	}
	const cd = Buffer.concat(centrals), e = Buffer.alloc(22);
	e.writeUInt32LE(0x06054b50, 0); e.writeUInt16LE(centrals.length / 2, 8); e.writeUInt16LE(centrals.length / 2, 10);
	e.writeUInt32LE(cd.length, 12); e.writeUInt32LE(off, 16);
	return Buffer.concat([...locals, cd, e]);
}
function unzipEntry(buf, want) {
	for (let p = 0; p + 30 < buf.length && buf.readUInt32LE(p) === 0x04034b50;) {
		const method = buf.readUInt16LE(p + 8), size = buf.readUInt32LE(p + 18), nl = buf.readUInt16LE(p + 26), xl = buf.readUInt16LE(p + 28);
		const name = buf.slice(p + 30, p + 30 + nl).toString(), data = buf.slice(p + 30 + nl + xl, p + 30 + nl + xl + size);
		if (name === want) return (method === 8 ? zlib.inflateRawSync(data) : data).toString('utf8');
		p += 30 + nl + xl + size;
	}
	return null;
}
const ROWS = [['Name', 'City', 'Amount'], ['Ada Lovelace', 'London', 10], ['Grace Hopper', 'New York, NY', 20], ['Katherine Johnson', 'Hampton', 30]];
function makeXlsx() {
	const ss = [], si = (s) => (ss.includes(s) ? 0 : ss.push(s), ss.indexOf(s));
	const NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"', REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
	const rows = ROWS.map((r, i) => `<row r="${i + 1}">` + r.map((v, j) => {
		const ref = 'ABC'[j] + (i + 1);
		return typeof v === 'string' ? `<c r="${ref}" t="s"><v>${si(v)}</v></c>` : `<c r="${ref}"><v>${v}</v></c>`;
	}).join('') + '</row>').join('');
	return zip({
		'[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
		'_rels/.rels': `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
		'xl/workbook.xml': `<?xml version="1.0" encoding="UTF-8"?><workbook ${NS} xmlns:r="${REL}"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>`,
		'xl/_rels/workbook.xml.rels': `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="${REL}/sharedStrings" Target="sharedStrings.xml"/></Relationships>`,
		'xl/worksheets/sheet1.xml': `<?xml version="1.0" encoding="UTF-8"?><worksheet ${NS}><sheetData>${rows}</sheetData></worksheet>`,
		'xl/sharedStrings.xml': `<?xml version="1.0" encoding="UTF-8"?><sst ${NS} count="${ss.length}" uniqueCount="${ss.length}">` + ss.map(s => `<si><t>${s}</t></si>`).join('') + '</sst>',
	});
}

// --- x2t, called the way desktop-sdk CConvertFileInEditor (fileconverter.h) calls it ------------------------
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function x2t(tmp, from, to, format) {
	const work = fs.mkdtempSync(path.join(tmp, 'FC_'));
	fs.mkdirSync(path.join(work, 'tmp'));
	const fonts = path.join(tmp, 'fonts');
	fs.writeFileSync(path.join(work, 'params.xml'), `<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>${esc(from)}</m_sFileFrom>` +
		`<m_sFileTo>${esc(to)}</m_sFileTo><m_nFormatTo>${format}</m_nFormatTo><m_sFontDir>${esc(fonts)}</m_sFontDir><m_bIsNoBase64>false</m_bIsNoBase64>` +
		`<m_sAllFontsPath>${esc(fonts)}/AllFonts.js</m_sAllFontsPath><m_sTempDir>${esc(path.join(work, 'tmp'))}</m_sTempDir>` +
		`<m_bDontSaveAdditional>true</m_bDontSaveAdditional><m_nDoctParams>1</m_nDoctParams></TaskQueueDataConvert>`);
	const r = spawnSync(path.join(CORE_BIN, 'x2t'), [path.join(work, 'params.xml')], { env: Object.assign({}, process.env, { DYLD_FRAMEWORK_PATH: CORE_LIB }), timeout: 120000 });
	return r.status;
}

async function run(webapps, sdkjs, tmp) {
	const fontsCopy = path.join(tmp, 'fonts');
	fs.mkdirSync(fontsCopy);
	for (const f of ['AllFonts.js', 'font_selection.bin']) fs.copyFileSync(path.join(FONTS, f), path.join(fontsCopy, f));
	const allFonts = path.join(tmp, 'AllFonts.js');
	fs.copyFileSync(path.join(FONTS, 'AllFonts.js'), allFonts);

	const xlsx = path.join(tmp, 'recipients.xlsx');
	fs.writeFileSync(xlsx, makeXlsx());
	const csv = path.join(tmp, 'recipients.csv');
	fs.writeFileSync(csv, '﻿Name;City;Amount\r\nZoë Ångström;"Paris; FR";40\r\nAlan Turing;Wilmslow;50\r\n');
	let pickNext = xlsx;
	const host = {
		pick: () => pickNext,
		convert: (p, format) => {
			const folder = fs.mkdtempSync(path.join(tmp, 'FC_')), out = path.join(folder, 'Editor.bin');
			const code = x2t(tmp, p, out, format);
			return { code, b64: code === 0 && fs.existsSync(out) ? fs.readFileSync(out).toString('base64') : null };
		},
		read: (p) => fs.existsSync(p) ? fs.readFileSync(p).toString('base64') : null,
	};

	const o = await openEditor({ webapps, webappsDeploy: DEPLOY, sdkjs, allFonts, editorBin: path.join(CORE, 'Common', 'empty', 'docx.bin'),
		doctype: 'word', filetype: 'docx', host });
	const f = o.frame, page = o.page;
	const ev = (fn, arg) => f.evaluate(fn, arg);
	let merged = null;
	try {
		await f.waitForFunction(() => window.DE && document.querySelector('#toolbar .panel.active') &&
			window.DE.getController('Toolbar').toolbar && $('#toolbar .ribtab:visible').length > 3, null, { timeout: 180000 });
		await sleep(2500);
		await ev(() => {
			window.api = DE.getController('Main').api;
			window.tb = DE.getController('Toolbar').toolbar;
			window.rc = DE.getController('Common.Controllers.ReviewChanges').view;
			window.mm = () => DE.getController('RightMenu').rightmenu.mergeSettings;
			window.__text = () => api.WordControl.m_oLogicDocument.Content.map(p => p.GetText ? p.GetText().replace(/\s+$/, '') : '').join('|');
			window.__started = 0;
			api.asc_registerCallback('asc_onStartMailMerge', () => window.__started++);
			Common.UI.Menu.Manager.hideAll();
			$('.synch-tip-root').remove();
		});

		// 1. the Mail Merge button, From file only
		const b = await ev(() => {
			const btn = window.rc && rc.btnMailRecepients;
			if (!btn) return null;
			tb.setTab('review');
			$('#id-toolbar-btn-mailrecepients button').first().click();
			return { visible: btn.$el.is(':visible'), items: rc.mnuMailRecepients.items.map(i => [i.value, i.isVisible()]) };
		});
		if (!check('offline: Collaboration tab has Mail Merge; its menu shows only "From file"',
			b && b.visible && JSON.stringify(b.items) === '[["file",true],["url",false],["storage",false]]', b)) throw new Error('no mail merge');

		// 2. From file -> native "cell" dialog -> x2t JSON -> panel with 3 recipients
		await ev(() => { rc.mnuMailRecepients.items[0].cmpEl.find('a').click(); });
		await f.waitForFunction(() => window.__started > 0 || (window.__converts && window.__converts.length && !api.isLongAction()), null, { timeout: 60000 }).catch(() => {});
		await sleep(1500);
		const st = await ev(() => ({ dialogs: window.__dialogs, converts: window.__converts, started: window.__started, count: api.asc_GetReceptionsCount(),
			fields: api.asc_GetMailMergeFieldsNameList(), panel: !!mm() && $('#id-mail-merge-settings').is(':visible') }));
		check('"From file": the host is asked for a "cell" dialog and the picked .xlsx goes to convertFile as JSON (0x0808)',
			JSON.stringify(st.dialogs) === '["cell"]' && st.converts && st.converts.length === 1 && st.converts[0].path === xlsx && st.converts[0].format === 0x0808, st);
		check('the recipients are loaded (3) with fields Name, City, Amount, and the Mail Merge panel is open',
			st.started === 1 && st.count === 3 && JSON.stringify(st.fields) === '["Name","City","Amount"]' && st.panel, st);

		// 3. type text and insert the fields from the panel's menu
		const box = await ev(() => { const r = document.getElementById('id_viewer').getBoundingClientRect(), fr = window.frameElement.getBoundingClientRect();
			return { x: fr.left + r.left + r.width / 2, y: fr.top + r.top + 120 }; });
		await page.mouse.click(box.x, box.y);
		await sleep(300);
		const insert = (name) => ev((n) => { const it = mm().btnInsField.menu.items.find(i => i.options.field === n); it.trigger('click', it, {}); }, name);
		await page.keyboard.type('Dear ');
		await insert('Name');
		await page.keyboard.type(' from ');
		await insert('City');
		await page.keyboard.type(', amount ');
		await insert('Amount');
		await page.keyboard.type('.');
		await sleep(500);
		const t0 = await ev(() => __text());
		check('fields inserted from the panel: the template reads Dear «Name» from «City», amount «Amount».',
			/^Dear «Name» from «City», amount «Amount»\.$/.test(t0), t0);

		// 4. preview, next -> record 2
		await ev(() => { mm().chPreview.setValue(true); });
		await sleep(600);
		const t1 = await ev(() => __text());
		await ev(() => { mm().btnNext.$el.find('button').addBack().filter('button').first().click(); });
		await sleep(800);
		const t2 = await ev(() => ({ text: __text(), num: mm().txtFieldNum.getValue() }));
		check('preview shows record 1, Next shows record 2 (Grace Hopper)',
			t1 === 'Dear Ada Lovelace from London, amount 10.' && t2.num == 2 && t2.text === 'Dear Grace Hopper from New York, NY, amount 20.', { t1, t2 });
		await ev(() => { mm().chPreview.setValue(false); });
		await sleep(500);

		// 5. merge to a new document
		const ui = await ev(() => ({ to: mm().cmbMergeTo.store.map(r => [r.get('displayValue'), r.get('value')]), caption: mm().btnDownload.$el.text().trim(),
			visible: mm().btnDownload.$el.is(':visible') }));
		check('"Merge to" lists only "New document"; the button says Merge',
			JSON.stringify(ui.to) === JSON.stringify([['New document', 0x41]]) && ui.caption === 'Merge' && ui.visible, ui);
		await ev(() => { mm().radioAll.setValue(true); mm().btnDownload.$el.click(); });
		await sleep(1500);
		const nf = await ev(() => ({ n: (window.__newFiles || []).length, b64: (window.__newFiles || [])[0], text: __text(), alert: $('.asc-window.alert:visible').length }));
		check('Merge hands the host one new-file binary (OpenBinaryAsNewFile); this document is unchanged, no error',
			nf.n === 1 && !!nf.b64 && nf.text === 'Dear «Name» from «City», amount «Amount».' && nf.alert === 0, { n: nf.n, text: nf.text, alert: nf.alert });
		merged = nf.b64 ? Buffer.from(nf.b64, 'base64') : null;

		// 6. a CSV through loadLocalFile
		pickNext = csv;
		await ev(() => { window.__converts = []; api.asc_StartMailMerge(); });
		await sleep(1500);
		const cs = await ev(() => ({ reads: window.__reads, converts: window.__converts.length, count: api.asc_GetReceptionsCount(), fields: api.asc_GetMailMergeFieldsNameList(),
			rows: [0, 1].map(i => ['Name', 'City', 'Amount'].map(n => api.asc_GetMailMergeFiledValue(i, n))) }));
		check('a .csv (UTF-8 BOM, ";", quoted "Paris; FR", non-ASCII) is read with loadLocalFile, not x2t, into the right rows',
			JSON.stringify(cs.reads) === JSON.stringify([csv]) && cs.converts === 0 && cs.count === 2 && JSON.stringify(cs.fields) === '["Name","City","Amount"]' &&
			JSON.stringify(cs.rows) === JSON.stringify([['Zoë Ångström', 'Paris; FR', '40'], ['Alan Turing', 'Wilmslow', '50']]), cs);

		const errs = o.errors.filter(e => !/widgetType/.test(e));
		check('no uncaught page errors', errs.length === 0, errs.map(e => e.split('\n')[0]));
	} catch (e) {
		check('run', false, String(e && e.message || e).split('\n')[0]);
	} finally {
		await o.browser.close();
		o.srv.close();
	}
	if (!merged) { check('merged document', false, 'no binary'); return; }

	// 7. the binary opened as the new tab is: one section per record with that record's text
	const mergedBin = path.join(tmp, 'merged', 'Editor.bin');
	fs.mkdirSync(path.dirname(mergedBin));
	fs.writeFileSync(mergedBin, merged);
	const o2 = await openEditor({ webapps, webappsDeploy: DEPLOY, sdkjs, allFonts, editorBin: mergedBin, doctype: 'word', filetype: 'docx', host });
	try {
		await o2.frame.waitForFunction(() => window.DE && DE.getController('Main').api && DE.getController('Main').api.WordControl &&
			DE.getController('Main').api.WordControl.m_oLogicDocument && DE.getController('Main').api.WordControl.m_oLogicDocument.Content.length > 1, null, { timeout: 180000 });
		await sleep(2000);
		const secs = await o2.frame.evaluate(() => {
			const out = [[]];
			for (const p of DE.getController('Main').api.WordControl.m_oLogicDocument.Content) {
				const t = p.GetText ? p.GetText().replace(/\s+$/, '') : '';
				if (t) out[out.length - 1].push(t);
				if (p.Get_SectionPr && p.Get_SectionPr()) out.push([]);
			}
			return out.filter(s => s.length).map(s => s.join('|'));
		});
		check('the new tab: one section per record, each with its own text', JSON.stringify(secs) === JSON.stringify([
			'Dear Ada Lovelace from London, amount 10.', 'Dear Grace Hopper from New York, NY, amount 20.', 'Dear Katherine Johnson from Hampton, amount 30.']), secs);
	} catch (e) {
		check('open the merged binary', false, String(e && e.message || e).split('\n')[0]);
	} finally {
		await o2.browser.close();
		o2.srv.close();
	}
	const docx = path.join(tmp, 'merged.docx');
	const code = x2t(tmp, mergedBin, docx, 65);
	const xml = code === 0 && fs.existsSync(docx) ? unzipEntry(fs.readFileSync(docx), 'word/document.xml') || '' : '';
	const text = xml.split(/<\/w:p>/).map(p => (p.match(/<w:t(?: [^>]*)?>[^<]*<\/w:t>/g) || []).map(t => t.replace(/<[^>]+>/g, '')).join('')).filter(Boolean);
	const sects = (xml.match(/<w:sectPr\b/g) || []).length;
	check('x2t saves the new tab as DOCX with the three letters, each in its own section', code === 0 && JSON.stringify(text) === JSON.stringify([
		'Dear Ada Lovelace from London, amount 10.', 'Dear Grace Hopper from New York, NY, amount 20.', 'Dear Katherine Johnson from Hampton, amount 30.']) && sects >= 3,
		{ code, text, sects });
}

(async () => {
	for (const [p, what] of [[SDKJS, 'sdkjs deploy (RD_SDKJS)'], [path.join(DEPLOY, 'apps'), 'web-apps deploy (RD_WEBAPPS_DEPLOY)'],
		[path.join(CORE, 'Common', 'empty'), 'core (RD_CORE)'], [path.join(CORE_BIN, 'x2t'), 'x2t (RD_CORE_BIN)'], [path.join(FONTS, 'AllFonts.js'), 'fonts cache (RD_FONTS)']]) {
		if (!fs.existsSync(p)) { console.log(`SKIP #733: ${what} not found: ${p}`); process.exit(0); }
	}
	const tmp = fs.mkdtempSync(path.join(process.env.RD_TMP || os.tmpdir(), 'rd733-'));
	try {
		const { webapps, sdkjs } = prepare(tmp);
		await run(webapps, sdkjs, tmp);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
	if (failed) {
		console.log(`${failed} check(s) failed${process.env.BASELINE ? ' (BASELINE)' : ''}`);
		process.exit(1);
	}
	console.log('all checks passed');
})();
