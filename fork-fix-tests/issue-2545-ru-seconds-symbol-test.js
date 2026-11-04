/*
 * Found while triaging #2545 ("TEXT returns invalid value", Russian format codes).
 * The reported 10.0 regression is not in our tree (see UPSTREAM_TRIAGE.md), but
 * running the same formulas turned up an older defect in the same table:
 *
 *     TEXT(A1;"ЧЧ:ММ:СС")  ->  "12:53:С С"      (lowercase "чч:мм:сс" works)
 *
 * ParseLocalFormatSymbol (common/NumFormat.js) maps each format letter to the
 * locale's own letter. In the ru block every entry is Cyrillic except one:
 * LocaleFormatSymbol['S'] = 'C' is the LATIN capital C (0x43), not the Cyrillic
 * Es (U+0421) that 's' = 'с' uses. The format parser compares characters against
 * LocaleFormatSymbol['S'] (Second = ... in NumFormat.prototype), so an uppercase
 * Cyrillic "СС" never matches and is written out as literal text.
 *
 * This extracts the real ParseLocalFormatSymbol by brace matching, runs it for
 * ru-RU and checks that every date/time letter of that locale is Cyrillic, and
 * that the parser still reads seconds from LocaleFormatSymbol['S'].
 * Not claimed here: the whole TEXT() path; that was checked separately with x2t
 * and LCID 1049.
 *
 * BASELINE=1 re-reads common/NumFormat.js from git and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const REL = 'common/NumFormat.js';
// Pinned to the parent of the commit that landed the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '7557345509^';

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
const at = source.indexOf('function ParseLocalFormatSymbol(Name)');
assert.notStrictEqual(at, -1, 'ParseLocalFormatSymbol not found - the extractor needs updating');
assert.ok(/Second\s*=\s*LocaleFormatSymbol\['S'\]/.test(source), 'the parser no longer reads seconds from LocaleFormatSymbol[\'S\']');

const LocaleFormatSymbol = {};
// eslint-disable-next-line no-new-func
new Function('LocaleFormatSymbol', matched(source, at) + '\nParseLocalFormatSymbol("ru-RU");')(LocaleFormatSymbol);

const hex = (s) => [...s].map((c) => 'U+' + c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')).join(' ');
let failures = 0;
for (const key of ['Y', 'y', 'M', 'm', 'D', 'd', 'H', 'h', 'Minute', 'minute', 'S', 's']) {
	const v = LocaleFormatSymbol[key];
	const ok = typeof v === 'string' && /^[Ѐ-ӿ]$/.test(v);
	console.log(`  ${ok ? 'ok  ' : 'FAIL'}  ru-RU ${key.padEnd(6)} -> ${v} (${hex(String(v))})`);
	if (!ok) failures++;
}
if (process.env.BASELINE) console.log(`BASELINE (${BASE_REF}): the 'S' entry must FAIL`);
console.log(failures ? `FAIL #2545: ${failures} ru format letter(s) are not Cyrillic`
	: 'PASS #2545: every ru date/time format letter is Cyrillic');
process.exit(failures ? 1 : 0);
