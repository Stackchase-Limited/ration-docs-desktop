/*
 * #2525 (found while triaging) - the AI plugin's "generate document" inserted
 * NOTHING into a text document.
 *
 * The bundled AI plugin (scripts/generate.js, MarkDownStreamer) streams the
 * generated markdown as HTML through the plugin method InsertStreamedContent:
 *   StartAction("GroupActions"); PasteText("\n"); then per chunk
 *   InsertStreamedContent({stable, tail, undo}); at the end
 *   EndAction("GroupActions") for the last tail and once more for the outer group.
 * Each call with undo=true must roll back the previous provisional tail, and the
 * whole generation should be one undo step. Two things were missing in our sdkjs:
 *  - InsertStreamedContent itself (removed upstream in 5dde32b68f); plugins.js
 *    callMethodInternal silently ignores an unknown method, so nothing happened;
 *  - the group actions behind StartAction/EndAction("GroupActions") were stubs
 *    (common/apiBase.js, since 8954b14a69), so a "cancel" kept the old tail
 *    (both the partial chunk and the final text ended up in the document) and
 *    every chunk was its own undo step.
 * The fix restores the last public InsertStreamedContent (word/api_plugins.js)
 * and the last public group-actions implementation for the word editor
 * (word/api.js, asc_docs_api overrides of the apiBase stubs).
 *
 * This extracts by brace matching the REAL InsertStreamedContent, the real
 * StartAction/EndAction plugin methods, the group-action methods (word/api.js,
 * falling back to the apiBase.js stubs when word/api.js has none, as on the
 * baseline) and the real CHistory group-point methods (word/Editor/History.js),
 * then replays the plugin's call sequence against a stub document whose
 * "paste" records one history item per pasted chunk.
 *
 * Claimed: the final content is exactly stable chunks + last tail, no rolled-
 * back tail survives, the generation is one history point that undoes in one
 * step, the global edit lock is released at the end, and after a save in the
 * middle of the stream the merged point is not counted as saved (CHistory.
 * endGroupPoints lowers SavedIndex; without that the next desktop save wrote
 * nothing and the file kept the half-streamed text).
 * NOT claimed: real HTML paste, layout, or the desktop save; those were checked
 * with the headless editor + x2t replay harness (see the commit message).
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the sources at
 * BASE_REF with git show, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '425850a934^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* `<prefix> = function(args) { body }` -> [args, body], or null when absent. */
function extract(text, prefix) {
	const at = text.indexOf(prefix);
	if (at === -1)
		return null;
	const fn = text.indexOf('function', at + prefix.length);
	const open = text.indexOf('{', fn);
	const args = text.slice(text.indexOf('(', fn) + 1, text.lastIndexOf(')', open));
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return [args, text.slice(open, i + 1)];
	}
	throw new Error('unbalanced braces after ' + prefix);
}

const apiWord = src('word/api.js');
const apiBase = src('common/apiBase.js');
const apiPlugins = src('word/api_plugins.js');
const apiBasePlugins = src('common/apiBase_plugins.js');
const history = src('word/Editor/History.js');

const env = {};
function compile(fnSrc) {
	return new Function('AscCommon', 'AscDFH', 'window',
		'"use strict"; return function(' + fnSrc[0] + ') ' + fnSrc[1])(env.AscCommon, env.AscDFH, env.window);
}

const GROUP_METHODS = ['initGroupActions', 'startGroupActions', 'executeGroupActions', 'executeGroupActionsStart',
	'executeGroupActionsEnd', 'cancelGroupActions', 'endGroupActions', '_finishGroupActions', 'isGroupActions',
	'setUserScrollGroupActions'];
const HISTORY_METHODS = ['startGroupPoints', 'cancelGroupPoints', 'endGroupPoints', 'getGroupChanges',
	'resetGroupChanges', 'private_UndoPoint', '_getLongPointIndex', 'GetDeleteIndex'];

