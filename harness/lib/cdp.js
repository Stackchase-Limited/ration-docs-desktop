'use strict';
/*
 * Minimal Chrome DevTools Protocol client for driving the Ration Docs desktop
 * editor. No dependencies: Node 20 needs --experimental-websocket, Node 22+ has
 * WebSocket built in.
 */
const http = require('http');

function getJSON(port, path) {
	return new Promise((resolve, reject) => {
		const req = http.get({host: '127.0.0.1', port: port, path: path}, (res) => {
			let body = '';
			res.on('data', (c) => { body += c; });
			res.on('end', () => {
				try {
					resolve(JSON.parse(body));
				} catch (e) {
					reject(new Error('unparseable CDP reply: ' + body.slice(0, 200)));
				}
			});
		});
		req.on('error', reject);
		req.setTimeout(4000, () => req.destroy(new Error('CDP on port ' + port + ' did not answer')));
	});
}

async function listPages(port) {
	const all = await getJSON(port, '/json');
	return all.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
}

// The editor page appears a moment after the window does, so poll.
async function waitForPage(port, match, timeoutMs) {
	const deadline = Date.now() + (timeoutMs || 60000);
	let last = 'no page target yet';
	while (Date.now() < deadline) {
		try {
			const pages = await listPages(port);
			const hit = match
				? pages.find((p) => (p.url || '').indexOf(match) !== -1 || (p.title || '').indexOf(match) !== -1)
				: pages[0];
			if (hit) return hit;
			if (pages.length) last = 'pages open but none match "' + match + '": ' + pages.map((p) => p.url).join(', ');
		} catch (e) {
			last = e.message;
		}
		await new Promise((r) => setTimeout(r, 500));
	}
	throw new Error('timed out waiting for a CDP page target (' + last + ')');
}

class CDP {
	constructor(ws) {
		this.ws = ws;
		this.nextId = 1;
		this.pending = new Map();
		this.handlers = new Map();
		ws.onmessage = (ev) => {
			let msg;
			try { msg = JSON.parse(ev.data); } catch (e) { return; }
			if (msg.id !== undefined && this.pending.has(msg.id)) {
				const p = this.pending.get(msg.id);
				this.pending.delete(msg.id);
				if (msg.error) p.reject(new Error(p.method + ' failed: ' + msg.error.message));
				else p.resolve(msg.result);
				return;
			}
			const hs = this.handlers.get(msg.method);
			if (hs) hs.forEach((h) => { try { h(msg.params); } catch (e) { console.error(e); } });
		};
	}

	static async connect(target) {
		if (typeof WebSocket === 'undefined') {
			throw new Error('no WebSocket in this Node: rerun with --experimental-websocket, or use Node 22+');
		}
		const ws = new WebSocket(target.webSocketDebuggerUrl);
		await new Promise((resolve, reject) => {
			ws.onopen = resolve;
			ws.onerror = () => reject(new Error('could not open ' + target.webSocketDebuggerUrl));
		});
		return new CDP(ws);
	}

	send(method, params) {
		const id = this.nextId++;
		const promise = new Promise((resolve, reject) => {
			this.pending.set(id, {resolve: resolve, reject: reject, method: method});
		});
		this.ws.send(JSON.stringify({id: id, method: method, params: params || {}}));
		return promise;
	}

	on(event, handler) {
		if (!this.handlers.has(event)) this.handlers.set(event, []);
		this.handlers.get(event).push(handler);
	}

	// Turn on the domains that report the failures we care about, and forward
	// every uncaught exception / console error to `sink`.
	async watchFailures(sink) {
		this.on('Runtime.exceptionThrown', (p) => {
			const d = p.exceptionDetails || {};
			const desc = (d.exception && (d.exception.description || d.exception.value)) || d.text || 'unknown';
			sink({kind: 'uncaught', text: String(desc), line: d.lineNumber, column: d.columnNumber, url: d.url});
		});
		this.on('Runtime.consoleAPICalled', (p) => {
			if (p.type !== 'error' && p.type !== 'warning') return;
			const text = (p.args || []).map((a) => (a.value !== undefined ? a.value : a.description)).join(' ');
			sink({kind: 'console.' + p.type, text: String(text)});
		});
		this.on('Log.entryAdded', (p) => {
			const e = p.entry || {};
			if (e.level !== 'error' && e.level !== 'warning') return;
			sink({kind: 'log.' + e.level, text: String(e.text), url: e.url});
		});
		await this.send('Runtime.enable');
		await this.send('Log.enable');
	}

	async evaluate(expression) {
		const res = await this.send('Runtime.evaluate', {
			expression: expression,
			awaitPromise: true,
			returnByValue: true,
			allowUnsafeEvalBlockedByCSP: true
		});
		if (res.exceptionDetails) {
			const d = res.exceptionDetails;
			const desc = (d.exception && (d.exception.description || d.exception.value)) || d.text;
			const err = new Error('evaluate threw: ' + desc);
			err.cdpDetails = d;
			throw err;
		}
		return res.result ? res.result.value : undefined;
	}

	close() { try { this.ws.close(); } catch (e) {} }
}

module.exports = {CDP: CDP, listPages: listPages, waitForPage: waitForPage, getJSON: getJSON};
