/*
 * #736 "Dark page background for dark mode" - with a dark interface theme the
 * editors flash a bright white page while a document opens.
 *
 * Checked first on our 9.4 build (the payload's built index.html, headless
 * Chromium, desktop theme variables stubbed): the loading skeleton is already
 * dark (#222) for every dark theme in all editors (index.html.deploy styles
 * ".theme-type-dark .loadmask"), and its placeholder page is white only when
 * the document itself will be white ("document dark mode" off). Two gaps were
 * left, both with document dark mode ON:
 *  - PDF editor: its skeleton had no content-theme-dark rule, so a white A4
 *    page showed until the viewer drew the #3a3a3a dark pages (sdkjs
 *    pdf/src/viewer.js) - the white flash of the report.
 *  - Document editor: the skeleton page was a fixed #3a3a3a while the page
 *    itself now follows the theme's canvas-dark-content-background (#2112), so
 *    a black theme showed a grey page first, then black.
 * Now the pdf skeleton gets the dark page in document dark mode, and the
 * document skeleton uses var(--canvas-dark-content-background, #3a3a3a).
 *
 * This loads the REAL apps/{documenteditor,pdfeditor}/main/index.html.deploy
 * (skeleton markup and styles; its external scripts removed) in headless
 * Chromium with the REAL themeinit.js run first as the desktop does
 * (window.uitheme = the theme, with a local theme's colours), sets the body
 * classes htmlutils.js sets, and reads the computed colours of the skeleton.
 *
 * NOT claimed: timing of the real app (GUI); the window/CEF background before
 * the page loads (desktop-sdk sets it from the theme; #2528 covers tab
 * switches); spreadsheet/presentation skeletons are unchanged.
 *
 *   node fork-fix-tests/issue-0736-dark-loading-page-test.js
 *   RD_REPO=<web-apps checkout> (default ../web-apps)   BASELINE=1 reads BASE_REF and must fail.
 *   PLAYWRIGHT, RD_CHROME as in issue-1664-paste-webp-test.js.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
const BASE_REF = process.env.BASE_REF || '0a9d55094d^';
const BASELINE = !!process.env.BASELINE;
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

(async () => {
	const { chromium } = require(PLAYWRIGHT);
	const browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
	const themeinit = src('apps/common/main/lib/util/themeinit.js');

	async function skeleton(editor, theme, contentDark) {
		const html = src(`apps/${editor}/main/index.html.deploy`)
			.replace(/<script\b[^>]*\bsrc=[^>]*>\s*<\/script>/g, '')
			.replace('</head>', '<script>window.uitheme = ' + JSON.stringify(theme) + ';<\/script><script>' + themeinit.replace(/<\/script>/g, '<\\/script>') + '<\/script></head>');
		const page = await browser.newPage();
		page.on('pageerror', () => {});
		await page.setContent(html, { waitUntil: 'domcontentloaded' });
		const r = await page.evaluate(([id, type, cd]) => {
			document.body.classList.add(id);
			type == 'dark' && document.body.classList.add('theme-type-dark');
			cd && document.body.classList.add('content-theme-dark');
			const m = document.getElementById('loading-mask'), ph = m.querySelector('.placeholder');
			return { mask: getComputedStyle(m).backgroundColor, page: getComputedStyle(ph).backgroundColor };
		}, [theme.id, theme.type, contentDark]);
		await page.close();
		return r;
	}

	const DARK = 'rgb(58, 58, 58)', WHITE = 'rgb(255, 255, 255)', BLACK = 'rgb(0, 0, 0)', MASK = 'rgb(34, 34, 34)';
	const builtin = { id: 'theme-dark', type: 'dark' };
	const black = { id: 'theme-id-black', type: 'dark', colors: { 'canvas-dark-content-background': '#000000' } };

	for (const ed of ['documenteditor', 'pdfeditor']) {
		let r = await skeleton(ed, builtin, false);
		check(r.mask === MASK && r.page === WHITE, `${ed}, dark theme, document dark mode off: dark skeleton, white page (unchanged) [${r.mask} / ${r.page}]`);
		r = await skeleton(ed, builtin, true);
		check(r.mask === MASK && r.page === DARK, `${ed}, dark theme, document dark mode on: skeleton page #3a3a3a, no white page [${r.page}]`);
		r = await skeleton(ed, { id: 'theme-white', type: 'light' }, false);
		check(r.page === WHITE && r.mask !== MASK, `${ed}, light theme: light skeleton, white page (unchanged) [${r.mask} / ${r.page}]`);
	}
	const r = await skeleton('documenteditor', black, true);
	check(r.page === BLACK, `documenteditor, theme with canvas-dark-content-background #000000, dark mode on: skeleton page black [${r.page}]`);

	await browser.close();
	console.log(failed ? `FAILED (${failed})` : 'PASS');
	process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
