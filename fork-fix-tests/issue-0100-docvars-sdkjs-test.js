/*
 * #100 "Support variables", editor side - document variables (settings.xml
 * w:docVars, read by DOCVARIABLE fields) were dropped by every save.
 *
 * Before: core did not put w:docVars into the binary, and the editor's
 * settings reader/writer (word/Editor/Serialize2.js Binary_SettingsTableReader
 * / BinarySettingsTableWriter) had no item for them either, so a document
 * saved from the editor lost all its variables; Word then shows "Error! No
 * document variable supplied." for each DOCVARIABLE field.
 *
 * Now: core writes a DocVars settings item (c_oSer_SettingsType 100); the
 * editor reads it into DocumentSettings.DocVars ([{name, value}], not edited)
 * and writes it back unchanged on save. Core side:
 * issue-0100-docvars-core/extract_and_run.py.
 *
 * This extracts the REAL c_oSer_SettingsType / c_oSerDocVars tables, the
 * DocVars statement of WriteSettings, WriteDocVars, the DocVars branch of
 * ReadSettingsContent and ReadDocVars from Serialize2.js by brace matching and
 * runs them against a stub byte stream with the binary's item framing (type
 * byte, 4-byte length, UTF-16LE strings).
 *
 * NOT claimed: no UI to view or edit variables; DOCVARIABLE fields keep the
 * result stored in the file (Update field does not recompute them). Checked
 * separately, not here: docbuilder (x2t + this sdkjs) open/edit/save of a docx
 * keeps w:docVars; with the payload sdkjs they are gone.
 *
 *   node fork-fix-tests/issue-0100-docvars-sdkjs-test.js
 *   RD_REPO=<sdkjs checkout>   (default ../sdkjs)
 *   BASELINE=1                 runs against BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const BASE_REF = process.env.BASE_REF || '87ae50a92a^';
const BASELINE = !!process.env.BASELINE;

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}
function extract(text, marker, from) {
	const at = text.indexOf(marker, from || 0);
	if (at === -1) return null;
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}
const ser = src('word/Editor/Serialize2.js');
const settingsJs = src('word/Editor/DocumentSettings.js');

/* ---- stub stream with the binary's framing */
const ReadOk = 0, ReadUnknown = 1;
function makeWriter() {
	const bytes = [];
	const memory = {
		WriteString3(s) { for (const ch of String(s)) { const c = ch.charCodeAt(0); bytes.push(c & 0xff, c >> 8); } },
	};
	const bs = {
		WriteItem(type, fn) {
			bytes.push(type); const at = bytes.length; bytes.push(0, 0, 0, 0); fn();
			const len = bytes.length - at - 4; for (let i = 0; i < 4; i++) bytes[at + i] = (len >> (8 * i)) & 0xff;
		},
	};
	return { bytes, memory, bs };
}
function makeReader(bytes) {
	let pos = 0;
	const stream = {
		GetUChar: () => bytes[pos++],
		GetLong: () => { let v = 0; for (let i = 0; i < 4; i++) v |= bytes[pos++] << (8 * i); return v; },
		GetString2LE(n) { let s = ''; for (let i = 0; i < n; i += 2) s += String.fromCharCode(bytes[pos + i] | (bytes[pos + i + 1] << 8)); pos += n; return s; },
		Skip2(n) { pos += n; },
		get pos() { return pos; },
	};
	const bcr = {
		Read1(len, fn) {
			let cur = 0, res = ReadOk;
			while (cur < len) {
				const t = stream.GetUChar(), l = stream.GetLong();
				res = fn(t, l);
				if (res === ReadUnknown) { stream.Skip2(l); res = ReadOk; } else if (res !== ReadOk) break;
				cur += l + 5;
			}
			return res;
		},
	};
	return { stream, bcr };
}

function tables() {
	const t = extract(ser, 'var c_oSer_SettingsType');
	const d = extract(ser, 'var c_oSerDocVars');
	assert.ok(t && d, 'Serialize2.js: no c_oSerDocVars table');
	const r = new Function(t + ';' + d + ';return [c_oSer_SettingsType, c_oSerDocVars];')();
	assert.ok(r[0].DocVars !== undefined, 'c_oSer_SettingsType has no DocVars item');
	return r;
}

