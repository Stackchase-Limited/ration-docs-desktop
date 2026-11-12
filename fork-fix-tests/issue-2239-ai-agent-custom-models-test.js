/*
 * #2239 - "When adding an AI provider to the AI agent, be able to enter the
 * model name manually".
 *
 * The AI agent offered only the models a provider's /models answer lists, cut
 * down for most providers to a fixed allowlist (e.g. providers/openrouter/
 * info.ts modelFilters). A model outside it could not be chosen at all.
 *
 * Now the Add/Edit provider dialogs have an optional "Models" field; the ids
 * typed there (lib/utils.ts parseCustomModels) are stored on the provider as
 * TProvider.customModels and Provider.getProvidersModels (providers/index.ts)
 * appends each id the provider did not list (mergeCustomModels), also when the
 * list could not be fetched. Empty field = the old behaviour.
 *
 * This loads the REAL parseCustomModels / mergeCustomModels (brace-matched out
 * of lib/utils.ts, types stripped with node's module.stripTypeScriptTypes) and
 * the REAL getProvidersModels method of providers/index.ts, and runs that
 * method against a stub provider registry. It also checks that the checked-in
 * bundle deploy/{9DC93CDB-...}/index.js carries the new field's string, i.e.
 * deploy/ was rebuilt from src.
 *
 * Claimed: typed ids are split/trimmed/deduplicated; a provider's list gets the
 * typed ids the provider did not list, after its own; with the fetch failing
 * the typed ids are still offered; without typed ids the list is unchanged.
 * NOT claimed: the React dialogs, localStorage persistence or a request with a
 * hand-entered model to a real provider (needs a GUI check); the in-tree vitest
 * tests (src/lib/tests/utils.test.ts, src/providers/tests/index.test.ts) cover
 * the same functions with the real module graph.
 *
 * RD_REPO=<desktop-sdk checkout> (default ../desktop-sdk). BASELINE=1 reads the
 * sources at BASE_REF with git show, where it must fail. Needs a node with
 * module.stripTypeScriptTypes (>= 22.13); with an older node it re-runs itself
 * under RD_NODE or a Homebrew node@22..25.
 */
'use strict';
const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const Module = require('module');

if (typeof Module.stripTypeScriptTypes !== 'function') {
	const candidates = [process.env.RD_NODE].concat(
		[25, 24, 23, 22].map((v) => `/opt/homebrew/opt/node@${v}/bin/node`), ['/opt/homebrew/bin/node']);
	const node = candidates.find((p) => p && fs.existsSync(p) && p !== process.execPath &&
		spawnSync(p, ['-e', 'process.exit(typeof require("module").stripTypeScriptTypes === "function" ? 0 : 1)']).status === 0);
	if (!node) {
		console.error('needs node >= 22.13 (module.stripTypeScriptTypes); set RD_NODE');
		process.exit(2);
	}
	process.exit(spawnSync(node, ['--no-warnings', __filename], { stdio: 'inherit' }).status);
}

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'desktop-sdk');
// Pinned to the parent of the commit that landed this feature, never HEAD.
const BASE_REF = process.env.BASE_REF || '42a94cd1^';
const PLUGIN = 'ChromiumBasedEditors/plugins/ai-agent/';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}

/* The balanced `{ ... }` block (with its header) that starts at `marker`, or null. */
function block(source, marker) {
	const at = source.indexOf(marker);
	if (at === -1) return null;
	let depth = 0;
	for (let i = source.indexOf('{', at + marker.length - 1); i < source.length; i++) {
		if (source[i] === '{') depth++;
		else if (source[i] === '}' && --depth === 0) return source.slice(at, i + 1);
	}
	throw new Error(`unbalanced block at ${marker}`);
}

/* An exported arrow function `export const name = (...) => { ... };` as plain JS. */
function arrow(source, name) {
	const b = block(source, `export const ${name} = (`);
	if (!b) return null;
	// `var`, so the function becomes a property of the vm context
	return Module.stripTypeScriptTypes(b.replace(/^export const /, 'var ') + ';');
}

// values made in the vm context have its Array/Object prototypes
const plain = (v) => JSON.parse(JSON.stringify(v));

