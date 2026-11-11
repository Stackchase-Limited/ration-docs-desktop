/*
 * #1664 (security follow-up) - the plugin store inserted remote data as HTML.
 *
 * Bug: the plugin store (onlyoffice.github.io store/index.html and
 * store/plugin-card.html, shipped as editors/sdkjs-plugins/{AA2EA9B6-...}/store/)
 * is a file:// page under the app and so gets the desktop bridge. It built HTML
 * strings from what it fetches over the network - the store's plugin list and
 * each plugin's config.json (name, description, publisher "offered", guid,
 * background, rating, icon URL) - and assigned them with innerHTML
 * (marketplace/ui.js _buildPluginPlateHtml/_makeActionButtons/_makeRatingElements,
 * card/plugin-card-ui.js makeRatingElements); a plugin's CHANGELOG.md went through
 * marked (which passes raw HTML through) into innerHTML (card/plugin-card.js
 * _loadAndShowChangelog); config.discussionUrl became a link href unchecked.
 * Whoever controls that remote content could run script next to the bridge.
 *
 * Fix (onlyoffice.github.io): Utils.escapeHtml on every remote value in those
 * HTML strings (the onclick guid as an escaped JSON literal); the CHANGELOG is
 * rebuilt by Utils.sanitizeHtml (inert <template>, allowlisted formatting tags
 * and attributes, http(s)/mailto links only); link hrefs only when http(s).
 *
 * This test loads the REAL store scripts (and the real marked) into the REAL
 * index.html / plugin-card.html markup in headless Chromium as file:// pages,
 * with only the network fetcher (DataFetcher) and the click handlers stubbed,
 * feeds hostile store data through the real functions, and checks that nothing
 * runs (onerror handlers, an onclick break-out on click, a javascript: link on
 * click) while the text still shows and the Install button still gets the exact
 * guid. It also renders every CHANGELOG.md in sdkjs-plugins/content through the
 * real code path and checks the same text and the same element structure as
 * marked's raw output (legit CHANGELOGs keep their formatting).
 *
 * NOT claimed: the GUI store was not opened in the app (needs a GUI check: the
 * list, a card and its Changelog tab); messages between the store and the
 * Plugin Manager wrapper (store/plugin) are not origin-checked - nothing remote
 * can reach them now that the store runs no remote script, but that was not
 * changed; plugins the user installs are trusted code by design.
 *
 * Env: RD_REPO   onlyoffice.github.io checkout (default ../onlyoffice.github.io)
 *      BASELINE=1 reads the store at BASE_REF via git; must FAIL.
 *      PLAYWRIGHT, RD_CHROME as in issue-1664-paste-webp-test.js.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const REPO = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'onlyoffice.github.io'));
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '683027f^';
const BASELINE = !!process.env.BASELINE;
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';

function read(rel) {
	if (BASELINE)
		return execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 });
	return fs.readFileSync(path.join(REPO, rel), 'utf8');
}

const STORE_SCRIPTS = ['scripts/shared/polyfill.js', 'scripts/shared/checkbox.js', 'scripts/marketplace/storage.js',
	'scripts/marketplace/ui.js', 'scripts/shared/utils.js', 'scripts/marketplace/scale.js', 'scripts/marketplace/plugin-icons.js'];
const CARD_SCRIPTS = ['scripts/shared/polyfill.js', 'scripts/shared/utils.js', 'vendor/marked/marked.min.js',
	'scripts/card/plugin-card-ui.js', 'scripts/card/plugin-card.js'];
// stubs: the click handlers code.js defines, and the network (DataFetcher) - nothing else
const STORE_STUBS = 'window.__pwned=[];window.__clicked=[];' +
	['onClickInstall', 'onClickDownload', 'onClickUpdate', 'onClickRemove'].map((f) => `function ${f}(g){__clicked.push(g)}`).join(';');
const CARD_STUBS = 'window.__pwned=[];window.__changelog="";window.PerfectScrollbar=function(){this.update=function(){}};' +
		// a CHANGELOG.md request answers window.__changelog; anything else (translations) fails, as offline
	'window.DataFetcher={makeRequestWithWaitConnectionStrategy:function(u){var log=/CHANGELOG\\.md$/.test(u);' +
	'var r={onSuccess:function(f){if(log)setTimeout(function(){f(window.__changelog)});return r},onFailure:function(f){if(!log)setTimeout(function(){f()});return r}};return r},' +
	'getRating:function(){return Promise.resolve(null)},makeRequest:function(){return Promise.reject(new Error("offline"))}};';

// the real page markup, its own <script>/<link> tags replaced by the real scripts above
function page(dir, html, scripts, stubs) {
	for (const s of scripts) {
		fs.mkdirSync(path.join(dir, path.dirname(s)), { recursive: true });
		fs.writeFileSync(path.join(dir, s), read('store/' + s));
	}
	html = html.replace(/<script\b[\s\S]*?<\/script>/gi, '').replace(/<link\b[^>]*>/gi, '');
	const inject = `<script>${stubs}</script>` + scripts.map((s) => `<script src="${s}"></script>`).join('');
	assert.ok(html.includes('</body>'), 'page has no </body>');
	return html.replace('</body>', inject + '</body>');
}

const X = (tag) => `<img src=x onerror="__pwned.push('${tag}')">`;
const HOSTILE_CHANGELOG = '# Change Log\n\n## 1.0.1\n\n' +
	'* fixed **bold** `code` [web](https://example.com/) [js](javascript:__pwned.push(\'cl-jslink\'))\n' +
	X('cl-img') + '\n<script>__pwned.push(\'cl-script\')</script>\n' +
	'<svg><animate onbegin="__pwned.push(\'cl-svg\')" attributeName="x" dur="1s"/></svg>\n' +
	'<iframe srcdoc="<script>parent.__pwned.push(\'cl-iframe\')</script>"></iframe>\n' +
	'<a href="  JaVaScRiPt:__pwned.push(\'cl-rawlink\')">raw</a> <details open ontoggle="__pwned.push(\'cl-toggle\')">d</details>\n\n' +
	'## 1.0.0\n\n* first';

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + ': ' + e.message); }
}

(async () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rd-1664-store-'));
	fs.writeFileSync(path.join(tmp, '__store.html'), page(tmp, read('store/index.html'), STORE_SCRIPTS, STORE_STUBS));
	fs.writeFileSync(path.join(tmp, '__card.html'), page(tmp, read('store/plugin-card.html'), CARD_SCRIPTS, CARD_STUBS));
	const changelogs = fs.readdirSync(path.join(REPO, 'sdkjs-plugins/content'))
		.map((p) => path.join(REPO, 'sdkjs-plugins/content', p, 'CHANGELOG.md')).filter((f) => fs.existsSync(f))
		.map((f) => [path.basename(path.dirname(f)), fs.readFileSync(f, 'utf8')]);

	const { chromium } = require(PLAYWRIGHT);
	const browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
	try {
		// --- the store list: a plugin plate built from a hostile config.json
		const store = await browser.newPage();
		const storeErrors = [];
		store.on('pageerror', (e) => storeErrors.push(e.message));
		await store.goto('file://' + path.join(tmp, '__store.html'));
		const plate = await store.evaluate(() => {
			const X = (tag) => `<img src=x onerror="__pwned.push('${tag}')">`;
			const guid = "asc.{0000-evil}');__pwned.push('guid-onclick');//\"><img src=x onerror=__pwned.push('guid-attr')>";
			const cfg = {
				guid: guid, name: X('name') + 'Evil & Co', offered: X('offered'),
				rating: { percent: 50, average: X('rating-average'), total: X('rating-total') },
				variations: [{ description: X('description'),
					store: { background: { light: 'red"><img src=x onerror="__pwned.push(\'background\')">', dark: 'red' } } }]
			};
			const el = UI.createPluginPlate(guid, false, '#fff', { config: cfg, bNeedInstallButton: true });
			UI.addPlugin(guid, el);
			const button = el.querySelector('.management button');
			if (button) button.click();
			UI.showRating({ guid: guid, rating: cfg.rating });
			return { guid: guid, clicked: window.__clicked.slice(), text: el.textContent,
				handlers: el.querySelectorAll('[onerror]').length };
		});
		await store.waitForTimeout(300);
		const storePwned = await store.evaluate(() => window.__pwned.slice());
		check('store: no script from hostile config.json ran in the plugin list', () => {
			assert.deepStrictEqual(storeErrors, [], 'page errors: ' + storeErrors.join('; '));
			assert.deepStrictEqual(storePwned, [], 'ran: ' + storePwned.join(', '));
			assert.strictEqual(plate.handlers, 0, 'elements with onerror in the plate');
		});
		check('store: the Install button still passes the exact guid, names show as text', () => {
			assert.deepStrictEqual(plate.clicked, [plate.guid]);
			assert.ok(plate.text.includes("<img src=x onerror=\"__pwned.push('name')\">Evil & Co"), 'name not shown as text');
		});

		// --- the plugin card: rating, links and the CHANGELOG tab
		const card = await browser.newPage();
		const cardErrors = [];
		card.on('pageerror', (e) => cardErrors.push(e.message));
		await card.goto('file://' + path.join(tmp, '__card.html'));
		await card.evaluate((log) => {
			const X = (tag) => `<img src=x onerror="__pwned.push('${tag}')">`;
			window.__changelog = log;
			const plugin = { guid: 'asc.{0000-card}', name: 'Card', baseUrl: 'https://example.invalid/sdkjs-plugins/content/card/',
				discussionUrl: "javascript:__pwned.push('discussion-link')",
				rating: { percent: 70, average: X('card-average'), total: X('card-total') },
				variations: [{ description: 'd' }] };
			PluginCard.init({ type: 'showPluginCard', pluginName: 'Card', pluginVersion: 1000004, pluginDescription: 'd',
				OOMarketplaceUrl: 'https://example.invalid/sdkjs-plugins/content/', OOIO: 'https://github.com/x/',
				ioUrl: 'https://example.invalid/', releaseUrl: '', plugin: plugin, iconBackground: '#fff',
				iconSrc: { src: 'x.png', srcset: '' }, isLocal: false, editorVersion: 9004000, bHasUpdate: false,
				bActionDisabled: false, removed: false, canRemoved: false, independentMode: false, translate: {} });
		}, HOSTILE_CHANGELOG);
		await card.waitForTimeout(500);
		const clicked = await card.evaluate(() => {
			// click every link that is not a web link (javascript: runs on click)
			const out = [];
			document.querySelectorAll('a[href]').forEach((a) => {
				const href = a.getAttribute('href') || '';
				if (/^\s*(https?:|mailto:|$)/i.test(href)) return;
				out.push(href);
				a.removeAttribute('target');
				a.click();
			});
			const toggles = document.querySelectorAll('#div_changelog_preview details');
			toggles.forEach((d) => { d.open = !d.open; });
			return out;
		});
		await card.waitForTimeout(500);
		const cardState = await card.evaluate(() => ({
			pwned: window.__pwned.slice(),
			changelog: document.getElementById('div_changelog_preview').innerHTML,
			stars: document.getElementById('stars_colored').textContent
		}));
		check('card: no script from a hostile CHANGELOG, rating or discussionUrl ran', () => {
			assert.deepStrictEqual(cardErrors, [], 'page errors: ' + cardErrors.join('; '));
			assert.deepStrictEqual(cardState.pwned, [], 'ran: ' + cardState.pwned.join(', '));
			assert.deepStrictEqual(clicked, [], 'non-web links present: ' + clicked.join(', '));
		});
		check('card: the hostile CHANGELOG keeps its formatting and web link', () => {
			assert.ok(/<strong>bold<\/strong>/.test(cardState.changelog), 'bold lost');
			assert.ok(/<code>code<\/code>/.test(cardState.changelog), 'code lost');
			assert.ok(/<a href="https:\/\/example\.com\/"[^>]*>web<\/a>/.test(cardState.changelog), 'web link lost');
			assert.ok(/<h2[^>]*>1\.0\.1<\/h2>/.test(cardState.changelog), 'heading lost');
		});

		// --- every real CHANGELOG.md renders with the same text and structure as marked's own output
		const diffs = await card.evaluate(async (logs) => {
			const shape = (root) => {
				const out = [];
				(function walk(n) {
					for (let c = n.firstChild; c; c = c.nextSibling) {
						if (c.nodeType === 3) out.push('#' + c.nodeValue);
						else if (c.nodeType === 1) { out.push('<' + c.nodeName + (c.nodeName === 'A' ? ' ' + c.getAttribute('href') : '') + (c.nodeName === 'IMG' ? ' ' + c.getAttribute('src') : '')); walk(c); out.push('>'); }
					}
				})(root);
				return out.join('\n');
			};
			const res = [];
			for (const [name, text] of logs) {
				const expected = document.createElement('template');
				expected.innerHTML = Utils.makeChangeLogHtml(text);
				window.__changelog = text;
				PluginCard._loadAndShowChangelog('https://example.invalid/' + name + '/');
				await new Promise((r) => setTimeout(r, 0));
				const got = shape(document.getElementById('div_changelog_preview'));
				if (got !== shape(expected.content)) res.push(name);
			}
			return res;
		}, changelogs);
		check(`real CHANGELOGs (${changelogs.length}) keep their text and formatting`, () => {
			assert.ok(changelogs.length > 20, 'no CHANGELOGs found under sdkjs-plugins/content');
			assert.deepStrictEqual(diffs, []);
		});
	} finally {
		await browser.close();
		fs.rmSync(tmp, { recursive: true, force: true });
	}
	console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed');
	process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
