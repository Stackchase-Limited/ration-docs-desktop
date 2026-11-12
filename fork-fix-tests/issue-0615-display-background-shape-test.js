/*
 * #615 (part 1) - a docx with <w:background w:color="00B8FF"/> but no
 * <w:displayBackgroundShape/> in settings.xml: Word shows a white page
 * (ECMA-376 17.15.1.25 - without the flag the background is not displayed),
 * we painted it blue, and saving switched the flag on, so the file turned
 * blue in Word too.
 *
 * Fix (sdkjs side; core has its own test, issue-0615-display-background-shape-core):
 * core passes the flag inside the binary Background item (DisplayShape,
 * type 100, byte 0 absent / 1 on / 2 off). DocumentBackground keeps it in
 * displayShape and draws only when it is on or undefined (page colour set in
 * the editor / binary from an older core); the writer passes it back.
 *
 * This runs the REAL document-background.js (whole file, against stubs) and
 * the REAL Binary_DocumentTableReader.ReadBackground / BinaryDocumentTableWriter
 * .WriteBackground from Serialize2.js (brace-matched), on the bytes core
 * writes, and checks: the flag survives read -> write byte-for-byte for all
 * three states, the page is not drawn unless the flag is on, a white loaded
 * background is not dropped as "default", and a colour set in the editor is
 * drawn.
 *
 * NOT claimed: rendering in the GUI (checked with docbuilder: the reporter's
 * file gives a white PDF page, and docx -> docx keeps background and flag);
 * collaborative changes (CChangesDocumentPageColor) do not carry the flag -
 * a page colour change always produces a shown background, which is right.
 *
 *   RD_REPO=<sdkjs checkout>  (default ../../sdkjs relative to this file)
 *   BASELINE=1                read sources at BASE_REF; must FAIL
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const BASE_REF = process.env.BASE_REF || 'ecd1f58829^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const ser = src('word/Editor/Serialize2.js');
const bgSrc = src('word/Editor/document/document-background.js');

/* constants exactly as Serialize2.js declares them */
const common = src('common/SerializeCommonWordExcel.js');
const consts = new Function(extract(ser, 'var c_oSerBackgroundType =') + ';\n' +
	extract(common, 'var c_oSerPropLenType =') + ';\nreturn {c_oSerBackgroundType, c_oSerPropLenType};')();
const c_oSerConstants = { ReadOk: 0, ReadUnknown: 1 };

/* --- stubs --- */
function CDocumentColor(r, g, b, auto) { this.r = r; this.g = g; this.b = b; this.Auto = !!auto; }
CDocumentColor.prototype.IsEqualRGB = function(c) { return this.r === c.r && this.g === c.g && this.b === c.b; };
let drawn = 0;
const window = { AscWord: {} };
const AscFormat = {
	CreateSolidFillRGB(r, g, b) { return { isVisible() { return true; }, check() {}, isSolidFill() { return true; }, getRGBAColor() { return { R: r, G: g, B: b }; } }; },
	ObjectToDraw: function() {},
};
const AscCommon = {
	CShapeDrawer: function() { this.fromShape2 = function() {}; this.draw = function() { drawn++; }; },
	CreateAscColorCustom(r, g, b) { return { r, g, b }; },
};
new Function('window', 'AscFormat', 'AscCommon', 'CDocumentColor', bgSrc)(window, AscFormat, AscCommon, CDocumentColor);
const DocumentBackground = window.AscWord.DocumentBackground;

/* byte memory + the parts of BinaryCommonWriter / Read2 the two functions use */
function Memory() { this.data = []; }
Memory.prototype.WriteByte = function(b) { this.data.push(b & 0xFF); };
Memory.prototype.WriteLong = function(v) { for (let i = 0; i < 4; i++) this.data.push((v >>> (8 * i)) & 0xFF); };
function Stream(data) { this.data = data; this.pos = 0; }
Stream.prototype.GetUChar = function() { return this.data[this.pos++]; };
Stream.prototype.GetLong = function() { let v = 0; for (let i = 0; i < 4; i++) v |= this.data[this.pos++] << (8 * i); return v; };

