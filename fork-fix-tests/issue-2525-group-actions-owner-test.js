/*
 * #2525 follow-up - a plugin's StartAction("GroupActions") could outlive the
 * plugin and leave the document editor locked for good.
 *
 * While a group is open (word/api.js startGroupActions) the editor sets
 * AscCommon.CollaborativeEditing's global lock and selection lock, so the user
 * can neither type nor select (nor undo) until the plugin calls
 * EndAction("GroupActions"). The AI plugin streams "generate document" inside
 * such a group. If the plugin went away before closing it - closed, restarted,
 * stopped, unregistered/uninstalled, its connector dropped - nothing ever
 * closed the group and the document stayed locked until it was reopened.
 * A related path: an exception thrown by a plugin method escaped
 * common/plugins.js callMethodInternal before shiftCommand, so the command
 * queue stayed stuck on that task; every later call of every plugin (the
 * plugin's own EndAction included) just queued up behind it forever.
 *
 * Fix: startGroupActions records the guid of the plugin whose command is
 * running (CPluginsManager.getCurrentPluginGuid); the new
 * asc_docs_api.endOrphanGroupActions ends (not cancels: the text inserted so far
 * stays, as one undo point) the innermost groups whose plugin is no longer
 * running. CPluginsManager.close calls it, and so does shiftCommand, so a group
 * opened by a method that was still running when its plugin closed (async
 * paste in InsertStreamedContent) is ended when that method returns rather than
 * under it. callMethodInternal catches a throwing method and moves the queue on;
 * a queued method of an already closed plugin no longer dereferences its
 * missing runObject.
 *
 * This extracts by brace matching the REAL CPluginsManager methods (close,
 * callMethod, callMethodInternal, shiftCommand, getCurrentPluginGuid,
 * setPluginMethodReturnAsync, onPluginMethodReturn, isRunned, getPluginByGuid),
 * CCommandTask, the real word group-action methods (+ endOrphanGroupActions),
 * StartAction/EndAction, InsertStreamedContent and the real CHistory
 * group-point methods, and runs them against a stub document whose paste adds
 * one history point per chunk.
 *
 * Claimed: closing the plugin mid-stream (also while its InsertStreamedContent
 * is still running) releases both locks, keeps the streamed content, leaves one
 * undo point; a throwing method does not jam the queue and the plugin's
 * EndAction still runs; a well-behaved plugin, and a group of a plugin that
 * stays running while ANOTHER plugin closes, are unaffected.
 * NOT claimed: real HTML paste, layout, desktop save - checked with the
 * headless word editor (plugin driven through the real connector message path)
 * and x2t; see the commit message.
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
const BASE_REF = process.env.BASE_REF || 'aa1e8ff9aa^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* `<prefix> function(args) { body }` -> [args, body], or null when absent. */
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
const plugins = src('common/plugins.js');

const GROUP_METHODS = ['initGroupActions', 'startGroupActions', 'executeGroupActions', 'executeGroupActionsStart',
	'executeGroupActionsEnd', 'cancelGroupActions', 'endGroupActions', '_finishGroupActions', 'isGroupActions',
	'setUserScrollGroupActions', 'endOrphanGroupActions'];
const HISTORY_METHODS = ['startGroupPoints', 'cancelGroupPoints', 'endGroupPoints', 'getGroupChanges',
	'resetGroupChanges', 'private_UndoPoint', '_getLongPointIndex'];
const MANAGER_METHODS = ['close', 'callMethod', 'callMethodInternal', 'shiftCommand', 'getCurrentPluginGuid',
	'setPluginMethodReturnAsync', 'onPluginMethodReturn', 'isRunned', 'getPluginByGuid'];

const P = 'asc.{STREAMER}', OTHER = 'asc.{OTHER}';

