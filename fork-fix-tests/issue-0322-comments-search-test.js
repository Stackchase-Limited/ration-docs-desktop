/*
 * #322 - comments could not be searched. Find looks at the document text only,
 * and the Comments panel (web-apps Common.Views.Comments, shared by the
 * document, spreadsheet, presentation and PDF editors) could be sorted and
 * filtered by status or user group but had no way to look for a word.
 *
 * Fix (web-apps): a search box in the panel header (CommentsPanel.template,
 * view Comments.js fires comment:filtertext; Esc clears it). The controller
 * keeps the text (setFilterText) and applyCombinedFilter hides a comment unless
 * the text is found, ignoring case, in the comment, the quoted document text,
 * the author, or any reply (text or author); readSDKComment and
 * onApiChangeCommentData apply it to comments added or changed meanwhile. The
 * status/group filters combine with it.
 *
 * This extracts the REAL setFilterText, isFilteredByText, applyCombinedFilter
 * and onApiChangeCommentData from controller/Comments.js and runs them on real
 * Backbone models (web-apps vendor/backbone + underscore) with a stubbed SDK
 * comment; it checks by text that the view creates the input and fires the
 * event, the controller listens to it, and the stylesheet moves the list down
 * by the header's new height.
 *
 * NOT claimed: the panel as drawn (header layout, RTL, themes) - needs a GUI
 * check in the built editors.
 *
 * RD_REPO overrides the web-apps checkout (default ../web-apps). BASELINE=1
 * reads the parent of the fix commit (BASE_REF), where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '62bf4b1e8b^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
/* "name: function (...) {...}" from an object literal, or null */
function method(source, name) {
	const m = new RegExp('\\n\\s*' + name + '\\s*:\\s*function\\b').exec(source);
	if (!m) return null;
	const src = block(source, m.index);
	return src.slice(src.indexOf('function'));
}

let failed = 0;
function check(what, fn) {
	try { fn(); console.log('ok   ' + what); }
	catch (e) { failed++; console.log('FAIL ' + what + ': ' + e.message); }
}

/* real underscore + Backbone from web-apps/vendor (not from the ref: vendor is unchanged) */
const ctx = { console };
ctx.window = ctx;
ctx.self = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(REPO, 'vendor/underscore/underscore.js'), 'utf8'), ctx);
vm.runInContext('var exports = undefined, module = undefined, define = undefined;' +
	fs.readFileSync(path.join(REPO, 'vendor/backbone/backbone.js'), 'utf8'), ctx);
const _ = ctx._, Backbone = ctx.Backbone;
assert.ok(_ && Backbone && Backbone.Collection, 'vendor libraries did not load');

const controllerSrc = read('apps/common/main/lib/controller/Comments.js');
const names = ['setFilterText', 'isFilteredByText', 'applyCombinedFilter', 'onApiChangeCommentData', 'setFilterComments'];
const methods = {};
for (const n of names) {
	const src = method(controllerSrc, n);
	methods[n] = src ? vm.runInContext('(' + src + ')', ctx) : null;
}

function makeController() {
	const c = {
		collection: new Backbone.Collection(),
		currentGroupFilter: null,
		currentTypeFilter: null,
		updates: 0,
		updateComments() { this.updates++; },
		getComparator: () => 'date-desc',
		popoverComments: { findWhere: () => true },
		getPopover: () => null,
		userCollection: { findOriginalUser: () => null },
		stringOOToLocalDate: () => 0, stringUtcToLocalDate: () => 0, dateToLocaleTimeString: () => '',
		mode: { canEditComments: true, canDeleteComments: true },
		currentUserId: 'u1',
		appPrefix: 'de-',
	};
	for (const n of names) if (methods[n]) c[n] = methods[n];
	c.findComment = id => c.collection.findWhere({ uid: id });
	c.findCommentInGroup = () => null;
	return c;
}
function comment(uid, text, quote, author, replies) {
	return new Backbone.Model({
		uid, comment: text, quote, username: author, parsedName: author, resolved: false, hide: false,
		replys: (replies || []).map(r => new Backbone.Model({ reply: r[0], username: r[1], parsedName: r[1] })),
	});
}
const visible = c => Array.from(c.collection.filter(m => !m.get('filtered')).map(m => m.get('uid')));

check('controller has the search (setFilterText, isFilteredByText)', () => {
	assert.ok(methods.setFilterText, 'no setFilterText');
	assert.ok(methods.isFilteredByText, 'no isFilteredByText');
});

