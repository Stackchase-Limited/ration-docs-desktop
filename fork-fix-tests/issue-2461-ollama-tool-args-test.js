/*
 * #2461 - "MCP tool arguments are lost when using local Ollama".
 *
 * With Ollama (the plugin's Ollama provider is the OpenAI provider pointed at
 * Ollama's /v1 endpoint) the model's tool call showed {"query":"Ariane 5",
 * "limit":3} in the chat, while the MCP server received "arguments": {}.
 *
 * Cause: Ollama's OpenAI endpoint (ollama openai/openai.go ToToolCalls,
 * middleware/openai.go) does not stream arguments in fragments the way OpenAI
 * does. It sends the whole call - id, index, name and the complete arguments
 * JSON string - in ONE delta, then a finish chunk with an empty delta.
 * src/providers/openai/handlers.ts createToolCallPart stored that text in
 * argsText (what the chat shows) but set args to {}; args were only parsed in
 * mergeToolCall, i.e. when a later delta continued the call, and with Ollama
 * none does. useMessages.handleToolCall passes toolCall.args to callTools, and
 * CustomServers sends it unchanged as params.arguments - so {}.
 * Also fixed in the same handler: a tool-call delta right after a call that
 * already has its result (the model calls another tool straight after the
 * first) was merged into that finished call - its arguments were appended to
 * the old argsText, args became {} and the new call never ran.
 *
 * Follow-up commit (two more silent drops):
 *  - OpenAIProvider.sendMessage (openai/index.ts; every OpenAI-derived provider
 *    uses it) checked finish_reason before reading the chunk's delta. Ollama
 *    builds before August 2026 send the tool call and finish_reason in ONE
 *    chunk, so the call was thrown away.
 *  - Parallel calls: handleToolCall read only delta.tool_calls[0], useMessages
 *    ran one call and continued, and each provider sent back only the LAST
 *    call's result. Now every entry is read (by id, else by index among the
 *    calls waiting for a result), useMessages runs every pending call first
 *    (lib/utils.ts getNextPendingToolCallIdx), and the providers send one
 *    result per unanswered call id (base.ts takeUnansweredToolCalls).
 *
 * This loads the REAL handlers.ts (types stripped with node's own
 * module.stripTypeScriptTypes; the file has only type imports) and feeds its
 * exported handleToolCall the chunk sequence Ollama sends, exactly as
 * OpenAIProvider.sendMessage does for chunks carrying tool_calls.
 *
 * For the follow-up it also runs, against stubs: the real per-chunk loop of
 * OpenAIProvider.sendMessage (the `for (const chunk of streamEvent.choices)`
 * statement, brace-matched out of openai/index.ts), the real
 * AbstractBaseProvider (base.ts, loaded whole) and the real
 * getNextPendingToolCallIdx (brace-matched out of lib/utils.ts).
 *
 * Claimed: the tool call that would be handed to callTools carries the parsed
 * arguments, for a string and for an object `arguments`; a second call after a
 * resolved one is a separate call; a call in the finish_reason chunk survives;
 * two calls at once (Ollama: one delta; OpenAI: fragments by index) become two
 * calls with their own arguments, both are run, and one result per call id is
 * picked to send - and none again on the next round.
 * NOT claimed: the HTTP/SSE layer, the React hook itself or the MCP transport;
 * the in-tree vitest tests src/providers/ollama/tests/toolArgs.test.ts and
 * src/providers/mistral/tests/toolHistory.test.ts run the real providers
 * against mock servers that check one tool message per call id.
 *
 * RD_REPO=<desktop-sdk checkout> (default ../desktop-sdk). BASELINE=1 reads the
 * sources at BASE_REF with git show, where it must fail. BASE_REF defaults to
 * the parent of the follow-up commit; the parent of the first #2461 commit
 * (BASE_REF=c865aace^) fails too. Needs a node with
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
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '073ae7ba^';
const SRC = 'ChromiumBasedEditors/plugins/ai-agent/src/';
const FILE = SRC + 'providers/openai/handlers.ts';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8' })
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

const text = read(FILE);

if (/^import (?!type )/m.test(text)) throw new Error('handlers.ts gained a value import; the loader cannot run it');
const js = Module.stripTypeScriptTypes(text).replace(/^export (const|type|\{)/gm, (m, k) => (k === 'const' ? 'const' : '//'));
const handlers = vm.runInNewContext(
	`${js}\n;({ handleToolCall, handleTextMessage, handleReasoningMessage, finalizeReasoningPart })`, { JSON, Date, Math });
const { handleToolCall } = handlers;
assert.strictEqual(typeof handleToolCall, 'function', 'handleToolCall not found');

// The chunk choices Ollama streams for one tool call (role chunk, tool-call
// chunk, finish chunk); only the tool-call one reaches handleToolCall.
const ollamaChoices = (id, args) => [
	{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null },
	{ index: 0, delta: { content: '', tool_calls: [{ id, index: 0, type: 'function',
		function: { name: 'wiki_wikipedia_search_articles', arguments: args } }] }, finish_reason: null },
	{ index: 0, delta: {}, finish_reason: 'tool_calls' },
];

function stream(message, choices) {
	for (const choice of choices) {
		if (choice.finish_reason) break;
		if (choice.delta.tool_calls) message = handleToolCall(message, choice);
	}
	return message;
}

// What useMessages.handleStream picks and passes to callTools.
const pending = (message) => message.content.find((c) => c.type === 'tool-call' && !c.result);

let failed = 0;
function check(name, fn) {
	try { fn(); console.log(`ok   - ${name}`); } catch (e) { failed++; console.log(`FAIL - ${name}: ${e.message}`); }
}

check('arguments sent whole in one delta reach callTools', () => {
	const msg = stream({ role: 'assistant', content: [] }, ollamaChoices('call_a1', '{"query":"Ariane 5","limit":3}'));
	const call = pending(msg);
	assert.ok(call, 'no tool call');
	assert.strictEqual(call.argsText, '{"query":"Ariane 5","limit":3}');
	assert.deepStrictEqual(call.args, { query: 'Ariane 5', limit: 3 });
});

check('arguments sent as a JSON object reach callTools', () => {
	const msg = stream({ role: 'assistant', content: [] }, ollamaChoices('call_a2', { query: 'Ariane 5', limit: 3 }));
	assert.deepStrictEqual(pending(msg).args, { query: 'Ariane 5', limit: 3 });
});

check('OpenAI-style fragments still accumulate into one call', () => {
	const frag = (f, id) => ({ index: 0, delta: { tool_calls: [{ index: 0, id, function: f }] }, finish_reason: null });
	const msg = stream({ role: 'assistant', content: [] }, [
		frag({ name: 'x', arguments: '' }, 'call_o'), frag({ arguments: '{"query":' }), frag({ arguments: '"Ariane 5"}' }),
	]);
	assert.strictEqual(msg.content.length, 1);
	assert.deepStrictEqual(pending(msg).args, { query: 'Ariane 5' });
});

check('a second call right after a resolved one is its own call', () => {
	let msg = stream({ role: 'assistant', content: [] }, ollamaChoices('call_b1', '{"query":"Ariane 5","limit":3}'));
	msg = { ...msg, content: msg.content.map((c) => ({ ...c, result: '{"content":[]}' })) };
	msg = stream(msg, ollamaChoices('call_b2', '{"query":"Ariane 6","limit":1}'));
	const call = pending(msg);
	assert.ok(call, 'the second tool call was merged into the first');
	assert.deepStrictEqual(call.args, { query: 'Ariane 6', limit: 1 });
});

/* --- follow-up: the provider's per-chunk loop, the base class, the hook helper --- */

