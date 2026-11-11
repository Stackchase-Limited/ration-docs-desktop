#!/usr/bin/env python3
"""
#560 - "Print feature ignores paper size, always produces A4 size printouts". On macOS a
document set to US Letter, Legal, an envelope or any custom size (#281's 210x330 mm F4)
printed - and printed to PDF - on the printer's default sheet.

ASCPrinterContext::BeginPaint (desktop-apps macos/.../Utils/ascprinter.h) took the sheet
from nativeOptions.paperSize.preset with -[NSPrintInfo setPaperName:]. The preset is the
caption web-apps shows ("US Letter", "Envelope #10", ...), not a macOS paper name, and
setPaperName: silently ignores names it does not know; a custom page sends no preset and
that branch was commented out. The fix sizes the sheet from paperSize.w/h with
setPaperSize:, which resolves to the printer's named paper of that size.

What runs here is the real nativeOptions block of BeginPaint, lifted by brace matching
(`if ( pWOptions && [pWOptions objectForKey:@"nativeOptions"] ) {...}`) and compiled as
Objective-C against the real AppKit, applied to a copy of the shared NSPrintInfo, as BeginPaint
uses (it starts on the default printer's default sheet - iso-a4 on the Mac this was written
on; on a Letter machine the US Letter case passes on BASELINE but the others still fail). The options are what web-apps'
documenteditor Print controller sends: w/h of the page in mm and the preset caption. Then a
real NSPrintOperation saves a one-page job to PDF (NSPrintSaveJob, no panel, no printer)
and the PDF's MediaBox is read back - that is the sheet the print job carries.

Claimed: US Letter, Envelope #10 (landscape page) and a custom 210x330 page give a sheet of
that size; A4 stays A4. NOT claimed: ASCPrintView's per-page orientation/placement, the
print panel, or a physical printer (needs a GUI check on macOS).

BASELINE=1 reads ascprinter.h at BASE_REF (parent of the fix): every non-ISO size stays on the
default sheet.
RD_REPO overrides the desktop-apps checkout (default ../../desktop-apps from this file).
macOS only.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps'))
# Pinned to the parent of the commit that landed this fix. It must NOT default to HEAD.
BASE_REF = os.environ.get('BASE_REF', '27578a09e^')
REL = 'macos/ONLYOFFICE/Code/Utils/ascprinter.h'

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()


def brace_match(src, at, what):
    depth = 0
    for i in range(src.index('{', at), len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces extracting %s' % what)


needle = 'if ( pWOptions && [pWOptions objectForKey:@"nativeOptions"] ) {'
at = source.find(needle)
if at == -1:
    raise SystemExit('the nativeOptions block of BeginPaint is gone')
block = brace_match(source, at, 'the nativeOptions block')
if 'paperSize' not in block or 'PMSetCopies' not in block:
    raise SystemExit('extracted the wrong block')

harness = r'''
#import <Cocoa/Cocoa.h>
#include <cmath>
struct Info { int m_nPagesCount; };

@interface Sheet : NSView @end
@implementation Sheet
- (void)drawRect:(NSRect)r { [[NSColor blackColor] set]; NSFrameRect(NSInsetRect(self.bounds, 20, 20)); }
@end

/* one case: the web-apps options, through the lifted block, then a real print job to PDF */
static int run(const char* what, NSDictionary* nativeOptions, double wantW, double wantH, NSString* dir)
{
	NSPrintInfo* pPrintInfo = [[NSPrintInfo sharedPrintInfo] copy];
	/* starts on the default printer's default sheet, as BeginPaint's sharedPrintInfo does */
	Info m_oInfo = { 1 };
	int pageCurrent = 1;
	NSDictionary* pWOptions = @{ @"nativeOptions": nativeOptions };

	%(block)s

	NSString* out = [dir stringByAppendingPathComponent:[NSString stringWithFormat:@"%%s.pdf", what]];
	[pPrintInfo setJobDisposition:NSPrintSaveJob];
	[pPrintInfo.dictionary setObject:[NSURL fileURLWithPath:out] forKey:NSPrintJobSavingURL];
	NSSize paper = pPrintInfo.paperSize;
	Sheet* view = [[Sheet alloc] initWithFrame:NSMakeRect(0, 0, paper.width, paper.height)];
	NSPrintOperation* op = [NSPrintOperation printOperationWithView:view printInfo:pPrintInfo];
	[op setShowsPrintPanel:NO];
	[op setShowsProgressPanel:NO];
	BOOL ok = [op runOperation];

	CGPDFDocumentRef doc = ok ? CGPDFDocumentCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:out]) : NULL;
	CGRect box = doc ? CGPDFPageGetBoxRect(CGPDFDocumentGetPage(doc, 1), kCGPDFMediaBox) : CGRectZero;
	if (doc) CGPDFDocumentRelease(doc);
	bool good = std::fabs(box.size.width - wantW) < 1.5 && std::fabs(box.size.height - wantH) < 1.5;
	printf("  %%-30s paper %%-24s PDF MediaBox %%6.1f x %%-6.1f pt (want %%.1f x %%.1f)  %%s\n", what,
	       [pPrintInfo.paperName UTF8String], box.size.width, box.size.height, wantW, wantH, good ? "ok" : "FAILED");
	return good ? 0 : 1;
}

int main(int argc, char** argv) { @autoreleasepool {
	[NSApplication sharedApplication];
	NSString* dir = [NSString stringWithUTF8String:argv[1]];
	const double mm = 72 / 25.4;
	int failures = 0;
	/* what documenteditor/main/app/controller/Print.js sends: page W/H in mm, preset caption */
	failures += run("A4", @{ @"paperSize": @{ @"w": @210, @"h": @297, @"preset": @"A4" }, @"copies": @1, @"sides": @"one" },
	                210 * mm, 297 * mm, dir);
	failures += run("US Letter", @{ @"paperSize": @{ @"w": @215.9, @"h": @279.4, @"preset": @"US Letter" }, @"copies": @1, @"sides": @"one" },
	                612, 792, dir);
	failures += run("Envelope #10 landscape", @{ @"paperSize": @{ @"w": @241.3, @"h": @104.8, @"preset": @"Envelope #10" }, @"copies": @1, @"sides": @"one" },
	                104.8 * mm, 241.3 * mm, dir);
	failures += run("custom 210x330 (#281)", @{ @"paperSize": @{ @"w": @210, @"h": @330 }, @"copies": @1, @"sides": @"one" },
	                210 * mm, 330 * mm, dir);
	printf("\n%%s\n", failures ? "FAILED" : "ok - the print job's sheet is the document's page size");
	return failures ? 1 : 0;
}}
''' % dict(block=block)

print('extracted the nativeOptions block of BeginPaint from %s%s' % (REPO, ' @ ' + BASE_REF if os.environ.get('BASELINE') else ''))
sys.stdout.flush()
with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'harness.mm')
    exe = os.path.join(tmp, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang++', '-fobjc-arc', '-w', '-o', exe, src, '-framework', 'Cocoa'], capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe, tmp]).returncode)
