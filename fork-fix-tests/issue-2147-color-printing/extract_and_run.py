#!/usr/bin/env python3
"""
#2147 - "Color printing" is greyed out and stuck on "Black and white printing".

The combo the reporters photographed is web-apps' own Print panel, and it is driven
entirely by one boolean the shell publishes per queue:

    FileMenuPanels.js:  colorSupported: !!printer.color_supported
                        this.setCmbColorPrintingDisabled(record ? !record.colorSupported : true)
                        -> cmbColorPrinting.setValue('black-and-white'); setDisabled(true)

and that boolean came from a single PPD option keyword in cprintdata.cpp:

    if (strcmp(option->keyword, "ColorModel") == 0) { ... }

Drivers do not agree on that keyword. The reporter on the thread posted their own
`lpoptions -p EPSON_L3250_Series -l` output:

    Ink/Grayscale: *COLOR MONO

- an "Ink" option, no "ColorModel" anywhere - so the scan found nothing and the shell
told the editor the printer was monochrome.

This test does not paraphrase any of that. It extracts the real predicate functions
from cprintdata.cpp by brace matching, compiles them against the real <cups/ppd.h>,
and feeds them PPDs parsed by the real ppdOpenFile() out of the system libcups -
macOS ships CUPS 2.3.4, the same PPD parser the Linux build calls. The PPDs are
modelled on the drivers named in the thread: Epson ESC/P-R (Ink), an HP colour laser
(ColorModel), a Brother mono laser, and a colour queue whose PPD declares nothing but
*ColorDevice.

The printer-type half is exercised with a real cups_dest_t built through
cupsAddDest/cupsAddOption, so CUPS_PRINTER_COLOR is the real bit, not a guess.

BASELINE=1 re-reads cprintdata.cpp from before the fix, where the only predicate is
the ColorModel walk - and every colour printer that spells the option any other way
is reported as monochrome.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/cprintdata.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '2441a039db^')
BASELINE = bool(os.environ.get('BASELINE'))

if BASELINE:
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()


def brace_match(src, at):
    """Return src[at:] up to and including the '}' that closes the next '{'."""
    open_brace = src.index('{', at)
    depth = 0
    for i in range(open_brace, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces extracting from %s' % REL)


def take_function(signature):
    at = source.find(signature)
    if at == -1:
        return None
    return brace_match(source, at)


def take_table(name):
    """Lift a `static const char * const <name>[] = { ... };` table verbatim."""
    at = source.find('static const char * const %s[]' % name)
    if at == -1:
        return None
    end = source.index(';', source.index('=', at))
    return source[at:end + 1]


# --- what HEAD has -----------------------------------------------------------------
extracted = []
for sig in ('static bool equalsNoCase(', 'static bool containsNoCase(',
            'static bool ppdChoiceMeansColor(', 'static bool ppdOffersColor(',
            'static bool destAdvertisesColor(', 'static bool printerSupportsColor('):
    body = take_function(sig)
    if body:
        extracted.append(body)

tables = [t for t in (take_table('kColorOptionKeywords'), take_table('kMonochromeChoices')) if t]

if extracted:
    helpers = '\n\n'.join(tables + extracted)
    print('extracted from %s: %d predicate(s), %d keyword table(s)'
          % (REL, len(extracted), len(tables)))
else:
    # The unpatched file has no predicate at all - the decision is inline in the
    # capability loop. Lift that loop's own text and wrap it, so the baseline runs
    # the real old logic rather than a retelling of it.
    at = source.find('if (strcmp(option->keyword, "ColorModel") == 0)')
    if at == -1:
        raise SystemExit('neither the fixed predicates nor the old ColorModel branch '
                         'were found in %s - the call site moved' % REL)
    # Take the whole `if (strcmp(keyword, "ColorModel") == 0) { ... }`, condition
    # included - without the condition the choice walk would run for every option.
    branch = brace_match(source, at)
    if not branch.startswith('if (strcmp(option->keyword, "ColorModel")'):
        raise SystemExit('unexpected shape for the old ColorModel branch: %r' % branch[:60])
    # The branch sets printerObject["color_supported"]; give it a bool to set instead.
    branch = branch.replace('printerObject["color_supported"] = true;', 'answer = true;')
    if 'answer = true;' not in branch:
        raise SystemExit('the old ColorModel branch no longer assigns color_supported')
    helpers = r'''
static bool printerSupportsColor(cups_dest_t *dest, ppd_file_t *ppdF)
{
    (void)dest;
    bool answer = false;
    if (!ppdF) return false;
    ppd_option_t *option = ppdFirstOption(ppdF);
    while (option) {
        %s
        option = ppdNextOption(ppdF);
    }
    return answer;
}
''' % branch
    print('extracted from %s: the pre-fix inline ColorModel branch' % REL)
sys.stdout.flush()

# --- the PPDs ----------------------------------------------------------------------
# Trimmed to the keywords under test; every one is parsed by the real ppdOpenFile.
PPD_HEAD = '''*PPD-Adobe: "4.3"
*FormatVersion: "4.3"
*FileVersion: "1.0"
*LanguageVersion: English
*LanguageEncoding: ISOLatin1
*PCFileName: "TEST.PPD"
*Manufacturer: "%(vendor)s"
*Product: "(%(model)s)"
*ModelName: "%(model)s"
*ShortNickName: "%(model)s"
*NickName: "%(nick)s"
*PSVersion: "(3010.000) 0"
*ColorDevice: %(colordevice)s
*DefaultColorSpace: %(space)s
*FileSystem: False
*LanguageLevel: "3"
*OpenGroup: General/General
*OpenUI *PageSize/Media Size: PickOne
*OrderDependency: 10 AnySetup *PageSize
*DefaultPageSize: Letter
*PageSize Letter/Letter: ""
*PageSize A4/A4: ""
*CloseUI: *PageSize
*OpenUI *PageRegion/Media Size: PickOne
*OrderDependency: 10 AnySetup *PageRegion
*DefaultPageRegion: Letter
*PageRegion Letter/Letter: ""
*PageRegion A4/A4: ""
*CloseUI: *PageRegion
*DefaultImageableArea: Letter
*ImageableArea Letter/Letter: "9 9 603 783"
*ImageableArea A4/A4: "9 9 586 833"
*DefaultPaperDimension: Letter
*PaperDimension Letter/Letter: "612 792"
*PaperDimension A4/A4: "595 842"
'''
PPD_TAIL = '*CloseGroup: General\n'

PPDS = {}

PPDS['epson-escpr'] = PPD_HEAD % dict(
    vendor='Epson', model='EPSON L3250 Series', space='RGB', colordevice='True',
    nick='EPSON L3250 Series, Epson Inkjet Printer Driver (ESC/P-R) for Linux') + '''*OpenUI *Ink/Grayscale: PickOne
*OrderDependency: 20 AnySetup *Ink
*DefaultInk: COLOR
*Ink COLOR/Color: ""
*Ink MONO/Grayscale: ""
*CloseUI: *Ink
''' + PPD_TAIL

# The same driver with the *ColorDevice line removed, so the option scan has to carry
# it on its own. This is the case that proves the keyword list is doing work.
PPDS['epson-escpr-no-colordevice'] = PPDS['epson-escpr'].replace(
    '*ColorDevice: True\n', '*ColorDevice: False\n')

PPDS['hp-colorlaserjet'] = PPD_HEAD % dict(
    vendor='HP', model='HP LaserJet 200 colorMFP M276nw', space='RGB', colordevice='True',
    nick='HP LaserJet 200 colorMFP M276nw, hpcups 3.22.10') + '''*OpenUI *ColorModel/Color Mode: PickOne
*OrderDependency: 20 AnySetup *ColorModel
*DefaultColorModel: RGB
*ColorModel Gray/Grayscale: ""
*ColorModel RGB/Color: ""
*CloseUI: *ColorModel
''' + PPD_TAIL

PPDS['brother-mono'] = PPD_HEAD % dict(
    vendor='Brother', model='Brother HL-L2350DW', space='Gray', colordevice='False',
    nick='Brother HL-L2350DW for CUPS') + '''*OpenUI *ColorModel/Color Mode: PickOne
*OrderDependency: 20 AnySetup *ColorModel
*DefaultColorModel: Gray
*ColorModel Gray/Grayscale: ""
*CloseUI: *ColorModel
''' + PPD_TAIL

# A mono laser whose PPD spells "black only" as something other than "Gray". The old
# `choice != "Gray"` test calls this one colour; it is not.
PPDS['mono-blackonly'] = PPD_HEAD % dict(
    vendor='Generic', model='Generic Mono Laser', space='Gray', colordevice='False',
    nick='Generic Mono Laser, foomatic') + '''*OpenUI *ColorModel/Color Mode: PickOne
*OrderDependency: 20 AnySetup *ColorModel
*DefaultColorModel: Black
*ColorModel Black/Black Only: ""
*ColorModel KGray/Draft Grayscale: ""
*CloseUI: *ColorModel
''' + PPD_TAIL

PPDS['brother-colour'] = PPD_HEAD % dict(
    vendor='Brother', model='Brother MFC-L3750CDW', space='RGB', colordevice='False',
    nick='Brother MFC-L3750CDW for CUPS') + '''*OpenUI *BRMonoColor/Color / Mono: PickOne
*OrderDependency: 20 AnySetup *BRMonoColor
*DefaultBRMonoColor: Auto
*BRMonoColor Auto/Auto: ""
*BRMonoColor FullColor/Full Color: ""
*BRMonoColor Mono/Mono: ""
*CloseUI: *BRMonoColor
''' + PPD_TAIL

# A driverless/IPP-Everywhere queue: CUPS generates a PPD with no colour toggle at all
# and only the *ColorDevice declaration to go on.
PPDS['driverless-colour'] = PPD_HEAD % dict(
    vendor='HP', model='HP OfficeJet Pro 9010', space='RGB', colordevice='True',
    nick='HP OfficeJet Pro 9010, driverless, cups-filters 2.0') + PPD_TAIL

harness = r'''
#include <cups/cups.h>
#include <cups/ppd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

%(helpers)s

static int failures = 0;

static void check_ppd(const char *path, const char *label, bool want)
{
    ppd_file_t *ppdF = ppdOpenFile(path);
    if (!ppdF) {
        printf("  %%-30s  ppdOpenFile FAILED  %%s\n", label, path);
        failures++;
        return;
    }
    bool got = printerSupportsColor(NULL, ppdF);
    printf("  %%-30s  color_supported=%%-5s  want=%%-5s  %%s\n",
           label, got ? "true" : "false", want ? "true" : "false",
           got == want ? "ok" : "FAILED");
    if (got != want) failures++;
    ppdClose(ppdF);
}

/* A real cups_dest_t, so CUPS_PRINTER_COLOR is the bit libcups defines. */
static void check_dest(const char *label, const char *printer_type, bool want)
{
    cups_dest_t *dests = NULL;
    int num = cupsAddDest("harness", NULL, 0, &dests);
    if (num < 1 || !dests) {
        printf("  %%-30s  cupsAddDest FAILED\n", label);
        failures++;
        return;
    }
    if (printer_type)
        dests[0].num_options = cupsAddOption("printer-type", printer_type,
                                             dests[0].num_options, &dests[0].options);
    bool got = printerSupportsColor(&dests[0], NULL);
    printf("  %%-30s  color_supported=%%-5s  want=%%-5s  %%s\n",
           label, got ? "true" : "false", want ? "true" : "false",
           got == want ? "ok" : "FAILED");
    if (got != want) failures++;
    cupsFreeDests(num, dests);
}

int main(int argc, char **argv)
{
    const char *dir = argv[1];
    char path[2048];

    printf("\nPPDs, parsed by the system libcups (CUPS %%d.%%d.%%d):\n",
           CUPS_VERSION_MAJOR, CUPS_VERSION_MINOR, CUPS_VERSION_PATCH);

#define PPD(name, label, want) \
    snprintf(path, sizeof(path), "%%s/%%s.ppd", dir, name); check_ppd(path, label, want)

    PPD("hp-colorlaserjet",           "HP colour laser (ColorModel)",  true);
    PPD("epson-escpr",                "Epson ESC/P-R (Ink)",           true);
    PPD("epson-escpr-no-colordevice", "Epson, *ColorDevice stripped",  true);
    PPD("brother-colour",             "Brother (BRMonoColor)",         true);
    PPD("driverless-colour",          "driverless, *ColorDevice only", true);
    PPD("brother-mono",               "Brother mono laser",            false);
    PPD("mono-blackonly",             "mono laser, ColorModel=Black",  false);
#undef PPD

    printf("\nQueue attributes, via a real cups_dest_t:\n");
    /* CUPS_PRINTER_COLOR is 0x8; CUPS_PRINTER_BW is 0x4. 0x800000c = local BW+colour
       queue with the usual capability bits, 0x8000004 = the same queue, mono only. */
    {
        char with_color[32], without_color[32];
        snprintf(with_color, sizeof(with_color), "%%lu",
                 (unsigned long)(CUPS_PRINTER_LOCAL | CUPS_PRINTER_BW | CUPS_PRINTER_COLOR | CUPS_PRINTER_COPIES));
        snprintf(without_color, sizeof(without_color), "%%lu",
                 (unsigned long)(CUPS_PRINTER_LOCAL | CUPS_PRINTER_BW | CUPS_PRINTER_COPIES));
        check_dest("printer-type has COLOR",   with_color,    true);
        check_dest("printer-type lacks COLOR", without_color, false);
        check_dest("no printer-type at all",   NULL,          false);
    }

    printf("\n%%s\n", failures
        ? "FAILED"
        : "ok - colour is offered for every colour queue and withheld from mono ones");
    return failures ? 1 : 0;
}
''' % {'helpers': helpers}

with tempfile.TemporaryDirectory() as tmp:
    for name, text in PPDS.items():
        open(os.path.join(tmp, name + '.ppd'), 'w').write(text)

    src = os.path.join(tmp, 'harness.cpp')
    exe = os.path.join(tmp, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-Wno-deprecated-declarations',
                        '-Wno-writable-strings', '-o', exe, src, '-lcups'],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe, tmp]).returncode)