if (methods.setFilterText && methods.isFilteredByText) {
	const c = makeController();
	c.collection.reset([
		comment('1', 'Check the KEYWORD here', 'some text', 'Alice'),
		comment('2', 'nothing', 'quoted keyword phrase', 'Bob'),
		comment('3', 'plain', 'plain', 'Carol', [['a reply with Keyword', 'Dave']]),
		comment('4', 'other', 'other', 'Erin', [['no match', 'Frank']]),
		comment('5', 'resolved one with keyword', '', 'Gina'),
	]);
	c.collection.get && c.collection.at(4).set('resolved', true);

	check('empty search shows every comment', () => {
		c.setFilterText('');
		c.applyCombinedFilter();
		assert.deepStrictEqual(visible(c), ['1', '2', '3', '4', '5']);
	});
	check('"keyword" finds comment text, quoted text and reply text, any case', () => {
		c.setFilterText('  keyword ');
		assert.deepStrictEqual(visible(c), ['1', '2', '3', '5']);
		assert.ok(c.updates > 0, 'the list was not redrawn');
	});
	check('author names (comment and reply) are searched', () => {
		c.setFilterText('frank');
		assert.deepStrictEqual(visible(c), ['4']);
		c.setFilterText('alice');
		assert.deepStrictEqual(visible(c), ['1']);
	});
	check('the status filter combines with the search', () => {
		c.setFilterText('keyword');
		c.setFilterComments('open');
		assert.deepStrictEqual(visible(c), ['1', '2', '3']);
		c.setFilterComments('all');
	});
	check('a comment changed during a search is checked again', () => {
		c.setFilterText('keyword');
		const reply = text => ({
			asc_getOnlyOfficeTime: () => '', asc_getTime: () => '', asc_getUserId: () => 'u2',
			asc_getUserName: () => 'Zed', asc_getText: () => text, asc_getUserData: () => null,
		});
		const data = {
			asc_getOnlyOfficeTime: () => '', asc_getTime: () => '', asc_getUserId: () => 'u1',
			asc_getUserName: () => 'Alice', asc_getText: () => 'edited, no match', asc_getQuoteText: () => 'q',
			asc_getSolved: () => false, asc_getUserData: () => null, asc_getRepliesCount: () => 1,
			asc_getReply: () => reply('still none'),
		};
		const env = {
			Common: {
				UI: { ExternalUsers: { getImage: () => null, getColor: () => '#000', get: () => {} }, getId: () => 'x' },
				Utils: { getUserInitials: s => s, InternalSettings: { get: () => null } },
				Models: { Reply: Backbone.Model },
			},
			AscCommon: { UserInfoParser: { getParsedName: s => s, getParsedGroups: () => null, canEditComment: () => true, canDeleteComment: () => true, canViewComment: () => true } },
		};
		const fn = new Function('Common', 'AscCommon', '_', 'return (' + method(controllerSrc, 'onApiChangeCommentData') + ');')(env.Common, env.AscCommon, _);
		fn.call(Object.assign(c, { fillUserGroups() {} }), '1', data, true);
		assert.strictEqual(c.collection.at(0).get('filtered'), true, 'the edited comment no longer matches but stays listed');
	});
}

/* wiring in the view, the template and the stylesheet */
const view = read('apps/common/main/lib/view/Comments.js');
const tpl = read('apps/common/main/lib/template/CommentsPanel.template');
const less = read('apps/common/main/resources/less/comments.less');
check('the panel header has the search input', () =>
	assert.ok(/id="comments-search"[\s\S]*?<input[^>]*placeholder="<%=textSearch%>"/.test(tpl)));
check('the view fires comment:filtertext from it and the controller listens', () => {
	assert.ok(/#comments-search input/.test(view) && /fireEvent\('comment:filtertext'/.test(view));
	assert.ok(/'comment:filtertext'\s*:\s*_\.bind\(this\.setFilterText, this\)/.test(controllerSrc));
});
check('the list starts below the taller header', () => {
	const h = /#comments-header\s*\{[^}]*?height:\s*(\d+)px/.exec(less);
	const p = /\.messages-ct\s*\{[^}]*?padding-top:\s*(\d+)px/.exec(less);
	assert.ok(h && p, 'rules not found');
	assert.ok(+h[1] > 45 && h[1] === p[1], `header ${h[1]}px, list offset ${p[1]}px`);
});
check('"Search comments" is in each editor\'s en.json', () => {
	for (const app of ['documenteditor', 'presentationeditor', 'spreadsheeteditor', 'pdfeditor'])
		assert.strictEqual(JSON.parse(read(`apps/${app}/main/locale/en.json`))['Common.Views.Comments.textSearch'], 'Search comments', app);
});

if (failed) {
	console.log(`${failed} check(s) FAILED`);
	process.exit(1);
}
console.log('PASS #322 comments search');