// The real `for (const chunk of streamEvent.choices) { ... }` of
// OpenAIProvider.sendMessage, run against one stream event.
const indexSrc = read(SRC + 'providers/openai/index.ts');
const loop = block(indexSrc, 'for (const chunk of streamEvent.choices) {');
assert.ok(loop, 'chunk loop not found in openai/index.ts');
const runLoop = vm.runInNewContext(`(function (handlers, choices, self) {
	const { handleToolCall, handleTextMessage, handleReasoningMessage, finalizeReasoningPart } = handlers;
	const streamEvent = { choices };
	const afterToolCall = false, previousMessage = undefined;
	let responseMessage = { role: 'assistant', content: [] };
	let isStreamComplete = false, hasUnfinalizedReasoning = false;
	(function () { ${Module.stripTypeScriptTypes(loop)} }).call(self);
	return { responseMessage, isStreamComplete };
})`, { JSON });

check('a tool call in the same chunk as finish_reason is kept (older Ollama)', () => {
	const pushed = [];
	const self = { pushSingleMessage: (m) => pushed.push(m), filterAfterToolCallContent: (m) => m };
	const { responseMessage, isStreamComplete } = runLoop(handlers, [
		{ index: 0, delta: { content: '', tool_calls: [{ id: 'call_old', index: 0, type: 'function',
			function: { name: 'wiki_wikipedia_search_articles', arguments: '{"query":"Ariane 5","limit":3}' } }] },
		finish_reason: 'tool_calls' },
	], self);
	assert.ok(isStreamComplete, 'stream not completed');
	const call = pending(responseMessage);
	assert.ok(call, 'the tool call was dropped');
	assert.deepStrictEqual(call.args, { query: 'Ariane 5', limit: 3 });
	assert.ok(pending(pushed[0]), 'the tool call is missing from the pushed history');
});

