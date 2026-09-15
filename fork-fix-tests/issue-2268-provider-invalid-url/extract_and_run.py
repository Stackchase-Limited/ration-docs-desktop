#!/usr/bin/env python3
"""
#2268 - "OpenAI Compatible Endpoint not working".

The reporter has a working OpenAI-compatible server. `curl
http://localhost:9999/api/v1/models` returns the model list, the server's own log
shows the plugin asking for exactly that path - and the plugin answers "Invalid
URL". They then spent the report trying `/v1`, trailing slashes and so on,
because the plugin had told them the address was the problem.

TWO SEPARATE THINGS, and this test covers the second.

1. THE ROOT CAUSE, NOT FIXED HERE. The plugin runs at a file: origin, so the
   OpenAI SDK's fetch carries Authorization + Content-Type and triggers a CORS
   preflight. curl sends no Origin and so never triggers one, which is why curl
   works and the plugin does not. The fix is to route provider requests through
   the `onlyoffice-proxy://` scheme the same plugin already uses for MCP servers
   and web search (src/servers/CustomServers.ts:363), registered CORS-exempt in
   C++ at lib/src/cefwrapper/client_scheme_wrapper.cpp:600. That is a real change
   to how every provider talks to the network and is not attempted here.

2. THE MISDIAGNOSIS, FIXED HERE. Whatever the underlying failure, the plugin has
   to say what actually happened. #2444 established that distinction for the
   OpenAI provider: a request that never reached a server is a connection
   failure, and only a server that answered 404 can tell you the address is
   wrong. But OllamaProvider overrides checkProvider with

       } catch {
         return ProviderErrors.invalidUrl();
       }

   which inherits nothing from that fix, and LMStudioProvider blames the url
   field twice over - once for any thrown error and once when the server answered
   perfectly well but had no models loaded. Those two are the code paths that
   produce the literal "Invalid URL" the reporter quotes, and #2444 did not touch
   either.

This extracts the real checkProvider out of both providers, and the real
ProviderErrors / getErrorCode / extractErrorMessage out of errors.ts, strips the
type annotations, and drives them under Node against a client that fails the way
each real failure mode does.

NOT ASSERTED HERE. LMStudioProvider's empty-model-list case was also changed,
from invalidUrl("No models loaded in LM Studio") to connectionFailed with the
same message. Both factories build {field: "url", message: ...}, so the two are
byte-identical at runtime and no test can tell them apart - it is a statement of
intent, not a behaviour change, and is not claimed as one.

  BASELINE=1 re-reads all three files from git HEAD, where it must FAIL.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
PLUGIN = 'ChromiumBasedEditors/plugins/ai-agent/src/providers'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', 'd8daec7d3a^')


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def arrow_property(text, name, what):
    """Extract `name = async (...) => { ... };` or `name = { ... };` by brace matching."""
    m = re.search(r'^(?:export )?const %s = |^  %s = ' % (re.escape(name), re.escape(name)),
                  text, re.M)
    if not m:
        raise SystemExit('%s not found in %s' % (name, what))
    ob = text.index('{', m.end())
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[m.start():i + 1]
    raise SystemExit('unbalanced braces in %s' % name)


def strip_types(src):
    """Remove the TypeScript annotations these particular snippets carry.

    Deliberately narrow: only the forms actually present. If a new form appears
    the harness fails to parse under Node rather than silently testing nothing.
    """
    # `): Promise<boolean | TErrorData> =>`  /  `): TErrorData =>`  /  `): string | undefined =>`
    src = re.sub(r'\)\s*:\s*[A-Za-z][A-Za-z0-9_<>|\[\]\s.]*?=>', ') =>', src)
    # `(data: TData)` / `(error: unknown)` / `(message = "x")` keeps the default
    src = re.sub(r'\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[A-Za-z][A-Za-z0-9_<>|\[\]\s.]*?\)',
                 r'(\1)', src)
    # `error.message as string`
    src = re.sub(r'\s+as\s+[A-Za-z][A-Za-z0-9_<>|\[\]\s.]*', '', src)
    # These are spliced into one plain script, not loaded as modules.
    src = re.sub(r'^export const ', 'const ', src)
    return src


errors_src = read(PLUGIN + '/errors.ts')
ollama_src = read(PLUGIN + '/ollama/index.ts')
lmstudio_src = read(PLUGIN + '/lm-studio/index.ts')

provider_errors = strip_types(arrow_property(errors_src, 'ProviderErrors', 'errors.ts'))
get_error_code = strip_types(arrow_property(errors_src, 'getErrorCode', 'errors.ts'))
extract_message = strip_types(arrow_property(errors_src, 'extractErrorMessage', 'errors.ts'))
get_error_status = strip_types(arrow_property(errors_src, 'getErrorStatus', 'errors.ts'))

m = re.search(r'^export const CONNECTION_ERROR = "([^"]+)";', errors_src, re.M)
connection_error = m.group(1) if m else 'connection_error'

ollama_check = strip_types(arrow_property(ollama_src, 'checkProvider', 'ollama/index.ts'))
lmstudio_check = strip_types(arrow_property(lmstudio_src, 'checkProvider', 'lm-studio/index.ts'))

for name, body in (('ollama', ollama_check), ('lm-studio', lmstudio_check)):
    if 'models.list()' not in body:
        raise SystemExit('extracted %s checkProvider does not call models.list() '
                         '- wrong block?' % name)

js = r'''
'use strict';
const CONNECTION_ERROR = %(connection_error)s;

/* --- the real helpers, lifted out of errors.ts --- */
%(provider_errors)s;
%(get_error_code)s;
%(get_error_status)s;
%(extract_message)s;

/* --- the real checkProvider of each provider, lifted out of its index.ts ---
   Each is a class property, so it is spliced back onto an object as one, and the
   arrow function's lexical `this` then resolves this.createClient the way it does
   in the real class. */
function makeProvider(assign, createClient) {
  const obj = { createClient };
  assign.call(obj);
  return obj.checkProvider;
}

const ollamaAssign = function () {
  this.%(ollama_check)s;
};

const lmStudioAssign = function () {
  this.%(lmstudio_check)s;
};

/* --- failure modes, shaped the way the real ones arrive --- */
function clientThatThrows(err) {
  return () => ({ models: { list: async () => { throw err; } } });
}
function clientThatLists(models) {
  return () => ({ models: { list: async () => ({ data: models }) } });
}

/* What the OpenAI SDK throws when fetch rejected - a blocked CORS preflight, a
   refused connection, a DNS or TLS failure. This is the reporter's case. */
const connectionError = Object.assign(new Error('Connection error.'), {});
/* A server that answered and said the path is not there. */
const notFound = Object.assign(new Error('Not Found'), { status: 404 });
/* A server that answered with something else entirely. */
const serverError = Object.assign(new Error('Internal Server Error'), { status: 500 });

let failures = 0;
function check(ok, what) {
  console.log('  ' + what.padEnd(66) + ' ' + (ok ? 'ok' : 'FAILED'));
  if (!ok) failures++;
}

function isUrlBlamed(r) { return r && r.field === 'url' && r.message === 'Invalid URL'; }

(async () => {
  const cases = [
    ['Ollama',    ollamaAssign],
    ['LM Studio', lmStudioAssign],
  ];

  console.log('a request that never reached a server is not a bad address:');
  for (const [name, assign] of cases) {
    const check1 = makeProvider(assign, clientThatThrows(connectionError));
    const r = await check1({ url: 'http://localhost:9999/api/v1', apiKey: '' });
    check(!isUrlBlamed(r),
          name + ': a blocked/refused request -> ' + JSON.stringify(r));
  }
  for (const [name, assign] of cases) {
    const c = makeProvider(assign, clientThatThrows(serverError));
    const r = await c({ url: 'http://localhost:9999/api/v1', apiKey: '' });
    check(!isUrlBlamed(r), name + ': a 500 from the server -> ' + JSON.stringify(r));
  }

  console.log('\nonly a server that answered 404 may blame the address:');
  for (const [name, assign] of cases) {
    const c = makeProvider(assign, clientThatThrows(notFound));
    const r = await c({ url: 'http://localhost:9999/nope', apiKey: '' });
    check(isUrlBlamed(r), name + ': a 404 -> ' + JSON.stringify(r));
  }

  console.log('\na working endpoint must still be accepted:');
  for (const [name, assign] of cases) {
    const c = makeProvider(assign, clientThatLists([{ id: 'llama3' }]));
    const r = await c({ url: 'http://localhost:9999/api/v1', apiKey: '' });
    check(r === true, name + ': a model list -> ' + JSON.stringify(r));
  }

  console.log('\n' + (failures
    ? 'FAILED'
    : 'ok - "Invalid URL" is said only when a server called the URL invalid'));
  process.exit(failures ? 1 : 0);
})();
''' % {
    'connection_error': '"%s"' % connection_error,
    'provider_errors': provider_errors,
    'get_error_code': get_error_code,
    'get_error_status': get_error_status,
    'extract_message': extract_message,
    'ollama_check': ollama_check,
    'lmstudio_check': lmstudio_check,
}

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, 'harness.js')
    open(path, 'w', encoding='utf-8').write(js)
    r = subprocess.run(['node', path])
    sys.exit(r.returncode)
