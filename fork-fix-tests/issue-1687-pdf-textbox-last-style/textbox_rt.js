// The REAL PDF-editor text box code from a built word bundle (it carries pdf/), in headless Chromium:
// NewShapeTrack("textRect").getShape as the Insert > Text Box drag ends, CPDFDoc.BlurActiveObject
// leaving a styled text box, and the api option. No document is opened: the PDF api and document are
// the real prototypes on stub instances (viewer/controller stubs record nothing we check).
// node textbox_rt.js <sdkjs tree> <AllFonts.js>  -> JSON
const fs = require('fs');
const path = require('path');
const startServer = require('./server');
const PW = process.env.RD_PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const { chromium } = require(PW);

(async () => {
	const [sdkjsTree, allFonts] = process.argv.slice(2);
	const srv = await startServer({ sdkjsRoots: [path.join(sdkjsTree, 'deploy', 'sdkjs'), sdkjsTree], page: path.join(__dirname, 'page.html'), allFonts });
	const chrome = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
	const browser = await chromium.launch(fs.existsSync(chrome) ? { executablePath: chrome } : {});
	const errors = [];
	try {
		const page = await browser.newPage();
		page.on('pageerror', e => errors.push(String(e && e.stack || e)));
		await page.goto(`http://127.0.0.1:${srv.address().port}/index.html`);
		const r = await page.evaluate(() => {
			AscCommon.History.TurnOff && AscCommon.History.TurnOff();
			const api = Object.create(Asc.PDFEditorApi.prototype);
			const doc = Object.create(AscPDF.CPDFDoc.prototype);
			api.isStartAddShape = true; api.isStartAddAnnot = false;
			api.isPdfEditor = () => true;
			api.getPDFDoc = () => doc;
			const controller = Object.create(AscPDF.CGraphicObjects.prototype);   // real createShape -> CPdfShape
			api.getGraphicController = () => controller;
			// the viewer: only repaint requests reach it here
			const noop = new Proxy({}, { get: (t, k) => (k === 'then' ? undefined : function () {}) });
			api.getDocumentRenderer = () => noop;
			window.Asc.editor = window.editor = api;
			AscCommon.g_oTableId.init(api);
			AscCommon.CollaborativeEditing = new AscPDF.CPDFCollaborativeEditing();   // as the PDF api sets it up
			const hasOption = typeof api.asc_setTextBoxLastStyle === 'function';

			// the stubs BlurActiveObject needs around the drawing it blurs
			let active = null;
			Object.assign(doc, {
				Api: api,
				GetController: () => ({ resetSelection() {}, resetTrackState() {} }),
				GetActiveObject: () => active,
				GetDrawingDocument: () => ({ TargetEnd() {} }),
				SetGlobalHistory() {}, UpdateInterfaceTracks() {}, SetNeedUpdateSearch() {}, Recalculate() {},
				Viewer: { onUpdateOverlay() {}, getPageRotate: () => 0 },
			});
			const draw = () => {      // the Insert > Text Box drag ending: NewShapeTrack -> getShape
				const t = new AscFormat.NewShapeTrack('textRect', 10, 10, AscFormat.GetDefaultTheme(), null, null, null, 0);
				t.track({}, 60, 30);
				const sp = t.getShape(false, null, null);
				sp.IsUseInDocument = () => true; sp.IsDrawing = () => true; sp.OnBlur = () => {};
				sp.GetDocContent = () => sp.txBody.content;
				return sp;
			};
			const describe = (sp) => {
				const c = sp.txBody.content, p = c.Content[0];
				const runs = p.Content.map(r => {
					const pr = r.Pr;
					return [r.IsParaEndRun() ? 'end' : 'run', pr.FontSize || null, pr.Bold || null, pr.RFonts && pr.RFonts.Ascii ? pr.RFonts.Ascii.Name : null];
				});
				const fill = sp.spPr.Fill && sp.spPr.Fill.fill;
				return {
					fill: fill ? (fill.type === Asc.c_oAscFill.FILL_TYPE_SOLID ? 'solid ' + [fill.color.color.RGBA.R, fill.color.color.RGBA.G, fill.color.color.RGBA.B].join(',') : fill.type === Asc.c_oAscFill.FILL_TYPE_NOFILL ? 'none' : 'type' + fill.type) : null,
					ln: sp.spPr.ln ? sp.spPr.ln.w : null,
					shadow: !!(sp.spPr.effectProps && sp.spPr.effectProps.EffectLst && sp.spPr.effectProps.EffectLst.outerShdw),
					paraEndPr: [p.TextPr.Value.FontSize || null, p.TextPr.Value.Bold || null],
					jc: p.Pr.Jc === undefined ? null : p.Pr.Jc,
					runs,
				};
			};
			const style = (sp) => {   // what the user does to the first box: shape and text formatting
				sp.spPr.setFill(AscFormat.CreateSolidFillRGB(255, 255, 0));
				const ln = new AscFormat.CLn(); ln.setW(25400); ln.setFill(AscFormat.CreateSolidFillRGB(0, 0, 255)); sp.spPr.setLn(ln);
				const ef = new AscFormat.CEffectProperties(); ef.EffectLst = new AscFormat.CEffectLst(); ef.EffectLst.outerShdw = new AscFormat.COuterShdw();
				sp.spPr.setEffectPr(ef);
				const p = sp.txBody.content.Content[0], run = p.Content[0];
				const pr = new AscCommonWord.CTextPr(); pr.FontSize = 24; pr.Bold = true; pr.RFonts.SetAll('Courier New', -1);
				run.AddText('Hello');
				run.Set_Pr(pr);
				p.Set_Align(AscCommon.align_Center);
			};
			const out = { hasOption };
			const run = (opt) => {
				hasOption && api.asc_setTextBoxLastStyle(opt);
				doc.lastTextBoxStyle = undefined;
				const a = draw();
				const first = describe(a);
				style(a);
				active = a;
				doc.BlurActiveObject();         // leaving the first box (e.g. Insert > Text Box again)
				active = null;
				const remembered = !!doc.lastTextBoxStyle;
				const b = draw();
				return { first, remembered, second: describe(b) };
			};
			out.off = run(false);
			out.on = run(true);
			return out;
		});
		console.log(JSON.stringify(Object.assign(r, { errors: errors.slice(0, 3) })));
	} finally {
		await browser.close();
		srv.close();
	}
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });
