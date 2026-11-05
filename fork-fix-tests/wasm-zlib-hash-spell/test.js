/*
 * sdkjs hash and spell engines: rebuilt from our own sources, same answers.
 *
 * Not a bug fix, so there is no failing BASELINE: the point is the opposite.
 * sdkjs/common/hash/hash/engine{.js,.wasm,_ie.js} (2021-11) and
 * sdkjs/common/spell/spell/spell{.js,.wasm,_ie.js} (2021-05) were upstream
 * binaries nothing in our tree could rebuild - upstream deleted both recipes
 * from core in 2da2866862 "Refactoring". Core now carries them again
 * (DesktopEditor/xmlsec/src/wasm/hash, Common/3dParty/hunspell/hunspell.json,
 * built with Common/js/make.py and emscripten 3.1.48), and the artefacts were
 * replaced by that build. This test pins what the editor gets from either
 * build, so it must PASS on the new artefacts AND on the old ones
 * (BASELINE=1 runs it against $BASE_REF, the upstream binaries).
 *
 * Both engines run in a Web Worker in the editor (common/hash/hash.js,
 * common/spell/spell.js -> new Worker(src)). Each REAL checked-in glue file is
 * run here in a vm context shaped like a worker global scope, and driven with
 * the same messages the editor posts:
 *   hash   { type:"hash", value:[{password, salt, spinCount, alg}] }
 *          -> { hashValue:[base64] }   (AscCommon.calculateProtectHash; the
 *          sheet/workbook/document protection password check)
 *   spell  { type:"init", dictionaries_path, languages } then
 *          { type:"spell"|"suggest", usrWords, usrLang }
 *          -> usrCorrect[] / usrSuggest[][]
 * WebAssembly.instantiateStreaming is withheld: in the desktop app the engines
 * are loaded from file://, where emscripten falls back to
 * instantiateArrayBuffer -> getBinaryPromise, the hook the recipes' after-step
 * splices (getBinaryPromise2). The test asserts the .wasm was actually fetched
 * through that path, so a wasm variant can't silently pass by being the wrong
 * file. The _ie.js (asm.js) variants are what the editor falls back to when
 * the wasm one fails, and get the same vectors.
 *
 * Vectors:
 *   hash  every algorithm sdkjs can ask for (common/editorscommon.js maps
 *         algorithmName -> AscCommon.HashAlgs: MD2 MD4 MD5 RIPEMD160 SHA1
 *         SHA256 SHA384 SHA512 WHIRLPOOL). Office password hash = H(salt ||
 *         UTF-16LE(password)), then spinCount x H(h || uint32le(i)).
 *         MD5/RIPEMD160/SHA* are checked against Node's crypto (independent
 *         implementation), including SHA-512 with spinCount 100000 - the
 *         default for docx/xlsx protection. MD2/MD4/WHIRLPOOL, which Node does
 *         not have, are checked on their RFC 1319 / RFC 1320 / ISO test
 *         vectors for "abc" (fed through the base64 salt with an empty
 *         password and no spin), plus a spin-1000 value each recorded from the
 *         upstream 2021 binary (MD4/WHIRLPOOL re-derived with OpenSSL's legacy
 *         provider; MD2 is a regression value only).
 *   spell en_US, de_DE, ru_RU from the dictionaries submodule: correct/incorrect
 *         per word and the exact suggestion lists, recorded from the upstream
 *         2021 binary.
 *
 *   RD_REPO=<sdkjs checkout>   default ../../sdkjs relative to this file
 *   RD_DICT=<dictionaries>     default ../../dictionaries
 *   BASELINE=1                 read the artefacts via `git show $BASE_REF:<path>`
 *                              (default: the commit before the rebuild); passes too
 *
 * NOT claimed: the zlib engine (common/zlib/engine) is not covered - it was not
 * rebuilt (its recipe, OfficeUtils/js/zlib_image.json, no longer links against
 * current core) and the editors never load it (AscCommon.zlib_load is commented
 * out in common/apiBase.js; AscCommon.ZLib comes from the font engine). The
 * desktop app's own worker loader is not exercised (no GUI here). Hunspell's
 * suggestion search is time-limited (TIMELIMIT_* in atypes.hxx), so on a very
 * slow machine the asm.js variant could legitimately return fewer suggestions;
 * the words below were picked because they finish far inside that limit.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', '..', 'sdkjs');
const DICT = process.env.RD_DICT || path.resolve(__dirname, '..', '..', 'dictionaries');
const BASE_REF = process.env.BASE_REF || '58ebfaf7aa^';
const BASELINE = !!process.env.BASELINE;

function read(rel) {
	if (BASELINE)
		return execFileSync('git', ['-C', SDKJS, 'show', BASE_REF + ':' + rel], { maxBuffer: 1 << 26 });
	return fs.readFileSync(path.join(SDKJS, rel));
}

// Run a worker script; relative fetches resolve inside the artefact's directory
// in the repo (or BASE_REF), dictionary XHRs resolve on disk.
function startWorker(rel) {
	const dir = path.posix.dirname(rel);
	const posted = [], fetched = [];
	const ctx = {
		console: { log() {}, warn() {}, error() {}, info() {} },
		TextDecoder, TextEncoder, setTimeout, clearTimeout, performance,
		navigator: { userAgent: 'node', languages: ['en-US'] },
		location: { href: 'http://rd.local/' + rel, protocol: 'http:' },
		postMessage: (m) => posted.push(m),
		importScripts() { throw new Error('importScripts not expected'); },
		WebAssembly: {
			Module: WebAssembly.Module, Instance: WebAssembly.Instance, Memory: WebAssembly.Memory,
			Table: WebAssembly.Table, Global: WebAssembly.Global, RuntimeError: WebAssembly.RuntimeError,
			CompileError: WebAssembly.CompileError, LinkError: WebAssembly.LinkError,
			instantiate: WebAssembly.instantiate, compile: WebAssembly.compile, validate: WebAssembly.validate,
		},
	};
	ctx.self = ctx;
	const strip = (u) => String(u).replace(/^http:\/\/rd\.local\//, '');
	ctx.fetch = (u) => {
		const name = strip(u);
		fetched.push(path.posix.basename(name));
		let data;
		try { data = read(name.startsWith(dir + '/') ? name : dir + '/' + name); } catch (e) { data = null; }
		const ab = data && data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
		return Promise.resolve({ ok: !!data, status: data ? 200 : 404, arrayBuffer: () => Promise.resolve(ab) });
	};
	ctx.XMLHttpRequest = function () {
		const x = this;
		x.open = (m, u) => { x.url = u; };
		x.overrideMimeType = x.setRequestHeader = () => {};
		// the old asm.js spell build also fetches its spell.js.mem this way
		const get = (u, cb) => (/^http:\/\/rd\.local\//.test(u)
			? setImmediate(() => { try { cb(null, read(strip(u))); } catch (e) { cb(e); } })
			: fs.readFile(u, cb));
		x.send = () => get(String(x.url), (err, d) => {
			x.status = err ? 404 : 200;
			x.response = err ? null : d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength);
			x.onload && x.onload.call(x);
		});
	};
	vm.createContext(ctx);
	vm.runInContext(read(rel).toString('utf8'), ctx, { filename: rel });
	return {
		posted, fetched,
		send: (data) => ctx.onmessage({ data }),
		wait: (pred, what) => new Promise((resolve, reject) => {
			const t0 = Date.now();
			(function tick() {
				const v = posted.find(pred);
				if (v) return resolve(v);
				if (Date.now() - t0 > 120000) return reject(new Error(rel + ': no answer for ' + what));
				setTimeout(tick, 5);
			})();
		}),
	};
}

// ---- hash ----
const ALGS = ['MD2', 'MD4', 'MD5', 'RMD160', 'SHA1', 'SHA256', 'SHA384', 'SHA512', 'WHIRLPOOL'];
const NODE_ALG = { MD5: 'md5', RMD160: 'ripemd160', SHA1: 'sha1', SHA256: 'sha256', SHA384: 'sha384', SHA512: 'sha512' };
const RAW_ABC = {
	MD2: 'da853b0d3f88d99b30283a69e6ded6bb',
	MD4: 'a448017aaf21d8525fc10ae87aa6729d',
	WHIRLPOOL: '4e2448a4c6f486bb16b6562c73b4020bf3043e3a731bce721ae1b303d97e6d4c' +
		'7181eebdb6c57e277d0e34957114cbd6c797fc9d95d8b582d225292076d4eef5',
};
// password "oleg", SALT, spinCount 1000. Recorded from the upstream 2021 engine.wasm;
// MD4 and WHIRLPOOL were recomputed independently with OpenSSL 3.6 (legacy provider)
// and agree. MD2 has no other implementation to hand: regression value only.
const RECORDED = {
	MD2: 'hRDA5FsZ88e6G6XCrOsNJw==',
	MD4: 'A1d1DLiad7IsZK3vEQLxyw==',
	WHIRLPOOL: 'X7tbDDH3TQE+dju2Y65i+fL4DERg1Y2hMH2uxLg9VlpXMkIwDD1WXAptRNoPFIG1NwhcPSHialHSheu90MD0Qg==',
};
const SALT = 'yrGivlyCImiWnryRee1OJw==';
const HASH_CASES = [];
for (const a of ALGS) {
	const alg = ALGS.indexOf(a);
	HASH_CASES.push({ a, kind: 'raw "abc"', c: { password: '', salt: Buffer.from('abc').toString('base64'), spinCount: 0, alg } });
	for (const pw of ['Pa$$w0rd!', 'пароль', 'Passwort-ÄÖÜß', '密码🔒'])
		HASH_CASES.push({ a, kind: 'office spin 7 ' + JSON.stringify(pw), c: { password: pw, salt: SALT, spinCount: 7, alg } });
	HASH_CASES.push({ a, kind: 'office spin 1000', c: { password: 'oleg', salt: SALT, spinCount: 1000, alg } });
}
HASH_CASES.push({ a: 'SHA512', kind: 'office spin 100000', c: { password: 'oleg', salt: SALT, spinCount: 100000, alg: 7 } });

function officeHash(name, c) {
	let h = crypto.createHash(name).update(Buffer.concat([Buffer.from(c.salt, 'base64'), Buffer.from(c.password, 'utf16le')])).digest();
	for (let i = 0; i < c.spinCount; i++) {
		const it = Buffer.alloc(4); it.writeUInt32LE(i);
		h = crypto.createHash(name).update(Buffer.concat([h, it])).digest();
	}
	return h.toString('base64');
}
function expectedHash(t) {
	if (NODE_ALG[t.a]) return officeHash(NODE_ALG[t.a], t.c);
	if (t.kind === 'raw "abc"') return Buffer.from(RAW_ABC[t.a], 'hex').toString('base64');
	if (t.kind === 'office spin 1000') return RECORDED[t.a];
	return null; // MD2/MD4/WHIRLPOOL with unicode passwords: only cross-checked between variants
}

// ---- spell ----
const LANGS = { 1033: 'en_US', 1031: 'de_DE', 1049: 'ru_RU' };
const SPELL = {
	en_US: [
		["color", true],
		["running", true],
		["international", true],
		["hello", true],
		["speling", false, ["spieling", "spelling", "spewing", "peeling", "splinting"]],
		["recieve", false, ["receive", "relieve", "reverie"]],
		["teh", false, ["the", "eh", "tech", "tee", "tea", "ten", "tel", "ted", "meh", "t eh"]],
		["wrod", false, ["word", "rod", "trod", "wood", "prod", "w rod"]],
		["beleive", false, ["believe", "bevel"]],
		["occurence", false, ["occurrence", "nonoccurence", "concurrence", "recurrence", "renounce"]],
		["accomodate", false, ["accommodate", "accommodation"]],
		["definately", false, ["definitely", "effeminately", "definitively", "indefinably"]],
	],
	de_DE: [
		["Haus", true],
		["Straße", true],
		["schön", true],
		["Rechtschreibung", true],
		["Fahrrad", true],
		["Hauss", false, ["Haus", "Hass", "Hausse", "Hauses", "Heuss", "Haus-", "Hause", "Haust"]],
		["schoen", false, ["schön", "schone", "schien", "schon", "schonen", "schoren", "schoben"]],
		["Fahrad", false, ["Farad", "Fahrrad", "Fahr ad", "Fahr-ad"]],
		["Entschuldigun", false, ["Entschuldigung", "Entschuldigen", "Entschuldigt", "Entschuldige", "Entschulden"]],
		["Strase", false, ["Strapse", "Strass", "Strafe", "Straße", "Trasse", "Esterase"]],
		["Rechtschreibunk", false, ["Rechtschreibung", "Rechtschreibunke", "Rechtschreibpunk", "Rechtschreibfunk", "Rechtschreiben", "Rechtschreiblich", "Rechtschreiber"]],
	],
	ru_RU: [
		["привет", true],
		["молоко", true],
		["проверка", true],
		["собака", true],
		["превет", false, ["преет", "ревет", "поревет", "прервет", "привет", "перевеет", "прете", "прет"]],
		["малако", false, ["макало", "малакон", "мала ко", "маклак"]],
		["праверка", false, ["проверка", "переправка", "правка", "вправе"]],
		["сабака", false, ["абака", "слабака", "собака", "табака", "салака", "кабака", "с абака", "кабак", "бакса", "сака"]],
		["карова", false, ["крова", "корова", "какова", "Сарова", "пароварка", "проварка", "ковар", "товарка"]],
		["исскуство", false, ["искусство", "искусств"]],
	],
};

let failed = 0;
const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); failed += !ok; };

async function testHash(rel) {
	const w = startWorker(rel);
	w.send({ type: 'hash', value: HASH_CASES.map((t) => t.c) });
	const got = (await w.wait((m) => m && m.hashValue, 'hash')).hashValue;
	if (!rel.endsWith('_ie.js'))
		check(w.fetched.includes('engine.wasm'), rel + ': engine.wasm loaded through getBinaryPromise (' + w.fetched.join(',') + ')');
	let ok = 0, bad = 0, only = 0;
	HASH_CASES.forEach((t, i) => {
		const e = expectedHash(t);
		if (e === null) { only++; return; }
		if (got[i] === e) ok++;
		else { bad++; console.log('     ' + t.a + ' ' + t.kind + ': got ' + got[i] + ' want ' + e); }
	});
	check(bad === 0, rel + ': ' + ok + '/' + (ok + bad) + ' hash vectors match (' + ALGS.length + ' algorithms, SHA-512 spin 100000 included)');
	return got;
}

async function testSpell(rel) {
	const w = startWorker(rel);
	w.send({ type: 'init', dictionaries_path: DICT, languages: LANGS });
	for (const [id, lang] of Object.entries(LANGS)) {
		const v = SPELL[lang];
		const words = v.map((x) => x[0]);
		w.send({ type: 'spell', usrWords: words, usrLang: words.map(() => +id) });
		const sp = await w.wait((m) => m.type === 'spell' && m.usrLang[0] === +id, 'spell ' + lang);
		const badSpell = v.filter((x, i) => sp.usrCorrect[i] !== x[1]).map((x) => x[0]);
		check(badSpell.length === 0, rel + ' ' + lang + ': spell() right for ' + (v.length - badSpell.length) + '/' + v.length + ' words' + (badSpell.length ? ' - wrong: ' + badSpell.join(' ') : ''));
		const wrong = v.filter((x) => !x[1]);
		w.send({ type: 'suggest', usrWords: wrong.map((x) => x[0]), usrLang: wrong.map(() => +id) });
		const sg = await w.wait((m) => m.type === 'suggest' && m.usrLang[0] === +id, 'suggest ' + lang);
		const badSug = wrong.filter((x, i) => JSON.stringify(sg.usrSuggest[i]) !== JSON.stringify(x[2]));
		badSug.forEach((x) => console.log('     ' + x[0] + ': got ' + JSON.stringify(sg.usrSuggest[wrong.indexOf(x)]) + ' want ' + JSON.stringify(x[2])));
		check(badSug.length === 0, rel + ' ' + lang + ': suggestions identical for ' + (wrong.length - badSug.length) + '/' + wrong.length + ' misspellings (e.g. ' + wrong[0][0] + ' -> ' + wrong[0][2].slice(0, 3).join(', ') + ')');
	}
	if (!rel.endsWith('_ie.js'))
		check(w.fetched.includes('spell.wasm'), rel + ': spell.wasm loaded through getBinaryPromise (' + w.fetched.join(',') + ')');
}

(async () => {
	console.log(BASELINE ? 'BASELINE ' + BASE_REF : 'repo ' + SDKJS);
	const h1 = await testHash('common/hash/hash/engine.js');
	const h2 = await testHash('common/hash/hash/engine_ie.js');
	check(JSON.stringify(h1) === JSON.stringify(h2), 'engine.wasm and engine_ie.js agree on all ' + h1.length + ' cases');
	await testSpell('common/spell/spell/spell.js');
	await testSpell('common/spell/spell/spell_ie.js');
	console.log(failed ? 'FAILED (' + failed + ')' : 'PASSED');
	process.exit(failed ? 1 : 0);
})().catch((e) => { console.log('FAIL ' + e.message); process.exit(1); });
