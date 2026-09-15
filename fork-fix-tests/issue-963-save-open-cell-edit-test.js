/*
 * #963 - Ctrl+S while a cell is still being edited saved nothing and lost the
 * typed value, with no message.
 *
 * BACK-FILLED. The fix was committed earlier with no test; see the verification
 * status section of UPSTREAM_TRIAGE.md for why that matters.
 *
 * _prepareSave commits an edit that is still open in an inline editor, and the
 * pending text only becomes a history change once that editor closes. asc_Save
 * used to ask "is there anything to save?" first and call _prepareSave only
 * inside that branch - so with an open edit the question was answered against
 * the pre-edit state, found nothing, and returned having thrown the typed value
 * away silently.
 *
 * NOTE ON THE BASELINE: a back-filled test cannot baseline against HEAD, which
 * already contains the fix - it would pass both ways and prove nothing. The
 * default below is the commit before the fix landed.
 *
 *   node issue-963-save-open-cell-edit-test.js   -> passes
 *   BASELINE=1 node issue-963-...-test.js        -> fails, at bbb6f9ee63^
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'common/apiBase.js';
const BASE_REF = process.env.BASE_REF || 'bbb6f9ee63^';

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

const at = source.indexOf('baseEditorsApi.prototype.asc_Save = function (isAutoSave, isIdle)');
assert.notStrictEqual(at, -1, 'asc_Save not found');
const fnSrc = matched(source, source.indexOf('(', at + 'baseEditorsApi.prototype.asc_Save = function'.length - 8));
assert.ok(fnSrc.includes('_prepareSave'), 'extracted the wrong function');

/* --- stubs ---
 * The editor with an open cell edit: nothing is a "change" yet, because the
 * pending text only becomes one when _prepareSave closes the editor. */
function makeApi(opts) {
	let committed = false;
	const api = {
		canSave: true,
		IsUserSave: false,
		canUnlockDocument: false,
		forceSaveUndoRequest: false,
		forceSaveSendFormRequest: false,
		forceSaveDisconnectRequest: false,
		forceSaveOformRequest: false,
		isForceSaveOnUserSave: false,
		askedToSave: false,
		_saveCheck: () => true,
		canSendChanges: () => true,
		_prepareSave: function () { committed = true; return opts.prepareSucceeds !== false; },
		/* These are the questions asc_Save asks. With an edit still open they are
		 * all false until _prepareSave has run. */
		/* An edit still open in the inline editor is not yet a change - it becomes one
		 * only when _prepareSave closes the editor. Changes made earlier are changes
		 * either way. */
		asc_isDocumentCanSave: () => committed && !!opts.hasOpenEdit,
		_haveChanges: () => (committed && !!opts.hasOpenEdit) || !!opts.hasPriorChanges,
		_haveOtherChanges: () => false,
		forceSave: function () {},
		checkSaveDocumentEvent: function () {},
		CoAuthoringApi: { askSaveChanges: function (cb) { api.askedToSave = true; cb && cb({}); } },
		_onSaveCallback: function () {},
	};
	api.wasCommitted = () => committed;
	return api;
}

const asc_Save = new Function('"use strict"; return function' + fnSrc)();

/* --- the defect: an edit is open and there is nothing else to save --- */
{
	const api = makeApi({ hasOpenEdit: true, hasPriorChanges: false });
	const res = asc_Save.call(api, false, false);
	assert.ok(api.wasCommitted(),
		'the open cell edit must be committed before asking whether there is anything ' +
		'to save - otherwise the typed value is silently discarded (#963)');
	assert.ok(api.askedToSave,
		'and the save must actually be requested; returning quietly is what lost the value');
	assert.strictEqual(res, true, 'asc_Save must report that it saved');
}

/* --- a document with nothing pending must still not save --- */
{
	const api = makeApi({ hasOpenEdit: false, hasPriorChanges: false });
	const res = asc_Save.call(api, false, false);
	assert.strictEqual(api.askedToSave, false, 'nothing to save must not request a save');
	assert.strictEqual(res, false);
}

/* --- ordinary changes, no open edit: unchanged behaviour --- */
{
	const api = makeApi({ hasOpenEdit: false, hasPriorChanges: true });
	asc_Save.call(api, false, false);
	assert.ok(api.askedToSave, 'an ordinary modified document must still save');
}

/* --- if committing the edit fails, do not claim to have saved --- */
{
	const api = makeApi({ hasOpenEdit: true, hasPriorChanges: false, prepareSucceeds: false });
	const res = asc_Save.call(api, false, false);
	assert.strictEqual(res, false, 'a failed commit must not report success');
}

console.log('ok - an open cell edit is committed before asc_Save decides there is nothing to do');
