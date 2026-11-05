/*
 * #2524 - "AI Tools agent fails with Mistral API error 400 / code 3230
 * (invalid_request_message_order) after any tool call".
 *
 * Mistral serves a request only when the last message is user or tool, and an
 * assistant message with toolCalls must be followed by one tool message per
 * call; otherwise it answers 400 / code 3230.
 *
 * What is in OUR (9.4) code: the live agent loop is fine - MistralProvider
 * pushes assistant(toolCalls), then the tool message, then sends; against a
 * mock that enforces the rules above the first tool turn of a new thread goes
 * through. (The report is against 10.0, whose AI agent is a different, rewritten
 * engine; its exact first-turn failure is not in this code.) What breaks is the
 * history: a finished agent turn is stored as ONE assistant message holding
 * [text, tool-call + result, text], and src/providers/mistral/utils.ts
 * convertMessagesToModelFormat turned it into a single assistant message with
 * toolCalls and NO tool message - it only looked for tool results on *user*
 * messages, which never carry them, and took the call id from part.parentId.
 * setPrevMessages runs that converter whenever a thread is reopened or the
 * provider is switched to Mistral, so every later request in a thread that
 * once used a tool was rejected with 3230.
 *
 * This loads the REAL utils.ts (types stripped with node's own
 * module.stripTypeScriptTypes; the file has only type imports), converts a
 * stored tool turn plus a new user message, and checks the result against the
 * ordering rules Mistral enforces.
 *
 * Claimed: the converted history is assistant(toolCalls with the right id) ->
 * tool(result) -> assistant(text) -> user, which satisfies those rules.
 * NOT claimed: the real Mistral API (no key here) - the rules are the ones its
 * 3230 errors state; the HTTP round trip with the real SDK and provider is in
 * the in-tree vitest test src/providers/mistral/tests/toolHistory.test.ts.
 *
 * RD_REPO=<desktop-sdk checkout> (default ../desktop-sdk). BASELINE=1 reads the
 * source at BASE_REF with git show, where it must fail. Needs a node with
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
const BASE_REF = process.env.BASE_REF || 'ac6f93e4^';
const FILE = 'ChromiumBasedEditors/plugins/ai-agent/src/providers/mistral/utils.ts';

const text = process.env.BASELINE
	? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${FILE}`], { encoding: 'utf8' })
	: fs.readFileSync(path.join(REPO, FILE), 'utf8');

if (/^import (?!type )/m.test(text)) throw new Error('utils.ts gained a value import; the loader cannot run it');
const js = Module.stripTypeScriptTypes(text).replace(/^export const/gm, 'const');
const { convertMessagesToModelFormat: convertInVm } = vm.runInNewContext(`${js}\n;({ convertMessagesToModelFormat })`, { JSON });
assert.strictEqual(typeof convertInVm, 'function', 'convertMessagesToModelFormat not found');
// Back into this realm (the vm's arrays have another Array.prototype), and as it is sent.
const convertMessagesToModelFormat = (messages) => JSON.parse(JSON.stringify(convertInVm(messages)));

// Mistral's ordering rules, with the error each one produces.
function orderError(messages) {
	const last = messages[messages.length - 1];
	if (last.role !== 'user' && last.role !== 'tool') return `last role ${last.role}`;
	for (let i = 0; i < messages.length; i++) {
		const m = messages[i];
		if (m.role === 'tool' && messages[i - 1].role !== 'tool' && !(messages[i - 1].toolCalls || []).length)
			return `tool message at ${i} does not follow a tool call`;
		if (m.role !== 'assistant' || !(m.toolCalls || []).length) continue;
		const answered = [];
		for (let j = i + 1; j < messages.length && messages[j].role === 'tool'; j++) answered.push(messages[j].toolCallId);
		const ids = m.toolCalls.map((c) => c.id);
		if (JSON.stringify(ids.slice().sort()) !== JSON.stringify(answered.slice().sort()))
			return `assistant at ${i} has tool calls ${JSON.stringify(ids)} but tool answers ${JSON.stringify(answered)}`;
	}
	return null;
}

// A thread as the plugin stores it: one finished agent turn and a new question.
const thread = [
	{ role: 'user', content: [{ type: 'text', text: 'Merge a.pdf and b.pdf' }] },
	{ role: 'assistant', content: [
		{ type: 'text', text: 'Merging.' },
		{ type: 'tool-call', toolCallId: 'D681PevKs', toolName: 'pdf_merge', args: { n: 2 }, argsText: '{"n":2}',
			result: { content: [{ type: 'text', text: 'ok' }], isError: false }, parentId: 'D681PevKs' },
		{ type: 'text', text: 'Merged into merged.pdf.' },
	] },
	{ role: 'user', content: [{ type: 'text', text: 'Now merge c.pdf too' }] },
];

let failed = 0;
function check(name, fn) {
	try { fn(); console.log(`ok   - ${name}`); } catch (e) { failed++; console.log(`FAIL - ${name}: ${e.message}`); }
}

const out = convertMessagesToModelFormat(thread);
check('a reloaded thread with a tool turn is in an order Mistral serves', () => {
	assert.strictEqual(orderError(out), null);
});
check('the turn becomes assistant(toolCalls) -> tool -> assistant(text) -> user', () => {
	assert.deepStrictEqual(out.map((m) => m.role), ['user', 'assistant', 'tool', 'assistant', 'user']);
	assert.strictEqual(out[1].toolCalls[0].id, 'D681PevKs');
	assert.strictEqual(out[2].toolCallId, 'D681PevKs');
	assert.deepStrictEqual(JSON.parse(out[2].content), { content: [{ type: 'text', text: 'ok' }], isError: false });
	assert.strictEqual(out[3].content[0].text, 'Merged into merged.pdf.');
});
check('the live loop push (call, no result yet) is one assistant message with the toolCallId', () => {
	const live = convertMessagesToModelFormat([{ role: 'assistant', content: [{ type: 'text', text: '' },
		{ type: 'tool-call', toolCallId: 'X1', toolName: 'pdf_merge', args: {}, argsText: '{}', result: '' }] }]);
	assert.deepStrictEqual(live.map((m) => m.role), ['assistant']);
	assert.strictEqual(live[0].toolCalls[0].id, 'X1');
});

console.log(failed ? `FAILED ${failed}` : 'PASS');
process.exit(failed ? 1 : 0);