const { c_oSerBackgroundType, c_oSerPropLenType } = consts;
function makeWriter(memory) {
	const w = { memory, bs: {
		WriteColor(type, color) { memory.WriteByte(type); memory.WriteByte(c_oSerPropLenType.Three); memory.WriteByte(color.r); memory.WriteByte(color.g); memory.WriteByte(color.b); },
		WriteItemWithLength() { throw new Error('not used in this test'); },
	} };
	new Function('c_oSerBackgroundType', 'c_oSerPropLenType', 'editor', 'AscCommonWord',
		'this.' + extract(ser, 'WriteBackground = function(oBackground)') + ';').call(w, c_oSerBackgroundType, c_oSerPropLenType, null, { CDocumentColor });
	return w;
}
function readBackground(bytes, bg) {
	const r = { stream: new Stream(bytes), bcr: { ReadColor() { const s = r.stream; return new CDocumentColor(s.GetUChar(), s.GetUChar(), s.GetUChar()); } } };
	new Function('c_oSerBackgroundType', 'c_oSerConstants', 'CDocumentColor',
		'this.' + extract(ser, 'ReadBackground = function(type, length, oBackground)') + ';').call(r, c_oSerBackgroundType, c_oSerConstants, CDocumentColor);
	/* Read2: type, length type, value (only Byte and Three are used here) */
	const s = r.stream;
	while (s.pos < bytes.length) {
		const type = s.GetUChar(), lenType = s.GetUChar();
		const len = lenType === c_oSerPropLenType.Byte ? 1 : lenType === c_oSerPropLenType.Three ? 3 : lenType === c_oSerPropLenType.Long ? 4 : -1;
		assert.ok(len > 0, 'unexpected length type ' + lenType);
		const start = s.pos;
		if (r.ReadBackground(type, len, bg) === c_oSerConstants.ReadUnknown) s.pos = start + len;
		assert.strictEqual(s.pos, start + len);
	}
}

/* what core's WriteBackground produces for <w:background w:color="00B8FF"/>: Color, then DisplayShape */
const CORE_DISPLAY_SHAPE = 100;
function coreBytes(flag) { return [c_oSerBackgroundType.Color, c_oSerPropLenType.Three, 0x00, 0xB8, 0xFF, CORE_DISPLAY_SHAPE, c_oSerPropLenType.Byte, flag]; }
const sectPr = { GetPageHeight() { return 297; }, GetPageWidth() { return 210; } };
const graphics = { StartDrawShape() {}, EndDrawShape() {}, setEndGlobalAlphaColor() {} };
const NAMES = { 0: 'absent', 1: 'on', 2: 'w:val="0"' };
let fails = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { fails++; console.log('FAIL ' + name + ': ' + e.message); }
}

for (const flag of [0, 1, 2]) {
	check(`flag ${NAMES[flag]}: read, drawn only when on, written back byte-for-byte`, () => {
		const bg = new DocumentBackground();
		readBackground(coreBytes(flag), bg);
		assert.ok(bg.Color && bg.Color.b === 0xFF, 'colour not read');
		drawn = 0;
		bg.draw(graphics, sectPr, null, null);
		assert.strictEqual(drawn, flag === 1 ? 1 : 0, `page background drawn=${drawn} with displayBackgroundShape ${NAMES[flag]} (Word: ${flag === 1 ? 'shown' : 'white'})`);
		const copy = bg.copy();
		assert.strictEqual(copy.isDefault(), false, 'a background from the file would not be saved');
		const mem = new Memory();
		makeWriter(mem).WriteBackground(copy);
		assert.deepStrictEqual(mem.data, coreBytes(flag), 'bytes written back differ from what core sent: flag lost on save');
	});
}

check('white background from a file without the flag is still written', () => {
	const bg = new DocumentBackground();
	readBackground([c_oSerBackgroundType.Color, c_oSerPropLenType.Three, 255, 255, 255, CORE_DISPLAY_SHAPE, c_oSerPropLenType.Byte, 0], bg);
	assert.strictEqual(bg.isDefault(), false, 'the white w:background would be dropped on save');
});

check('page colour set in the editor (no flag byte) is drawn and written without the byte', () => {
	const bg = new DocumentBackground(new CDocumentColor(255, 0, 0), null, null);
	drawn = 0;
	bg.draw(graphics, sectPr, null, null);
	assert.strictEqual(drawn, 1);
	const mem = new Memory();
	makeWriter(mem).WriteBackground(bg);
	assert.deepStrictEqual(mem.data, [c_oSerBackgroundType.Color, c_oSerPropLenType.Three, 255, 0, 0], 'core turns the flag on for this');
	assert.ok(new DocumentBackground().isDefault(), 'empty background must stay default');
});

console.log(fails ? `FAIL ${fails} check(s)` : 'PASS #615 display background flag (sdkjs)');
process.exit(fails ? 1 : 0);