function writeSettings(settings) {
	const [ST, DV] = tables();
	const wAt = ser.indexOf('function BinarySettingsTableWriter');
	const stmt = ser.slice(ser.indexOf('if (settings.DocVars', wAt), ser.indexOf('});', ser.indexOf('if (settings.DocVars', wAt)) + 3);
	assert.ok(ser.indexOf('if (settings.DocVars', wAt) !== -1, 'WriteSettings writes no DocVars item');
	const wdv = extract(ser, 'this.WriteDocVars = function', wAt);
	assert.ok(wdv, 'BinarySettingsTableWriter.WriteDocVars missing');
	const w = makeWriter();
	const oThis = { bs: w.bs, memory: w.memory };
	new Function('oThis', 'c_oSerDocVars', wdv + ';').call(oThis, oThis, DV);
	new Function('oThis', 'settings', 'c_oSer_SettingsType', 'c_oSerDocVars', stmt).call(oThis, oThis, settings, ST, DV);
	return w.bytes;
}

function readSettings(bytes) {
	const [ST, DV] = tables();
	const rAt = ser.indexOf('function Binary_SettingsTableReader');
	const brAt = ser.indexOf('else if (c_oSer_SettingsType.DocVars === type)', rAt);
	assert.ok(brAt !== -1, 'ReadSettingsContent has no DocVars branch');
	const branch = extract(ser, 'else if (c_oSer_SettingsType.DocVars === type)', rAt).slice('else '.length);
	const rdv = extract(ser, 'this.ReadDocVars = function', rAt);
	assert.ok(rdv, 'Binary_SettingsTableReader.ReadDocVars missing');
	const r = makeReader(bytes);
	const Settings = {};
	const oThis = { stream: r.stream, bcr: r.bcr };
	new Function('c_oSerDocVars', 'c_oSerConstants', rdv + ';').call(oThis, DV, { ReadOk, ReadUnknown });
	const body = 'var res = c_oSerConstants.ReadOk;\n' + branch + '\nreturn res;';
	const item = (type, length) => new Function('type', 'length', 'Settings', 'oThis', 'c_oSer_SettingsType', 'c_oSerConstants', body)
		.call(oThis, type, length, Settings, oThis, ST, { ReadOk, ReadUnknown });
	r.bcr.Read1(bytes.length, item);
	assert.strictEqual(r.stream.pos, bytes.length, 'reader did not consume the item');
	return Settings;
}

const VARS = [
	{ name: 'ClientName', value: 'Acme & Sons' },
	{ name: 'Contract<No>', value: 'K-42 "x"' },
	{ name: 'Ort', value: 'Köln – 日本' },
	{ name: 'Empty', value: '' },
];
const cases = [
	['A. a binary DocVars item (as core writes it) is read into Settings.DocVars', () => {
		const s = readSettings(writeSettings({ DocVars: VARS }));
		assert.deepStrictEqual(s.DocVars, VARS);
	}],
	['B. a save writes them back unchanged (bin -> editor -> bin)', () => {
		const first = writeSettings({ DocVars: VARS });
		const again = writeSettings(readSettings(first));
		assert.deepStrictEqual(again, first);
	}],
	['C. a document without variables writes no item', () => {
		assert.strictEqual(writeSettings({}).length, 0);
		assert.strictEqual(writeSettings({ DocVars: [] }).length, 0);
	}],
	['D. a variable without a name is not kept', () => {
		const s = readSettings(writeSettings({ DocVars: [{ name: '', value: 'x' }, { name: 'A', value: '1' }] }));
		assert.deepStrictEqual(s.DocVars, [{ name: 'A', value: '1' }]);
	}],
	['E. DocumentSettings declares DocVars', () => {
		assert.ok(/this\.DocVars\s*=\s*undefined/.test(extract(settingsJs, 'function DocumentSettings(') || ''), 'DocumentSettings has no DocVars field');
	}],
];

let failed = 0;
for (const [name, fn] of cases) {
	try { fn(); console.log('PASS ' + name); }
	catch (e) { failed++; console.log('FAIL ' + name + ': ' + e.message); }
}
console.log(failed ? `${failed} of ${cases.length} FAILED${BASELINE ? ' (baseline ' + BASE_REF + ')' : ''}` : `all ${cases.length} passed`);
process.exit(failed ? 1 : 0);
