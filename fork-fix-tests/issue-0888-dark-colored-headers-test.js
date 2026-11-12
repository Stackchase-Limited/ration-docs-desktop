/*
 * #888 "Coloured Dark Mode Toolbars" - the blue/green/orange/red header that
 * tells the editors apart is only in light themes; every built-in dark theme
 * paints it grey. Asked for: a dark option with the coloured headers.
 *
 * Themes already take the header colours from the theme file; nothing offered a
 * dark one with coloured headers. Now web-apps ships
 * apps/common/main/resources/themes/dark-colored-headers-theme-dark.json.example:
 * a "dark" theme with the light theme's header colours (opt-in: added by the
 * user, nothing changes otherwise).
 *
 * This reads the REAL example file, checks it is a dark theme whose header
 * colours are the light theme's (colors-table.less :root) and not the dark
 * table's (colors-table-dark.less), then runs the REAL
 * apps/common/main/lib/util/themeinit.js in a vm the way the desktop starts an
 * editor (desktopinit.js puts the local theme's colours in window.uitheme) with
 * a stub document, and checks themeinit sets every header colour on <html>
 * before first paint and injects the theme's colours for body.<id>.
 *
 * Native side (desktop-apps win-linux/src/cthemes.cpp): a theme file's colours
 * reach the native tabs through map_alias_names; brand-draw (Visio tab) was
 * aliased to "toolbar-header-draw", a token web-apps does not have (it is
 * toolbar-header-visio), so the Visio tab ignored the theme. The test reads the
 * REAL map_alias_names and checks every brand-* alias names one of the header
 * tokens themeinit applies.
 *
 * NOT claimed: the look (needs a GUI check); macOS cannot load a custom theme
 * (its tab colours are fixed per built-in theme in ASCThemesController).
 *
 *   node fork-fix-tests/issue-0888-dark-colored-headers-test.js
 *   RD_REPO=<web-apps checkout> (default ../web-apps)   RD_DESKTOP=<desktop-apps> (default ../desktop-apps)
 *   BASELINE=1 reads BASE_REF (web-apps) / DESKTOP_BASE_REF and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
const BASE_REF = process.env.BASE_REF || '23698b98ea^';
const DESKTOP = process.env.RD_DESKTOP || path.resolve(__dirname, '..', 'desktop-apps');
const DESKTOP_BASE_REF = process.env.DESKTOP_BASE_REF || '18fd77fc1^';
const BASELINE = !!process.env.BASELINE;
const EXAMPLE = 'apps/common/main/resources/themes/dark-colored-headers-theme-dark.json.example';

function src(rel, repo = REPO, ref = BASE_REF) {
	try {
		return BASELINE
			? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
			: fs.readFileSync(path.join(repo, rel), 'utf8');
	} catch (e) { return null; }
}
function table(text, selector) {
	const at = text.indexOf(selector);
	const body = text.slice(text.indexOf('{', at), text.length);
	const out = {};
	for (const m of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) if (!(m[1] in out)) out[m[1]] = m[2].trim();
	return out;
}

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

const HEADERS = ['document', 'spreadsheet', 'presentation', 'pdf', 'visio'].map(t => 'toolbar-header-' + t);
const text = src(EXAMPLE);
check(text !== null, 'a dark theme with coloured headers is shipped (' + path.basename(EXAMPLE) + ')');
if (text !== null) {
	const theme = JSON.parse(text);
	const light = table(src('apps/common/main/resources/less/colors-table.less'), ':root');
	const dark = table(src('apps/common/main/resources/less/colors-table-dark.less'), '.theme-dark');
	check(theme.type === 'dark' && /^[\w-]+$/.test(theme.id) && !!theme.name, 'it is a "dark" theme with a valid id and name');
	for (const h of HEADERS)
		check(theme.colors[h] && theme.colors[h].toLowerCase() === light[h].toLowerCase() && theme.colors[h].toLowerCase() !== dark[h].toLowerCase(),
			`${h} is the light theme's ${light[h]}, not the dark ${dark[h]}`);

	// run the real themeinit.js as an editor page does in the desktop app
	const props = {}, styles = [];
	const document = {
		documentElement: { style: { setProperty: (k, v) => { props[k] = v; } } },
		getElementById: () => null,
		createElement: () => ({}),
		getElementsByTagName: () => [{ appendChild: (s) => styles.push(s.innerHTML) }],
	};
	const window = { uitheme: { id: theme.id, type: theme.type, colors: theme.colors }, localStorage: { getItem: () => null, removeItem() {} }, matchMedia: () => ({ matches: false }) };
	vm.runInNewContext(src('apps/common/main/lib/util/themeinit.js'), { window, document, console });
	for (const h of HEADERS) check(props['--' + h] === theme.colors[h], `themeinit sets --${h} = ${theme.colors[h]} on <html>`);
	check(styles.some(s => s.includes(':root body.' + theme.id + '{') && s.includes('--toolbar-header-spreadsheet:' + theme.colors['toolbar-header-spreadsheet'])),
		'themeinit injects the theme colours for body.' + theme.id);
}
const cthemes = src('win-linux/src/cthemes.cpp', DESKTOP, DESKTOP_BASE_REF);
const aliases = [...cthemes.matchAll(/\{"(brand-[\w-]+)",\s*"([\w-]+)"\}/g)];
check(aliases.length >= 5, 'cthemes.cpp has the brand-* aliases');
for (const [, native, token] of aliases)
	check(HEADERS.includes(token), `native ${native} reads the theme's ${token}`);

console.log(failed ? `FAILED (${failed})` : 'PASS');
process.exit(failed ? 1 : 0);
