// Tiny static server for the headless sdkjs harness.
const http = require('http'), fs = require('fs'), path = require('path'), url = require('url');
module.exports = function start(opts) {
	const roots = opts.sdkjsRoots; // array of dirs tried in order for /sdkjs/*
	const types = { '.js': 'application/javascript', '.wasm': 'application/wasm', '.html': 'text/html', '.bin': 'application/octet-stream' };
	const srv = http.createServer((req, res) => {
		const u = url.parse(req.url, true);
		let file = null;
		if (u.pathname.endsWith('/main/index.html')) file = opts.page;
		else if (u.pathname === '/AllFonts.js') file = opts.allFonts;
		else if (u.pathname === '/Editor.bin') file = opts.editorBin;
		else if (u.pathname === '/font') file = u.query.p;
		else if (u.pathname.startsWith('/sdkjs/')) {
			const rel = decodeURIComponent(u.pathname.slice(7));
			for (const r of roots) { const p = path.join(r, rel); if (fs.existsSync(p) && fs.statSync(p).isFile()) { file = p; break; } }
		}
		if (!file || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
		res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
		fs.createReadStream(file).pipe(res);
	});
	return new Promise(r => srv.listen(0, '127.0.0.1', () => r(srv)));
};
