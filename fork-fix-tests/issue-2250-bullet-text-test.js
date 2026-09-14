/*
 * #2250 - copying a bulleted list out of the editor pastes an unreadable
 * character instead of a bullet.
 *
 * A bullet is not a bullet character, it is a byte in a symbol font. Our default
 * is 0x00B7 in Symbol (word/Editor/Numbering/NumberingLvl.js), and a document
 * written by Word stores the same thing shifted into the private use area as
 * 0xF0B7. The glyph means "bullet" only while the font travels with it.
 *
 * The HTML clipboard flavour is fine - common/wordcopypaste.js emits a real
 * <li style="list-style-type: disc"> and the receiving application draws its own
 * bullet. The text/plain flavour, built by GetSelectedText from
 * Paragraph.GetNumberingTextWithSuffix, has nowhere to put a font and handed over
 * the raw codepoint.
 *
 * This extracts the real MapSymbolFontTextToUnicode out of Paragraph.js by brace
 * matching and checks both spellings of each glyph.
 *
 * BASELINE=1 runs against HEAD, where the function does not exist at all - which
 * is itself the failure.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'word/Editor/Paragraph.js';
const BASE_REF = process.env.BASE_REF || 'HEAD';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const tableAt = source.indexOf('const SYMBOL_BULLET_TO_UNICODE');
const fnAt = source.indexOf('function MapSymbolFontTextToUnicode(text, fontName)');
assert.notStrictEqual(tableAt, -1,
	'SYMBOL_BULLET_TO_UNICODE not found - the plain-text flavour still hands over the raw symbol-font codepoint (#2250)');
assert.notStrictEqual(fnAt, -1, 'MapSymbolFontTextToUnicode not found');

const tableSrc = source.slice(tableAt, source.indexOf('};', tableAt) + 2);
const fnSrc = source.slice(fnAt, fnAt + matched(source, source.indexOf('{', fnAt)).length +
	(source.indexOf('{', fnAt) - fnAt));

const map = new Function(tableSrc + '\n' + fnSrc + '\nreturn MapSymbolFontTextToUnicode;')();

const BULLET = String.fromCharCode(0x2022);
const SQUARE = String.fromCharCode(0x25AA);
const CHECK  = String.fromCharCode(0x2714);
const ARROW  = String.fromCharCode(0x27A2);

/* Our own default: 0x00B7 in Symbol. */
assert.strictEqual(map(String.fromCharCode(0x00B7), 'Symbol'), BULLET,
	'the default Symbol bullet must become a real bullet in plain text');

/* The same glyph as Word stores it, offset into the private use area. */
assert.strictEqual(map(String.fromCharCode(0xF0B7), 'Symbol'), BULLET,
	'the private-use spelling of the same glyph must map identically');

/* Wingdings bullets, both spellings. */
assert.strictEqual(map(String.fromCharCode(0x00A7), 'Wingdings'), SQUARE);
assert.strictEqual(map(String.fromCharCode(0xF0A7), 'Wingdings'), SQUARE);
assert.strictEqual(map(String.fromCharCode(0x00FC), 'Wingdings'), CHECK);
assert.strictEqual(map(String.fromCharCode(0x00D8), 'Wingdings'), ARROW);

/* A font we do not have a table for must be left alone, not guessed at. */
assert.strictEqual(map(String.fromCharCode(0x00B7), 'Courier New'), String.fromCharCode(0x00B7),
	'an unknown font must pass through untouched');
assert.strictEqual(map('o', 'Courier New'), 'o',
	'the "circle" bullet is a real letter o and must stay one');

/* Ordinary numbering must survive verbatim. */
assert.strictEqual(map('1.', 'Symbol'), '1.', 'a numbered list must not be rewritten');
assert.strictEqual(map('iii.', 'Times New Roman'), 'iii.');

/* A character in a symbol font that we have no mapping for must pass through
 * rather than be dropped or replaced by something invented. */
const unmapped = String.fromCharCode(0xF0AB);
assert.strictEqual(map(unmapped, 'Symbol'), unmapped,
	'an unmapped symbol-font character must be left as it was');

/* Multi-character numbering text, mixed. */
assert.strictEqual(map(String.fromCharCode(0x00B7) + String.fromCharCode(0x00B7), 'Symbol'),
	BULLET + BULLET);

/* No font at all must not throw. */
assert.strictEqual(map('x', undefined), 'x');
assert.strictEqual(map('x', null), 'x');

console.log('ok - symbol-font bullets become real characters in the plain-text flavour');