function run(saveMidStream) {
	const content = [];          // the document: one entry per pasted chunk
	const log = { pastedWhileLocked: 0 };
	let globalLock = false;

	const doc = {
		IsDocumentEditor: () => true, RemoveSelection() {}, TurnOff_Recalculate() {}, TurnOn_Recalculate() {},
		TurnOff_InterfaceEvents() {}, TurnOn_InterfaceEvents() {}, Recalculate() {}, RecalculateByChanges() {},
		UpdateInterface() {}, UpdateSelection() {}, SetSelectionState() {}, GetSelectionState() { return {}; },
		SaveDocumentState() { return {}; }, LoadDocumentState() {}, FullRecalc: {},
		GetSpellCheckManager() { return { TurnOn() {}, TurnOff() {} }; },
	};
	const History = {
		Points: [], Index: -1, GroupChanges: [], UndoRedoInProgress: false, Document: doc, SavedIndex: null,
		Set_SavedIndex(index) { this.SavedIndex = index; },
		Create_NewPoint(description) {
			this.Points[++this.Index] = { State: {}, Items: [], Description: description };
			this.Points.length = this.Index + 1;
		},
		ClearRedo() { this.Points.length = this.Index + 1; },
		private_UpdateContentChangesOnUndo() {},
	};
	env.AscDFH = { historydescription_GroupPoints: 0xFF01, historydescription_GroupPointsOpen: 0xFF02 };
	env.AscCommon = {
		History,
		CollaborativeEditing: { Set_GlobalLock(v) { globalLock = v; }, Set_GlobalLockSelection() {} },
	};
	env.window = {
		AscCommon: { g_specialPasteHelper: { specialPasteStart: false, SpecialPasteButton_Hide() {} } },
		g_asc_plugins: { setPluginMethodReturnAsync() {}, onPluginMethodReturn() {} },
	};
	for (const m of HISTORY_METHODS) {
		const f = extract(history, `CHistory.prototype.${m} = `);
		assert.ok(f, `CHistory.${m} not found`);
		History[m] = compile(f);
	}

	const api = {
		isLockScrollToTarget: false,
		private_GetLogicDocument: () => doc,
		asc_LockScrollToTarget() {}, scrollToTarget() {}, updateSelection() {},
		sync_StartAction() {}, sync_EndAction() {},
		// stands in for the clipboard paste: one history point, one undoable item per chunk
		_pluginMethod_PasteHtml(html, callback) {
			this.executeGroupActionsStart();
			if (globalLock) log.pastedWhileLocked++;
			History.Create_NewPoint(0);
			content.push(html);
			History.Points[History.Index].Items.push({ Data: {
				Undo() { content.splice(content.lastIndexOf(html), 1); }, CheckNeedRecalculate() {},
			} });
			this.executeGroupActionsEnd();
			callback && callback();
		},
		pluginMethod_PasteText(text) { this._pluginMethod_PasteHtml('TEXT:' + text); },
	};
	for (const m of GROUP_METHODS) {
		const f = extract(apiWord, `asc_docs_api.prototype.${m} = `) || extract(apiBase, `baseEditorsApi.prototype.${m} = `);
		if (f) api[m] = compile(f);
	}
	for (const m of ['StartAction', 'EndAction'])
		api['pluginMethod_' + m] = compile(extract(apiBasePlugins, `Api.prototype["pluginMethod_${m}"] = `));
	const isc = extract(apiPlugins, 'Api.prototype["pluginMethod_InsertStreamedContent"] = ');
	if (isc) api['pluginMethod_InsertStreamedContent'] = compile(isc);
	api.initGroupActions();

	// common/plugins.js callMethodInternal: unknown methods are silently ignored
	function callMethod(name, args) {
		const f = api['pluginMethod_' + name];
		if (!f) return undefined;
		if (name === 'StartAction' || name === 'EndAction') return f.apply(api, args);
		return api.executeGroupActions(() => f.apply(api, args));
	}
	const ISC = (stable, tail, undo) => callMethod('InsertStreamedContent',
		[{ stable, tail, undo, word: { removeSelection: true } }]);

	const pointsBefore = History.Points.length;
	// MarkDownStreamer.onStreamChunk prelude
	callMethod('StartAction', ['GroupActions']);
	callMethod('PasteText', ['\n']);
	// chunks: tail only, then stable+tail replacing the old tail, then a longer tail
	ISC('', '<p>AITAIL1</p>', false);
	ISC('<p>AISTABLE para</p><table><tr><td>AISCELL</td></tr></table>', '<p>AITAIL2</p>', true);
	let savedItems = 0;
	if (saveMidStream) {
		// the user saves while the stream runs: points 0..Index go to disk (Reset_SavedIndex)
		History.SavedIndex = History.Index;
		for (let i = 0; i <= History.Index; i++) savedItems += History.Points[i].Items.length;
	}
	ISC('', '<p>AITAIL2 final words</p>', true);
	// onStreamEnd: keep the last tail, then close the outer group
	callMethod('EndAction', ['GroupActions']);
	callMethod('EndAction', ['GroupActions']);

	return { content, History, pointsBefore, globalLock, api, log, iscPresent: !!isc, savedItems };
}

const r = run();
assert.ok(r.iscPresent, 'pluginMethod_InsertStreamedContent is missing: plugins.js ignores the call and the AI ' +
	'"generate document" inserts nothing');
const EXPECTED = [
	'TEXT:\n',
	'<p>AISTABLE para</p><table><tr><td>AISCELL</td></tr></table>',
	'<p>AITAIL2 final words</p>',
];
assert.deepStrictEqual(r.content, EXPECTED, 'document must hold exactly the stable chunks and the last tail; rolled-back tails must be gone');
assert.strictEqual(r.api.isGroupActions(), false, 'group actions still open after the stream ended');
assert.strictEqual(r.globalLock, false, 'global edit lock left on: the user could not type after generation');
assert.strictEqual(r.log.pastedWhileLocked, 0, 'a paste ran under the global lock');
assert.strictEqual(r.History.Points.length - r.pointsBefore, 1,
	`generation must be ONE undo step, got ${r.History.Points.length - r.pointsBefore} history points`);

// undo that single point with the real CHistory.private_UndoPoint
r.History.private_UndoPoint(r.History.Points[r.History.Index], []);
assert.deepStrictEqual(r.content, [], 'one undo must remove the whole generated content');

/* A save in the middle of the stream: the merged group point must count as unsaved, otherwise the next
 * save sends nothing (CollaborativeEditingBase.private_CollectOwnChanges starts at SavedIndex + 1) and its
 * deleteIndex claims the unsent changes as saved - the file keeps the half-streamed text. */
{
	const m = run(true);
	assert.deepStrictEqual(m.content, EXPECTED);
	assert.ok(m.History.SavedIndex < m.History.Index,
		`after a mid-stream save the merged point is treated as saved (SavedIndex=${m.History.SavedIndex}, ` +
		`Index=${m.History.Index}): the next save would write nothing and the file keeps the partial text`);
	assert.ok(m.History.GetDeleteIndex() <= m.savedItems,
		`deleteIndex ${m.History.GetDeleteIndex()} claims more than the ${m.savedItems} changes actually saved`);
}

console.log('ok - streamed AI insertion keeps exactly the final text and undoes in one step');
