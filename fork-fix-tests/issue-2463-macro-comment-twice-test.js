/*
 * #2463 - a comment added from a macro or plugin with ApiRange.AddComment
 * appeared twice in the Comments panel until the document was reopened
 * (upstream bug 83298, fixed in 10.0 by sdkjs 551cb909f3; backported here).
 *
 * Cause: AddCommentToDocument (word/apiBuilder.js), which ApiRange, ApiRun,
 * ApiTable, ApiInlineLvlSdt and ApiBlockLvlSdt AddComment all go through,
 * called logicDocument.AddComment and then api.sync_AddComment for the new
 * comment. CDocument.prototype.AddComment (word/Editor/Document.js) already
 * ends with this.Api.sync_AddComment for every comment it creates, so the
 * asc_onAddComment event that the Comments panel listens to fired twice.
 * Reproduced headless in docbuilder: one ApiRange.AddComment fired
 * asc_onAddComment twice with the 9.4 build, once with the fix.
 *
 * This extracts the REAL AddCommentToDocument and CDocument.prototype.AddComment
 * by brace matching and runs them against stubs, for a selection comment (the
 * ApiRange path) and a global one (AddGlobalCommentToDocument), counting the
 * sync_AddComment calls - one per comment is right.
 * NOT claimed: the web-apps Comments panel itself, or the other builder paths
 * that create a CComment directly (they never called CDocument.AddComment and
 * announce the comment once themselves).
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the sources at
 * BASE_REF (default: the parent of the fix commit) with git show, where it
 * must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '3fae1156fb^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	let depth = 0;
	for (let i = text.indexOf('{', at); i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}

const builderSrc = src('word/apiBuilder.js');
const documentSrc = src('word/Editor/Document.js');

/* --- stubs --- */
let announced = [];
function CComment(comments, data) { this.Id = 'c' + (CComment.n = (CComment.n || 0) + 1); this.Data = data; }
CComment.prototype.GetId = function () { return this.Id; };
CComment.prototype.GetData = function () { return this.Data; };
CComment.prototype.GenerateDurableId = function () { this.DurableId = 1; };
function ApiComment(comment) { this.Comment = comment; }

function CDocument() {
	this.Comments = { list: [], Add(c) { this.list.push(c); } };
	this.Api = { sync_AddComment(id) { announced.push(id); } };
	this.Controller = { AddComment() {} };
}
CDocument.prototype.CanAddComment = function () { return true; };
CDocument.prototype.UpdateInterface = function () {};
CDocument.prototype.UpdateSelection = function () {};
CDocument.prototype.Recalculate = function () {};
CDocument.prototype.GetSelectedText = function () { return 'Hello'; };
CDocument.prototype.GetCurrentParagraph = function () { return null; };
CDocument.prototype.GetApi = function () { return this.Api; };

new Function('CDocument', 'AscCommon',
	extract(documentSrc, 'CDocument.prototype.AddComment = function') + ';')(CDocument, { CComment });

const api = new Function('ApiComment',
	extract(builderSrc, 'function AddGlobalCommentToDocument(') + '\n' +
	extract(builderSrc, 'function AddCommentToDocument(') +
	'\nreturn { AddCommentToDocument, AddGlobalCommentToDocument };')(ApiComment);

function commentData() { return { quote: undefined, Set_QuoteText(t) { this.quote = t; } }; }

/* 1. ApiRange.AddComment: a comment on the selection. */
const doc = new CDocument();
const rangeComment = api.AddCommentToDocument(doc, commentData());
assert.ok(rangeComment instanceof ApiComment, 'no comment returned');
assert.strictEqual(rangeComment.Comment.Data.quote, 'Hello');
assert.deepStrictEqual(announced, [rangeComment.Comment.Id],
	'the comment was announced ' + announced.length + ' times; the Comments panel lists it that many times');

/* 2. a global comment (no selection). */
announced = [];
const globalComment = api.AddGlobalCommentToDocument(doc, commentData());
assert.deepStrictEqual(announced, [globalComment.Comment.Id],
	'the global comment was announced ' + announced.length + ' times');
assert.strictEqual(doc.Comments.list.length, 2);

console.log('PASS #2463: a comment added through the builder API is announced to the UI once' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
