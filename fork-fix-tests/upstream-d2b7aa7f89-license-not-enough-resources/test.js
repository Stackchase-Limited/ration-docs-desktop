/*
 * Upstream d2b7aa7f89 (ONLYOFFICE bug 81827) - a v10 document server reports
 * licenseType 17 when it runs out of resources and switches editors to
 * view-only. Asc.c_oLicenseResult had no NotEnoughResources, so web-apps
 * (ed424af8e4, backported separately) could not recognise the state and the
 * user's edits were lost without the right warning. Fix: add
 * c_oLicenseResult.NotEnoughResources = 17, also exported by its quoted name
 * like the other values.
 *
 * What runs: common/apiCommon.js inside the WHOLE word engine headless in
 * docbuilder (shared harness ../lib/sdkjs-docbuilder.js). Checked: the value is
 * 17 by dotted and quoted name; the existing values (NotBefore 16) unchanged.
 * With RD_DEPLOY=<sdkjs deploy dir> it also checks that the built
 * word/cell/slide sdk-all-min.js carry the quoted export.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const r = h.run({
	editor: 'word', baseRef: BASE_REF, tag: 'lic17', script: (w, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var L = Asc.c_oLicenseResult;
out('values', [L.NotEnoughResources, L['NotEnoughResources'], L.NotBefore, L.Success]);
builder.CloseFile();
` });
const ck = h.checker();
const v = r.results.get('values');
ck.check('Asc.c_oLicenseResult.NotEnoughResources is 17', !!v && v[0] === 17 && v[1] === 17, JSON.stringify(v));
ck.check('existing values unchanged (NotBefore 16, Success 3)', !!v && v[2] === 16 && v[3] === 3, JSON.stringify(v && v.slice(2)));
if (process.env.RD_DEPLOY && !process.env.BASELINE) {
	for (const ed of ['word', 'cell', 'slide']) {
		const f = path.join(process.env.RD_DEPLOY, ed, 'sdk-all-min.js');
		const t = fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '';
		ck.check(`built ${ed}/sdk-all-min.js exports NotEnoughResources`, /NotEnoughResources\s*:\s*17/.test(t) && /\[['"]NotEnoughResources['"]\]/.test(t), f);
	}
}
ck.finish(r);
