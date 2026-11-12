/*
 * #2225 - "Add IBM watsonx and Groq as providers in AI agent ui".
 *
 * The AI agent's provider list (providers/registry.ts) had no Groq entry, so a
 * Groq key could only be used through "OpenAI compatible" with the URL typed
 * by hand and Groq's whole /models list (speech, guard and other models the
 * agent cannot use) offered. Upstream closed the issue as fixed citing
 * desktop-sdk 5dac6001 ("Fixed Bug 79842"), which is an RTL layout change in
 * the plugin; neither v9.4.0.120 nor v10.0.0.176 has a Groq or watsonx
 * provider.
 *
 * Now there is a "Groq" provider (providers/groq): an OpenAIProvider with
 * Groq's OpenAI-compatible URL https://api.groq.com/openai/v1, whose model
 * list is cut to the chat models that take tools (like xai/deepseek), with
 * reasoning (reasoning_effort) only for openai/gpt-oss-*. It is registered in
 * providerRegistry, so the Add provider dialog lists it.
 *
 * This loads the REAL groqInfo (providers/groq/info.ts) and the REAL
 * getProviderModels method of providers/groq/index.ts (brace-matched, types
 * stripped with node's module.stripTypeScriptTypes) and runs the method with a
 * stub client whose models.list() returns a Groq-like answer. It also checks
 * the registry/type entries and that the checked-in bundle
 * deploy/{9DC93CDB-...}/index.js carries the new URL, i.e. deploy/ was
 * rebuilt from src.
 *
 * Claimed: Groq is a registered provider type with the right URL; its model
 * list keeps only the allowlisted chat models, with display names, reasoning
 * on gpt-oss only, and an empty list when the request fails.
 * NOT claimed: a request to the real Groq API (needs a key; CORS of
 * api.groq.com from the plugin page not checked here), the React dialog (GUI
 * check). IBM watsonx is NOT added: its API needs an IAM token exchange and a
 * project id, not an OpenAI-style key (see the report).
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
// Pinned to the parent of the commit that added the provider, never HEAD.
const BASE_REF = process.env.BASE_REF || '46ddc076^';
const PLUGIN = 'ChromiumBasedEditors/plugins/ai-agent/';

function read(rel) {
	try {
		return process.env.BASELINE
			? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['ignore', 'pipe', 'ignore'] })
			: fs.readFileSync(path.join(REPO, rel), 'utf8');
	} catch (e) {
		return null;
	}
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

// values made in the vm context have its Array/Object prototypes
const plain = (v) => JSON.parse(JSON.stringify(v));

let failed = 0;
function check(name, fn) {
	try { fn(); console.log(`ok   - ${name}`); } catch (e) { failed++; console.log(`FAIL - ${name}: ${e.message}`); }
}
async function checkAsync(name, fn) {
	try { await fn(); console.log(`ok   - ${name}`); } catch (e) { failed++; console.log(`FAIL - ${name}: ${e.message}`); }
}

(async () => {
	const registry = read(PLUGIN + 'src/providers/registry.ts') || '';
	const types = read(PLUGIN + 'src/lib/types.ts') || '';
	const infoSrc = read(PLUGIN + 'src/providers/groq/info.ts');
	const indexSrc = read(PLUGIN + 'src/providers/groq/index.ts');

	check('"groq" is a provider type and is in providerRegistry', () => {
		assert.ok(/\|\s*"groq"/.test(types), 'ProviderType has no "groq"');
		assert.ok(/^\s*groq:\s*groqProvider,/m.test(registry), 'providerRegistry has no groq entry');
	});

	let getProviderModels = null;
	const ctx = { Promise, listAnswer: null };
	check('providers/groq has groqInfo and GroqProvider.getProviderModels', () => {
		assert.ok(infoSrc, 'providers/groq/info.ts missing');
		assert.ok(indexSrc, 'providers/groq/index.ts missing');
		const info = block(infoSrc, 'export const groqInfo = ');
		// isReasoningModel is a one-line arrow without braces: take up to its `;`
		const isReasoningLine = indexSrc.slice(indexSrc.indexOf('const isReasoningModel = ('),
			indexSrc.indexOf(';', indexSrc.indexOf('const isReasoningModel = (')) + 1);
		const method = block(indexSrc, 'getProviderModels = async (');
		assert.ok(info && method && isReasoningLine, 'pieces not found');
		vm.createContext(ctx);
		vm.runInContext(Module.stripTypeScriptTypes(info.replace(/^export const /, 'var ') + ';'), ctx);
		vm.runInContext(Module.stripTypeScriptTypes(isReasoningLine.replace(/^const /, 'var ')), ctx);
		// `this.createClient(key, url)` -> a stub OpenAI client
		ctx.self = {
			createClient: (key, url) => {
				ctx.lastClient = { key, url };
				return { models: { list: async () => { if (ctx.listAnswer instanceof Error) throw ctx.listAnswer; return { data: ctx.listAnswer }; } } };
			},
		};
		// the class field as it is in GroqProvider, so `this` is the instance
		getProviderModels = vm.runInContext(
			`new (class { constructor() { this.createClient = self.createClient; } ${Module.stripTypeScriptTypes(method)}; })().getProviderModels`, ctx);
	});

	check('the provider is named Groq and uses its OpenAI-compatible URL', () => {
		assert.ok(ctx.groqInfo, 'no groqInfo');
		assert.strictEqual(ctx.groqInfo.name, 'Groq');
		assert.strictEqual(ctx.groqInfo.baseUrl, 'https://api.groq.com/openai/v1');
	});

	await checkAsync('only the chat models with tools are offered, with names; reasoning on gpt-oss only', async () => {
		assert.ok(getProviderModels, 'no getProviderModels');
		ctx.listAnswer = [
			{ id: 'whisper-large-v3' }, { id: 'openai/gpt-oss-120b' }, { id: 'meta-llama/llama-guard-4-12b' },
			{ id: 'llama-3.3-70b-versatile' }, { id: 'playai-tts' },
		];
		const models = await getProviderModels({ apiKey: 'gsk_x', url: '' });
		assert.deepStrictEqual(plain(models), [
			{ id: 'openai/gpt-oss-120b', name: 'GPT-OSS 120B', provider: 'groq', reasoning: true },
			{ id: 'llama-3.3-70b-versatile', name: 'Llama 3.3 70B', provider: 'groq', reasoning: false },
		]);
		assert.deepStrictEqual(plain(ctx.lastClient), { key: 'gsk_x', url: 'https://api.groq.com/openai/v1' });
	});

	await checkAsync('a URL given with the provider is used; a failed request gives no models', async () => {
		assert.ok(getProviderModels, 'no getProviderModels');
		ctx.listAnswer = new Error('401');
		const models = await getProviderModels({ apiKey: 'bad', url: 'http://127.0.0.1:9/v1' });
		assert.deepStrictEqual(plain(models), []);
		assert.strictEqual(ctx.lastClient.url, 'http://127.0.0.1:9/v1');
	});

	check('the checked-in deploy bundle was rebuilt with the Groq provider', () => {
		const bundle = read(PLUGIN + 'deploy/{9DC93CDB-B576-4F0C-B55E-FCC9C48DD777}/index.js') || '';
		assert.ok(bundle.includes('api.groq.com/openai/v1'), 'deploy/index.js has no Groq URL');
	});

	console.log(failed ? `${failed} check(s) failed` : 'all checks passed');
	process.exit(failed ? 1 : 0);
})().catch((e) => { console.log(`FAIL - ${e.message}`); process.exit(1); });