function setup() {
	const st = { content: [], globalLock: false, selLock: false, sent: [], errors: [], pendingPaste: [], asyncPaste: false };
	const doc = {
		IsDocumentEditor: () => true, RemoveSelection() {}, TurnOff_Recalculate() {}, TurnOn_Recalculate() {},
		TurnOff_InterfaceEvents() {}, TurnOn_InterfaceEvents() {}, Recalculate() {}, RecalculateByChanges() {},
		UpdateInterface() {}, UpdateSelection() {}, SetSelectionState() {}, GetSelectionState() { return {}; },
		SaveDocumentState() { return {}; }, LoadDocumentState() {},
		FullRecalc: {}, GetSpellCheckManager() { return { TurnOn() {}, TurnOff() {} }; },
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
	function CPluginData() { this.a = {}; }
	CPluginData.prototype.setAttribute = function (k, v) { this.a[k] = v; };
	CPluginData.prototype.getAttribute = function (k) { return this.a[k]; };
	const env = {
		AscDFH: { historydescription_GroupPoints: 0xFF01, historydescription_GroupPointsOpen: 0xFF02 },
		AscCommon: {
			History,
			CollaborativeEditing: { Set_GlobalLock(v) { st.globalLock = v; }, Set_GlobalLockSelection(v) { st.selLock = v; } },
		},
		window: { AscCommon: { g_specialPasteHelper: { specialPasteStart: false, SpecialPasteButton_Hide() {} } } },
		document: { getElementById: () => null },
		console: { error(e) { st.errors.push(String(e)); }, log() {} },
		CPluginData,
		CommandTaskType: { Command: 0, Method: 1 },
	};
	const NAMES = Object.keys(env);
	const compile = f => new Function(...NAMES,
		'"use strict"; return function(' + f[0] + ') ' + f[1])(...NAMES.map(n => env[n]));
	env.CCommandTask = compile(extract(plugins.slice(plugins.indexOf('function CCommandTask(')), ''));
	NAMES.push('CCommandTask');

	for (const m of HISTORY_METHODS) {
		const f = extract(history, `CHistory.prototype.${m} = `);
		assert.ok(f, `CHistory.${m} not found`);
		History[m] = compile(f);
	}

	const api = {
		isLockScrollToTarget: false,
		private_GetLogicDocument: () => doc,
		asc_LockScrollToTarget() {}, scrollToTarget() {}, updateSelection() {},
		sync_StartAction() {}, sync_EndAction() {}, isLogPluginCommands: () => false, onPluginClose() {},
		// stands in for the clipboard paste: one history point per chunk; optionally finishes later (fonts, images)
		_pluginMethod_PasteHtml(html, callback) {
			const api = this;
			api.executeGroupActionsStart();
			History.Create_NewPoint(0);
			st.content.push(html);
			History.Points[History.Index].Items.push({ Data: {
				Undo() { st.content.splice(st.content.lastIndexOf(html), 1); }, CheckNeedRecalculate() {},
			} });
			const done = () => { api.executeGroupActionsEnd(); callback && callback(); };
			if (st.asyncPaste) st.pendingPaste.push(done); else done();
		},
	};
	api.pluginMethod_PasteText = function (text) { this._pluginMethod_PasteHtml('TEXT:' + text); };
	for (const m of GROUP_METHODS) {
		const f = extract(apiWord, `asc_docs_api.prototype.${m} = `) || extract(apiBase, `baseEditorsApi.prototype.${m} = `);
		if (f) api[m] = compile(f);
	}
	for (const m of ['StartAction', 'EndAction'])
		api['pluginMethod_' + m] = compile(extract(apiBasePlugins, `Api.prototype["pluginMethod_${m}"] = `));
	api.pluginMethod_InsertStreamedContent = compile(extract(apiPlugins, 'Api.prototype["pluginMethod_InsertStreamedContent"] = '));

	const plugin = guid => ({ guid, isBackground: () => true, variations: [{}] });
	const mgr = {
		api, queueCommands: [], internalGuid: 'onlyoffice_internal_guid', internalCallbacks: [], internalCommandAsync: false,
		pluginsMap: { [P]: plugin(P), [OTHER]: plugin(OTHER) }, runnedPluginsMap: {}, sendsToInterface: {},
		runAndCloseData: null,
		removeUsedBackgroundPlugins() {}, closeAllWindows() {}, endLongAction() {},
		sendMessageToFrame(frameId, data) { st.sent.push(data.getAttribute('type')); },
	};
	for (const m of MANAGER_METHODS) {
		const f = extract(plugins, `\n\t\t${m} : `);
		assert.ok(f, `CPluginsManager.${m} not found`);
		mgr[m] = compile(f);
	}
	for (const g of [P, OTHER])
		mgr.runnedPluginsMap[g] = { frameId: 'iframe_' + g, currentVariation: 0, startData: null, methodReturnAsync: false };
	env.window.g_asc_plugins = mgr;
	api.initGroupActions();

	// what the plugin sees: a call returns once the editor posts onMethodReturn back
	const call = (guid, name, args) => {
		const before = st.sent.length;
		try { mgr.callMethod(guid, name, args); }
		catch (e) { return 'threw: ' + e.message; }
		return st.sent.length > before ? 'returned' : 'no return';
	};
	const ISC = (guid, stable, tail, undo) => call(guid, 'InsertStreamedContent', [{ stable, tail, undo, word: { removeSelection: true } }]);
	const unlocked = () => !st.globalLock && !st.selLock && !api.isGroupActions();
	return { st, api, mgr, History, call, ISC, unlocked };
}

// the MarkDownStreamer sequence up to the middle of the stream
function startStream(t, guid) {
	const pointsBefore = t.History.Points.length;
	t.call(guid, 'StartAction', ['GroupActions']);
	t.call(guid, 'PasteText', ['\n']);
	t.ISC(guid, '<p>AISTABLE1</p>', '<p>AITAIL1</p>', false);
	t.ISC(guid, '<p>AISTABLE2</p>', '<p>AITAIL2</p>', true);
	assert.ok(t.st.globalLock && t.st.selLock, 'setup: the editor is locked while the stream runs');
	return pointsBefore;
}
const KEPT = ['TEXT:\n', '<p>AISTABLE1</p>', '<p>AISTABLE2</p>', '<p>AITAIL2</p>'];

function checkReleased(t, pointsBefore, what) {
	assert.ok(t.unlocked(), `${what}: editor still locked (global lock ${t.st.globalLock}, selection lock ` +
		`${t.st.selLock}, group open ${t.api.isGroupActions()}) - the user cannot type until the document is reopened`);
	assert.deepStrictEqual(t.st.content, KEPT, `${what}: content inserted before the plugin went away must stay`);
	assert.strictEqual(t.History.Points.length - pointsBefore, 1, `${what}: the generation must be ONE undo point`);
	t.History.private_UndoPoint(t.History.Points[t.History.Index], []);
	assert.deepStrictEqual(t.st.content, [], `${what}: one undo removes the whole generation`);
}

// 1. the plugin is closed (stopped, restarted, unregistered: all go through CPluginsManager.close) mid-stream
{
	const t = setup();
	const before = startStream(t, P);
	t.mgr.close(P);
	checkReleased(t, before, 'plugin closed mid-stream');
	assert.deepStrictEqual(t.st.errors, []);
}

// 2. it is closed while its InsertStreamedContent is still running (async paste): ended once the method returns
{
	const t = setup();
	const before = startStream(t, P);
	t.st.asyncPaste = true;
	t.ISC(P, '<p>AISTABLE3</p>', '<p>AITAIL3</p>', true);
	t.mgr.close(P);
	assert.ok(t.api.isGroupActions(), 'a group must not be ended under the plugin method that is still running');
	while (t.st.pendingPaste.length) t.st.pendingPaste.shift()();
	assert.ok(t.unlocked(), 'plugin closed during InsertStreamedContent: editor still locked after the method finished');
	assert.deepStrictEqual(t.st.content, ['TEXT:\n', '<p>AISTABLE1</p>', '<p>AISTABLE2</p>', '<p>AISTABLE3</p>', '<p>AITAIL3</p>']);
	assert.strictEqual(t.History.Points.length - before, 1, 'one undo point');
	assert.strictEqual(t.mgr.queueCommands.length, 0, 'command queue drained');
	assert.deepStrictEqual(t.st.errors, []);
}

// 3. a plugin method throws inside the group: the queue moves on and the plugin's own EndAction still runs
{
	const t = setup();
	const before = startStream(t, P);
	const r = t.call(P, 'InsertStreamedContent', []); // no argument: throws on streamObj["word"]
	assert.strictEqual(r, 'returned', `a throwing plugin method must still return to the plugin (got: ${r})`);
	assert.strictEqual(t.mgr.queueCommands.length, 0, 'command queue stuck on the throwing method');
	assert.strictEqual(t.call(P, 'EndAction', ['GroupActions']), 'returned');
	assert.strictEqual(t.call(P, 'EndAction', ['GroupActions']), 'returned');
	checkReleased(t, before, 'method threw');
}

// 4. well-behaved plugin, and another plugin closing in the middle of its stream: nothing changes
{
	const t = setup();
	const before = startStream(t, P);
	t.mgr.close(OTHER);
	assert.ok(t.api.isGroupActions() && t.st.globalLock, 'closing another plugin must not end this plugin\'s group');
	t.call(P, 'EndAction', ['GroupActions']); // keep the last tail
	assert.ok(t.api.isGroupActions(), 'outer group still open until the plugin ends it');
	t.call(P, 'EndAction', ['GroupActions']);
	checkReleased(t, before, 'well-behaved plugin');
	assert.deepStrictEqual(t.st.errors, []);
}

console.log('ok - a GroupActions group never outlives the plugin that opened it; content kept as one undo step');
