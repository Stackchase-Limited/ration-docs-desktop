#!/usr/bin/env python3
"""Extract the real IsHexLiteral out of DigitReader.cpp and wrap it in a harness."""
import re, sys, os
src = open(sys.argv[1], encoding='utf-8').read()

at = src.find('static bool IsHexLiteral(const std::wstring &value)')
if at == -1:
    sys.stderr.write(
        'IsHexLiteral not found in DigitReader.cpp - CSV import still hands 0x... '
        'straight to wcstod, which parses it as a hexadecimal float (#2301)\n')
    sys.exit(1)
open_brace = src.index('{', at)
depth = 0
for i in range(open_brace, len(src)):
    if src[i] == '{': depth += 1
    elif src[i] == '}':
        depth -= 1
        if depth == 0:
            end = i; break
fn = src[at:end+1]

print(r'''
#include <stdio.h>
#include <wchar.h>
#include <string>
#include <cmath>

%s

static int failures = 0;

/* Demonstrate the defect rather than assume it: wcstod really does swallow these. */
static bool wcstodAcceptsWhole(const wchar_t *s) {
    wchar_t *end;
    double d = wcstod(s, &end);
    (void)d;
    return *end == 0 && end != s;
}

static void mustReject(const wchar_t *s) {
    bool swallowed = wcstodAcceptsWhole(s);
    bool rejected  = IsHexLiteral(std::wstring(s));
    printf("  %%-46ls wcstod-would-take=%%-5s rejected=%%-5s %%s\n",
           s, swallowed ? "yes" : "no", rejected ? "yes" : "no",
           (swallowed && rejected) ? "ok" : "FAILED");
    if (!(swallowed && rejected)) failures++;
}

static void mustAccept(const wchar_t *s) {
    bool rejected = IsHexLiteral(std::wstring(s));
    printf("  %%-46ls kept as a number=%%-5s %%s\n",
           s, rejected ? "no" : "yes", rejected ? "FAILED" : "ok");
    if (rejected) failures++;
}

int main() {
    printf("values wcstod misreads as numbers - must be refused:\n");
    mustReject(L"0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb");  /* the report */
    mustReject(L"0x1A");
    mustReject(L"0XFF");
    mustReject(L"0x1p3");        /* hex float with a binary exponent */
    mustReject(L"-0xFF");
    mustReject(L"  0x10");

    printf("\nordinary values - must still be numbers:\n");
    mustAccept(L"123");
    mustAccept(L"1e5");
    mustAccept(L"-42.5");
    mustAccept(L"0");
    mustAccept(L"0.5");
    mustAccept(L"  7 ");
    mustAccept(L"1234567890123456789");

    printf("\n%%s\n", failures ? "FAILED" : "ok - hex literals stay text, numbers stay numbers");
    return failures ? 1 : 0;
}
''' % fn)