let failed = 0;
function check(name, fn) {
	try { fn(); console.log(`ok   - ${name}`); } catch (e) { failed++; console.log(`FAIL - ${name}: ${e.message}`); }
}
async function checkAsync(name, fn) {
	try { await fn(); console.log(`ok   - ${name}`); } catch (e) { failed++; console.log(`FAIL - ${name}: ${e.message}`); }
}

const utils = read(PLUGIN + 'src/lib/utils.ts');
const parseSrc = arrow(utils, 'parseCustomModels');
const mergeSrc = arrow(utils, 'mergeCustomModels');

const indexSrc = read(PLUGIN + 'src/providers/index.ts');
// the class property `getProvidersModels = async (providers: TProvider[]) => { ... };`
const methodSrc = block(indexSrc, 'getProvidersModels = async (');

(async () => {
	check('lib/utils.ts has parseCustomModels and mergeCustomModels', () => {
		assert.ok(parseSrc, 'parseCustomModels not found');
		assert.ok(mergeSrc, 'mergeCustomModels not found');
	});
	assert.ok(methodSrc, 'getProvidersModels not found in providers/index.ts');

	const ctx = { Map, Promise };
	vm.createContext(ctx);
	if (parseSrc) vm.runInContext(parseSrc, ctx);
	if (mergeSrc) vm.runInContext(mergeSrc, ctx);

	// Stub registry: "ok" lists one model, "down" cannot be reached.
	const listed = [{ id: 'listed/model', name: 'Listed', provider: 'openrouter', reasoning: true }];
	ctx.providerRegistry = {
		openrouter: { getProviderModels: async (d) => { if (d.url === 'down') throw new Error('offline'); return listed; } },
	};
	ctx.getProvider = (type) => ctx.providerRegistry[type];
	const getProvidersModels = vm.runInContext(
		`(${Module.stripTypeScriptTypes(methodSrc.replace(/^getProvidersModels = /, ''))})`, ctx);

	check('typed model ids are split on commas/new lines, trimmed and deduplicated', () => {
		assert.deepStrictEqual(plain(ctx.parseCustomModels(' vendor/a , b\nvendor/a,, ')), ['vendor/a', 'b']);
		assert.deepStrictEqual(plain(ctx.parseCustomModels('')), []);
	});

	await checkAsync('a typed model the provider does not list is offered after the listed ones', async () => {
		const models = await getProvidersModels([
			{ type: 'openrouter', name: 'OR', key: 'k', baseUrl: 'ok', customModels: ['listed/model', 'vendor/new-model'] },
		]);
		assert.deepStrictEqual(plain(models.get('OR')), [
			listed[0],
			{ id: 'vendor/new-model', name: 'vendor/new-model', provider: 'openrouter', reasoning: false },
		]);
	});

	await checkAsync('typed models are offered when the list cannot be fetched', async () => {
		const models = await getProvidersModels([
			{ type: 'openrouter', name: 'OR', key: 'k', baseUrl: 'down', customModels: ['vendor/new-model'] },
		]);
		assert.deepStrictEqual(plain((models.get('OR') || []).map((m) => m.id)), ['vendor/new-model']);
	});

	await checkAsync('without typed models the list is what the provider returned (default unchanged)', async () => {
		const models = await getProvidersModels([{ type: 'openrouter', name: 'OR', key: 'k', baseUrl: 'ok' }]);
		assert.strictEqual(models.get('OR'), listed);
		const none = await getProvidersModels([{ type: 'openrouter', name: 'OR', key: 'k', baseUrl: 'down' }]);
		assert.strictEqual(none.has('OR'), false);
	});

	check('the checked-in deploy bundle was rebuilt with the Models field', () => {
		const bundle = read(PLUGIN + 'deploy/{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}/index.js');
		assert.ok(bundle.includes('EnterModels'), 'deploy/index.js has no "EnterModels" string');
	});

	console.log(failed ? `${failed} check(s) failed` : 'all checks passed');
	process.exit(failed ? 1 : 0);
})().catch((e) => { console.log(`FAIL - ${e.message}`); process.exit(1); });