check('two calls in one delta (Ollama) become two calls with their own arguments', () => {
	const msg = handleToolCall({ role: 'assistant', content: [] }, { index: 0, finish_reason: null, delta: { tool_calls: [
		{ id: 'call_p1', index: 0, type: 'function', function: { name: 'w', arguments: '{"query":"Ariane 5"}' } },
		{ id: 'call_p2', index: 1, type: 'function', function: { name: 'w', arguments: '{"query":"Ariane 6"}' } },
	] } });
	assert.deepStrictEqual(Array.from(msg.content, (c) => c.toolCallId), ['call_p1', 'call_p2']);
	assert.deepStrictEqual(Array.from(msg.content, (c) => c.args), [{ query: 'Ariane 5' }, { query: 'Ariane 6' }]);
});

check('two calls streamed as fragments by index (OpenAI) stay apart', () => {
	const tc = (index, extra) => ({ index: 0, finish_reason: null, delta: { tool_calls: [{ index, ...extra }] } });
	let msg = { role: 'assistant', content: [] };
	for (const c of [
		tc(0, { id: 'call_f1', function: { name: 'w', arguments: '' } }), tc(0, { function: { arguments: '{"query":' } }),
		tc(1, { id: 'call_f2', function: { name: 'w', arguments: '' } }), tc(1, { function: { arguments: '{"query":"B"}' } }),
		tc(0, { function: { arguments: '"A"}' } }),
	]) msg = handleToolCall(msg, c);
	assert.deepStrictEqual(Array.from(msg.content, (c) => c.args), [{ query: 'A' }, { query: 'B' }]);
});

// lib/utils.ts getNextPendingToolCallIdx, which useMessages uses to run every
// pending call before continuing.
const utilsSrc = read(SRC + 'lib/utils.ts');
const nextFn = block(utilsSrc, 'export const getNextPendingToolCallIdx = (');
const hookSrc = read(SRC + 'hooks/useMessages.ts');
check('useMessages runs every pending call of the message before continuing', () => {
	assert.ok(nextFn, 'getNextPendingToolCallIdx not found in lib/utils.ts');
	assert.ok(/getNextPendingToolCallIdx\(updatedMessage, idx\)/.test(hookSrc), 'useMessages does not use it');
	const next = vm.runInNewContext(`${Module.stripTypeScriptTypes(nextFn).replace(/^export const/, 'const')}\n;getNextPendingToolCallIdx`);
	const msg = { role: 'assistant', content: [{ type: 'tool-call', toolCallId: 'a', result: 'r' },
		{ type: 'tool-call', toolCallId: 'b' }, { type: 'text', text: '' }, { type: 'tool-call', toolCallId: 'c' }] };
	assert.strictEqual(next(msg, 0), 1);
	assert.strictEqual(next(msg, 1), 3);
	assert.strictEqual(next(msg, 3), -1);
});

// base.ts, loaded whole: which calls a provider answers after the tool run.
check('one result per unanswered call id is sent, and not again next round', () => {
	const baseSrc = read(SRC + 'providers/base.ts');
	const Base = vm.runInNewContext(`${Module.stripTypeScriptTypes(baseSrc).replace(/^export /gm, '')}\n;AbstractBaseProvider`);
	const provider = new (class extends Base {
		take(m) { return this.takeUnansweredToolCalls(m).map((c) => c.toolCallId); }
		remember(ms) { this.rememberAnsweredToolCalls(ms); }
	})();
	assert.strictEqual(typeof provider.takeUnansweredToolCalls, 'function', 'base class has no takeUnansweredToolCalls');
	const call = (id) => ({ type: 'tool-call', toolCallId: id, result: 'r' });
	provider.remember([{ role: 'assistant', content: [call('old')] }]);
	const turn1 = { role: 'assistant', content: [call('old'), call('p1'), call('p2')] };
	assert.deepStrictEqual(Array.from(provider.take(turn1)), ['p1', 'p2']);
	const turn2 = { ...turn1, content: [...turn1.content, { type: 'text', text: 'x' }, call('p3')] };
	assert.deepStrictEqual(Array.from(provider.take(turn2)), ['p3']);
});

console.log(failed ? `FAILED ${failed}` : 'PASS');
process.exit(failed ? 1 : 0);
