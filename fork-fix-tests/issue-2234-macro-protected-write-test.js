/*
 * #2234 - "Since version 9.2, spreadsheet macros are no longer executed... There is
 * no error message; they are simply not executed."
 *
 * The reporter narrowed it themselves: it happens when the target cell of the macro
 * is locked for modification. ApiRange.SetValue refuses to write through sheet
 * protection - which is right, Excel will not let VBA do it either - but it refused
 * in silence: it returned false with the throwException commented out, and a macro
 * rarely inspects a return value.
 *
 * Twenty-five other places in apiBuilder.js hit the same condition and throw. This
 * was the one that did not, in the method a macro is most likely to call.
 *
 * This extracts the real ApiRange.SetValue by brace matching and drives its guard
 * with stubs.
 *
 * BASELINE=1 runs against HEAD, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/apiBuilder.js';
// Pinned to the parent of the commit that landed this fix. It must NOT default to
// HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
// and the test passes forever while testing nothing.
const BASE_REF = process.env.BASE_REF || '96b4de581f^';

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

const at = source.indexOf('ApiRange.prototype.SetValue = function (data)');
assert.notStrictEqual(at, -1, 'ApiRange.SetValue not found');
const fnSrc = matched(source, source.indexOf('(', at + 'ApiRange.prototype.SetValue = function'.length - 8));
assert.ok(fnSrc.includes('isIntersectLockedRanges'), 'extracted the wrong function');

/* --- stubs: only what runs before the guard --- */
let thrown = null;
function throwException(err) { thrown = err; throw err; }

function makeRange(protectedSheet, locked) {
	return {
		range: {
			bbox: { r1: 0, c1: 0, r2: 0, c2: 0 },
			worksheet: {
				getSheetProtection: () => protectedSheet,
				isIntersectLockedRanges: () => locked,
			},
			// reached only when the guard lets the write through
			setValue: function () { this._wrote = true; return true; },
		},
	};
}

const SetValue = new Function('throwException', 'Asc', 'AscCommonExcel',
	'"use strict"; return function' + fnSrc)(throwException, {}, {});

/* --- the defect: a locked cell on a protected sheet --- */
{
	thrown = null;
	const api = makeRange(true, true);
	assert.throws(
		() => SetValue.call(api, '123'),
		/Cannot modify protected sheet/,
		'writing to a locked cell must report why it did nothing - returning false in ' +
		'silence is #2234, the macro just appears not to run'
	);
	assert.ok(thrown instanceof Error, 'it must be a real Error, as the other 25 sites raise');
}

/* --- an unprotected sheet must be unaffected: the guard must not fire --- */
{
	thrown = null;
	const api = makeRange(false, false);
	let sawGuard = false;
	try { SetValue.call(api, '123'); } catch (e) {
		if (/Cannot modify protected sheet/.test(e.message)) sawGuard = true;
	}
	assert.ok(!sawGuard, 'an unprotected sheet must not be refused');
	assert.strictEqual(thrown, null, 'and nothing may be thrown for it');
}

/* --- protected sheet, but the target is not locked: also allowed --- */
{
	thrown = null;
	const api = makeRange(true, false);
	let sawGuard = false;
	try { SetValue.call(api, '123'); } catch (e) {
		if (/Cannot modify protected sheet/.test(e.message)) sawGuard = true;
	}
	assert.ok(!sawGuard, 'an unlocked cell on a protected sheet must still be writable');
}

/* --- no commented-out protection error may be left anywhere in the file --- */
const commented = (source.match(/\/\/\s*throwException\(new Error\('Cannot modify protected sheet'\)\)/g) || []).length;
assert.strictEqual(commented, 0,
	`${commented} protection error(s) are still commented out - they fail silently`);

console.log('ok - a refused macro write says why; unprotected and unlocked writes are untouched');
