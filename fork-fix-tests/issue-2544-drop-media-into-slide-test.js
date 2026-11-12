/*
 * #2544 "Support drag & drop of video/audio files into slides".
 *
 * Dragging an .mp4 / .mp3 from the file manager onto a slide does nothing;
 * only Insert > Video / Audio can add media.
 *
 * Cause: the desktop drop handler (sdkjs common/Local/common.js,
 * AscCommon.InitDragAndDrop ondrop) inserts only files that
 * AscDesktopEditor.IsImageFile() accepts. Since #2095 every other file goes to
 * DropOfficeFiles ("open in a new tab"), whose native format check cannot open
 * media, so nothing happened.
 *
 * Fix: in the presentation editor (api with asc_AddVideoCallback, editorId
 * Presentation) a dropped video/audio file (by extension) is inserted with
 * AscDesktopEditor.AddVideo / AddAudio + asc_AddVideoCallback /
 * asc_AddAudioCallback, the calls Insert > Video / Audio make.
 *
 * This extracts the REAL InitDragAndDrop + IsDesktopFilesDrag (Local/common.js)
 * and the REAL CanDropFiles + isValidImageDragItem (editorscommon.js) by brace
 * matching and drives them with a synthetic drag. The AscDesktopEditor stub
 * models client_renderer_wrapper.cpp: GetDropFiles returns AND clears the drop
 * list; AddVideo/AddAudio store the callback in window.on_add_multimedia_local
 * and the host later runs "on_add_multimedia_local(...);
 * on_add_multimedia_local = undefined;" asynchronously (ExecuteJavaScript).
 *
 * NOT claimed: that the native side copies the file and the slide shows the
 * poster (existing Insert > Video code; needs a GUI check), nor where on the
 * slide the object lands (same place as Insert > Video, not at the drop point).
 *
 *   node fork-fix-tests/issue-2544-drop-media-into-slide-test.js
 *   RD_REPO=<sdkjs checkout>   (default ../sdkjs)
 *   BASELINE=1                 runs against BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const BASE_REF = process.env.BASE_REF || '660fdeb7c9^';
const BASELINE = !!process.env.BASELINE;

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function extract(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) return null;
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}

const local = src('common/Local/common.js');
const common = src('common/editorscommon.js');
const initSrc = extract(local, 'AscCommon.InitDragAndDrop = function');
assert.ok(initSrc && initSrc.includes('GetDropFiles'), 'wrong InitDragAndDrop block');
const filesDragSrc = extract(local, 'AscCommon.IsDesktopFilesDrag = function');
const canDropSrc = extract(common, 'function CanDropFiles(event)');
const imgItemSrc = extract(common, 'function isValidImageDragItem(item)');
assert.ok(filesDragSrc && canDropSrc && imgItemSrc, 'helpers not found');

const EDITOR_ID = { Word: 0, Spreadsheet: 1, Presentation: 2, PDF: 3 };
const IMAGES = new Set(['/Users/x/photo.png']);

async function run(opts) {
	const log = { inserted: [], media: [], opened: null, pasteText: [], dropDelivered: false };
	let nativeDropList = [];
	const pending = [];
	const window = {};
	let counter = 0;
	function hostAnswer(args) {
		// host: ExecuteJavaScript("on_add_multimedia_local(...); on_add_multimedia_local = undefined;")
		pending.push(() => { window.on_add_multimedia_local(...args); window.on_add_multimedia_local = undefined; });
		setTimeout(() => pending.shift()(), 0);
	}
	const AscDesktopEditor = {
		SetDropFiles(arr) { nativeDropList = arr.slice(); },
		GetDropFiles() { const r = nativeDropList; nativeDropList = []; return r; },
		IsImageFile(p) { return IMAGES.has(p); },
		LocalFileGetImageUrl(p) { return 'media/' + path.basename(p); },
		DropOfficeFiles() { log.opened = nativeDropList.slice(); },
		AddVideo(file, cb) { window.on_add_multimedia_local = cb; const n = counter++; hostAnswer([`display8image${n}.png`, `display8image${n}.mp4#${path.basename(file)}`, 1920, 1080]); },
		AddAudio(file, cb) { window.on_add_multimedia_local = cb; const n = counter++; hostAnswer([`display8image${n}.png`, `display8image${n}.mp3#${path.basename(file)}`]); },
	};
	const editor = {
		editorId: opts.editorId,
		canEdit: () => opts.canEdit !== false,
		isEnabledDropTarget: () => opts.dropTarget !== false,
		beginInlineDropTarget() {}, endInlineDropTarget() {},
		_addImageUrl(urls) { log.inserted.push(...urls); },
		pluginMethod_PasteText(t) { log.pasteText.push(t); },
		pluginMethod_PasteHtml() {},
	};
	if (opts.editorId === EDITOR_ID.Presentation) {
		editor.asc_AddVideoCallback = (img, url, obj, w, h) => log.media.push(['video', url, w, h]);
		editor.asc_AddAudioCallback = (img, url) => log.media.push(['audio', url]);
	}
	window.Asc = { editor };
	window.AscDesktopEditor = AscDesktopEditor;
	const AscCommon = {
		AscBrowser: { isSafari: false },
		c_oEditorId: EDITOR_ID,
		g_oDocumentUrls: { getImageUrl: (u) => 'docurl/' + u },
	};
	new Function('window', 'AscCommon', 'FileReader', 'setTimeout',
		imgItemSrc + '\n' + canDropSrc + '\nAscCommon.CanDropFiles = CanDropFiles;\n' +
		filesDragSrc + ';\n' + initSrc + ';')(window, AscCommon, function FileReader() {}, setTimeout);

	const el = {};
	AscCommon.InitDragAndDrop(el, () => {});
	AscDesktopEditor.SetDropFiles(opts.paths || []);
	const dt = { types: opts.types || ['Files'], items: opts.items, dropEffect: 'none', getData: (t) => (opts.data && opts.data[t]) || '' };
	const ev = { dataTransfer: dt, preventDefault() {} };
	el.ondragover(ev);
	if (dt.dropEffect !== 'none') {
		log.dropDelivered = true;
		el.ondrop(ev);
	}
	await new Promise((r) => setTimeout(r, 50));
	return log;
}

const item = (type) => ({ kind: 'file', type });
const P = EDITOR_ID.Presentation;

const cases = [
	{
		name: 'A. an .mp4 dropped on a slide is inserted as a video (with its size)',
		opts: { editorId: P, items: [item('video/mp4')], paths: ['/Users/x/clip one.mp4'] },
		check(l) {
			assert.ok(l.dropDelivered, 'dragover refused the drop');
			assert.deepStrictEqual(l.media, [['video', 'display8image0.mp4#clip one.mp4', 1920, 1080]], 'video not inserted');
			assert.strictEqual(l.opened, null, 'media file handed to DropOfficeFiles');
		},
	},
	{
		name: 'B. an .MP3 (upper case) is inserted as audio',
		opts: { editorId: P, items: [item('audio/mpeg')], paths: ['/Users/x/song.MP3'] },
		check(l) { assert.deepStrictEqual(l.media, [['audio', 'display8image0.mp3#song.MP3']]); assert.strictEqual(l.opened, null); },
	},
	{
		name: 'C. video + audio + image + docx: all media inserted in order, image inserted, docx opened',
		opts: { editorId: P, items: [item('video/quicktime'), item('audio/wav'), item('image/png'), item('')],
			paths: ['/Users/x/a.mov', '/Users/x/b.wav', '/Users/x/photo.png', '/Users/x/r.docx'] },
		check(l) {
			assert.deepStrictEqual(l.media.map((m) => m[1]), ['display8image0.mp4#a.mov', 'display8image1.mp3#b.wav']);
			assert.deepStrictEqual(l.inserted, ['docurl/media/photo.png']);
			assert.deepStrictEqual(l.opened, ['/Users/x/r.docx']);
		},
	},
	/* --- unchanged behaviour --- */
	{
		name: 'D. Word editor: an .mp4 still goes to DropOfficeFiles (no media insert there)',
		regression: true,
		opts: { editorId: EDITOR_ID.Word, items: [item('video/mp4')], paths: ['/Users/x/clip.mp4'] },
		check(l) { assert.deepStrictEqual(l.media, []); assert.deepStrictEqual(l.opened, ['/Users/x/clip.mp4']); },
	},
	{
		name: 'E. slide with drop target disabled (view mode): nothing inserted',
		regression: true,
		opts: { editorId: P, dropTarget: false, items: [item('video/mp4')], paths: ['/Users/x/clip.mp4'] },
		check(l) { assert.deepStrictEqual(l.media, []); },
	},
	{
		name: 'E2. read-only presentation: a dropped video is not inserted',
		regression: true,
		opts: { editorId: P, canEdit: false, items: [item('video/mp4')], paths: ['/Users/x/clip.mp4'] },
		check(l) { assert.deepStrictEqual(l.media, []); },
	},
	{
		name: 'F. slide: a .pptx still opens in a new tab, an image is still inserted',
		regression: true,
		opts: { editorId: P, items: [item('image/png'), item('')], paths: ['/Users/x/photo.png', '/Users/x/deck.pptx'] },
		check(l) { assert.deepStrictEqual(l.media, []); assert.deepStrictEqual(l.inserted, ['docurl/media/photo.png']); assert.deepStrictEqual(l.opened, ['/Users/x/deck.pptx']); },
	},
	{
		name: 'G. slide: dragged text is still pasted',
		regression: true,
		opts: { editorId: P, types: ['text/plain'], items: [{ kind: 'string', type: 'text/plain' }], paths: [], data: { 'text/plain': 'hi' } },
		check(l) { assert.deepStrictEqual(l.pasteText, ['hi']); assert.deepStrictEqual(l.media, []); },
	},
];

(async () => {
	let failed = 0;
	for (const c of cases) {
		try {
			c.check(await run(c.opts));
			console.log('ok   ' + c.name);
		} catch (e) {
			failed++;
			console.log('FAIL ' + c.name + ' :: ' + e.message.split('\n')[0]);
		}
	}
	if (failed) {
		console.log(`FAIL #2544: ${failed}/${cases.length} cases` + (BASELINE ? ' (BASELINE, expected)' : ''));
		process.exit(1);
	}
	console.log('PASS #2544: video/audio files dropped on a slide are inserted; other drops unchanged' + (BASELINE ? ' (BASELINE?!)' : ''));
})();
