// #2550 web-apps part: runs the REAL presentation editor define.js (Common.define.effectData) and the REAL
// Animation controller methods onFocusObject + lockMediaEffects (cut out by brace matching) against stubs.
// stdin: {"define": <define.js source>, "ctrl": <controller/Animation.js source>}; prints one JSON line.
const vm = require('vm');

const src = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const AscFormat = new Proxy({ PRESET_CLASS_EMPH: 0, PRESET_CLASS_ENTR: 1, PRESET_CLASS_EXIT: 2, PRESET_CLASS_MEDIACALL: 3, PRESET_CLASS_PATH: 4,
	MEDIACALL_PLAY: 1, MEDIACALL_PAUSE: 2, MEDIACALL_STOP: 3 }, {
	get(t, k) { return (k in t) ? t[k] : 'const:' + String(k); },
});
const ctx = { AscFormat, _: { extend: Object.assign }, define(deps, fn) { (typeof deps === 'function' ? deps : fn)(); } };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(src.define, ctx);
const data = ctx.Common.define.effectData;
const group = (data.getEffectGroupData().find(g => g.id === 'menu-effect-group-media') || {}).value;
const pick = arr => arr.filter(e => e.group === 'menu-effect-group-media').map(e => [e.value, e.displayValue]);
const res = { group: group === undefined ? null : group, effects: pick(data.getEffectData()), full: pick(data.getEffectFullData()) };

// the methods of the controller's object literal
function method(source, name) {
	const m = new RegExp('\\n\\s*' + name + '\\s*:\\s*function\\s*\\(([^)]*)\\)\\s*\\{').exec(source);
	if (!m) return null;
	let i = m.index + m[0].length, depth = 1;
	for (; i < source.length && depth; i++) {
		if (source[i] === '{') depth++;
		else if (source[i] === '}') depth--;
	}
	return new Function(...m[1].split(',').map(s => s.trim()).filter(Boolean), source.slice(m.index + m[0].length, i - 1));
}
const onFocusObject = method(src.ctrl, 'onFocusObject');
const lockMediaEffects = method(src.ctrl, 'lockMediaEffects');
function locked(mediaSelected) {
	if (!onFocusObject || !lockMediaEffects) return null;
	const items = [{ group: 'menu-effect-group-media', disabled: false }, { group: 'menu-effect-group-entrance', disabled: false }];
	const store = { each(f) { items.forEach(it => f({ get: k => it[k], set: (k, v) => { it[k] = v; } })); } };
	const ctrl = {
		_state: {},
		api: { asc_getAnimatedObjectsStack: () => [], asc_getMediaSettings: () => (mediaSelected ? { Mute: false } : null) },
		setSettings() {},
		lockMediaEffects,
	};
	global.Asc = { c_oAscTypeSelectElement: { Animation: 1, Slide: 2, Shape: 3, Table: 4 } };
	onFocusObject.call(ctrl, []);
	ctrl.lockMediaEffects(store);
	return items[1].disabled ? 'entrance locked too' : items[0].disabled;
}
res.lockedNoMedia = locked(false);
res.lockedMedia = locked(true);
console.log(JSON.stringify(res));
