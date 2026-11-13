// Tiny static server: /sdkjs/* from the sdkjs tree (deploy first), /AllFonts.js, the page.
const http = require('http'), fs = require('fs'), path = require('path'), url = require('url');
module.exports = function start(opts) {
	const types = { '.js': 'application/javascript', '.wasm': 'application/wasm', '.html': 'text/html' };
	const srv = http.createServer((req, res) => {
		const u = url.parse(req.url, true);
		let file = null;
		if (u.pathname === '/index.html') file = opts.page;
		else if (u.pathname === '/AllFonts.js') file = opts.allFonts;
		else if (u.pathname.startsWith('/sdkjs/')) {
			const rel = decodeURIComponent(u.pathname.slice(7));
			for (const r of opts.sdkjsRoots) { const p = path.join(r, rel); if (fs.existsSync(p) && fs.statSync(p).isFile()) { file = p; break; } }
		}
		if (!file || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
		res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
		fs.createReadStream(file).pipe(res);
	});
	return new Promise(r => srv.listen(0, '127.0.0.1', () => r(srv)));
};
