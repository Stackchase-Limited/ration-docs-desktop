// Static server for the full web-apps editor (source tree, dev mode) + a built sdkjs (deploy/sdkjs).
//   /web-apps/*  -> opts.webapps (the documenteditor/... main/index.html is served with the sdk loaded
//                   from the built bundle instead of sdkjs/develop scripts; api/documents/index.html is
//                   the desktop host page index.html.desktop)
//   (files the source tree lacks - resources/css/app.css, sprites - come from opts.webappsDeploy)
//   /sdkjs/*     -> opts.sdkjs (deploy/sdkjs); /sdkjs/common/AllFonts.js -> opts.allFonts
//   /Editor.bin  -> opts.editorBin; /font?p=<path> -> a font file (paths come from AllFonts.js)
const http = require('http'), fs = require('fs'), path = require('path'), url = require('url');
module.exports = function start(opts) {
	const types = { '.js': 'application/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.html': 'text/html',
		'.css': 'text/css', '.less': 'text/plain', '.svg': 'image/svg+xml', '.png': 'image/png', '.bin': 'application/octet-stream' };
	const srv = http.createServer((req, res) => {
		const u = url.parse(req.url, true);
		const p = decodeURIComponent(u.pathname);
		let file = null, body = null;
		if (p === '/Editor.bin') file = opts.editorBin;
		else if (p === '/font') file = u.query.p;
		else if (p === '/sdkjs/common/AllFonts.js') file = opts.allFonts;
		else if (p.startsWith('/sdkjs/')) file = path.join(opts.sdkjs, p.slice(7));
		else if (p === '/web-apps/apps/api/documents/index.html') file = path.join(opts.webapps, 'apps/api/documents/index.html.desktop');
		else if (p.startsWith('/web-apps/')) {
			file = path.join(opts.webapps, p.slice(10));
			if (/\/apps\/(document|spreadsheet|presentation)editor\/main\/index\.html$/.test(p) && fs.existsSync(file)) {
				const ed = { document: 'word', spreadsheet: 'cell', presentation: 'slide' }[p.match(/apps\/(\w+?)editor/)[1]];
				body = fs.readFileSync(file, 'utf8').replace(/<script[^>]*src="[^"]*sdkjs\/develop\/sdkjs\/\w+\/scripts\.js"><\/script>/,
					`<script>window.sdk_scripts = ['../../../../sdkjs/common/AllFonts.js', '../../../../sdkjs/${ed}/sdk-all-min.js'];</script>`)
					// styles: the built app.css of a web-apps deploy (the less sources need generated sprites)
					.replace(/<link rel="stylesheet\/less"[^>]*>/, '<link rel="stylesheet" type="text/css" href="resources/css/app.css" />')
					.replace(/<script[^>]*src="[^"]*vendor\/less\/dist\/less\.js"[^>]*><\/script>/, '');
			}
		}
		if (body === null && p.startsWith('/web-apps/') && opts.webappsDeploy && !(file && fs.existsSync(file)))
			file = path.join(opts.webappsDeploy, p.slice(10));
		if (body === null && (!file || !fs.existsSync(file) || !fs.statSync(file).isFile())) { res.writeHead(404); res.end(); return; }
		res.writeHead(200, { 'Content-Type': types[path.extname(body !== null ? p : (p.endsWith('.html') ? p : file))] || 'application/octet-stream', 'Cache-Control': 'no-store' });
		if (body !== null) res.end(body);
		else fs.createReadStream(file).pipe(res);
	});
	return new Promise(r => srv.listen(0, '127.0.0.1', () => r(srv)));
};
