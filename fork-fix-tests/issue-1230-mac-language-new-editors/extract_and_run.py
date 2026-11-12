#!/usr/bin/env python3
"""
#1230 - "The app language doesn't change completely, only on the second launch". On macOS,
after Settings > Interface language > Apply, documents opened afterwards still came up in the
old language until the app was restarted.

The settings:apply handler in ASCEventsController.mm (desktop-apps macos/.../Common) set the
editors' `lang` URL parameter from [NSLocale currentLocale] BEFORE storing the new langid with
+[ASCLinguist setAppLanguageCode:]. NSLocale currentLocale is cached for the life of the process
(writing AppleLocale/AppleLanguages to the app's defaults does not change it), so it kept
answering the language the app was launched with. The fix stores the language first and takes
the parameter from +[ASCLinguist appLanguageCode], as ASCEditorJSVariables does at startup.

What runs here: the language part of the real settings:apply handler (from the external-delegate
lookup up to the `username` branch), lifted from the source and compiled as Objective-C++ with
the REAL ASCLinguist.m and real NSUserDefaults/NSLocale. ASCEditorJSVariables, the external
controller (no delegate, as in our build) and the app manager are stubs that record calls.
The "app" starts in en-US, primes NSLocale as the running app has long done by then, and then
applies langid lv-LV; the `lang` handed to new editors must be Latvian.

Claimed: the editors' lang parameter follows the language just applied. NOT claimed: documents
already open (web-apps loads translations once; they keep their language), native macOS menus
(need a restart, as before), Windows/Linux (their wrapper already rebuilt `lang=` in
setUserSettings). A GUI check on macOS is still worthwhile.

The test's NSUserDefaults domain (rd_issue1230_harness) and its plist are removed at the end.
BASELINE=1 reads the file at BASE_REF (parent of the fix): lang stays "en".
RD_REPO overrides the desktop-apps checkout (default ../../desktop-apps from this file). macOS only.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps'))
# Pinned to the parent of the commit that landed this fix. It must NOT default to HEAD.
BASE_REF = os.environ.get('BASE_REF', '5c8da46e06^')
REL = 'macos/ONLYOFFICE/Code/Controllers/Common/ASCEventsController.mm'
LINGUIST = 'macos/ONLYOFFICE/Code/Controllers/Common/ASCLinguist.m'


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


source = read(REL)
linguist = read(LINGUIST)

at = source.find('cmd.find(L"settings:apply")')
if at == -1:
    raise SystemExit('the settings:apply handler is gone')
start = source.find('id <ASCExternalDelegate> externalDelegate', at)
end = source.find('if (NSString * userName = json[@"username"])', at)
if start == -1 or end == -1 or end < start:
    raise SystemExit('could not find the language part of settings:apply')
fragment = source[start:end]
if 'setAppLanguageCode' not in fragment or '@"lang"' not in fragment:
    raise SystemExit('extracted the wrong part of settings:apply')

constants = r'''
#import <Foundation/Foundation.h>
static NSString * const ASCUserUILanguage = @"asc_user_ui_lang";
'''
linguist_h = r'''
#import <Foundation/Foundation.h>
@interface ASCLinguist : NSObject
+ (void)init;
+ (NSString *)appLanguageCode;
+ (void)setAppLanguageCode:(NSString *)langCode;
+ (BOOL)isUILayoutDirectionRtl;
+ (NSDictionary *)keyboardLanguages;
+ (NSDictionary *)availableLanguages;
@end
'''

harness = r'''
#import <Foundation/Foundation.h>
#include <string>
#import "ASCLinguist.h"

@protocol ASCExternalDelegate <NSObject>
@optional
- (NSString *)onAppPreferredLanguage;
@end
@interface ASCExternalController : NSObject
@property (nonatomic, assign) id <ASCExternalDelegate> delegate;
+ (instancetype)shared;
@end
@implementation ASCExternalController
+ (instancetype)shared { static ASCExternalController * s; if (!s) s = [ASCExternalController new]; return s; }
@end

static NSMutableDictionary * g_params;
@interface ASCEditorJSVariables : NSObject
+ (instancetype)instance;
- (void)setParameter:(NSString *)name withString:(NSString *)value;
@end
@implementation ASCEditorJSVariables
+ (instancetype)instance { static ASCEditorJSVariables * s; if (!s) s = [ASCEditorJSVariables new]; return s; }
- (void)setParameter:(NSString *)name withString:(NSString *)value { g_params[name] = value; }
@end

struct CAscApplicationManager { int plugins = 0; void UpdatePlugins(const std::wstring&) { ++plugins; } };
static CAscApplicationManager g_manager;
@interface NSAscApplicationWorker : NSObject
+ (CAscApplicationManager *)getAppManager;
@end
@implementation NSAscApplicationWorker
+ (CAscApplicationManager *)getAppManager { return &g_manager; }
@end

@interface NSDictionary (RDJson) - (NSString *)jsonString; @end
@implementation NSDictionary (RDJson)
- (NSString *)jsonString { return [[NSString alloc] initWithData:[NSJSONSerialization dataWithJSONObject:self options:0 error:nil] encoding:NSUTF8StringEncoding]; }
@end
@interface NSString (RDWstr) - (std::wstring)stdwstring; @end
@implementation NSString (RDWstr)
- (std::wstring)stdwstring { std::wstring w; for (NSUInteger i = 0; i < self.length; ++i) w += (wchar_t)[self characterAtIndex:i]; return w; }
@end

static void apply(NSDictionary * json) {
%(fragment)s
}

int main() { @autoreleasepool {
	g_params = [NSMutableDictionary dictionary];
	NSUserDefaults * d = [NSUserDefaults standardUserDefaults];
	/* the app was launched in English: AppDelegate calls [ASCLinguist init] at startup */
	[d setObject:@"en-US" forKey:@"asc_user_ui_lang"];
	[ASCLinguist init];
	NSString * launched = [[NSLocale currentLocale] objectForKey:NSLocaleLanguageCode];

	/* Settings > Interface language: Latviesu valoda > Apply */
	apply(@{ @"langid": @"lv-LV", @"username": @"" });
	NSString * lang = g_params[@"lang"];
	NSString * stored = [ASCLinguist appLanguageCode];

	[d removePersistentDomainForName:[[NSProcessInfo processInfo] processName]];
	[d synchronize];

	bool good = [lang.lowercaseString hasPrefix:@"lv"];
	printf("  launched in %%s; applied lv-LV; stored language %%s; plugins told %%d time(s)\n",
	       launched.UTF8String, stored.UTF8String, g_manager.plugins);
	printf("  lang handed to editors opened next: %%s  %%s\n", lang ? lang.UTF8String : "(none)", good ? "ok" : "FAILED (old language)");
	printf("\n%%s\n", good ? "ok - documents opened after a language change use the new language" : "FAILED");
	return good ? 0 : 1;
}}
''' % dict(fragment=fragment)

print('extracted the language part of settings:apply from %s%s' % (REPO, ' @ ' + BASE_REF if os.environ.get('BASELINE') else ''))
sys.stdout.flush()
with tempfile.TemporaryDirectory() as tmp:
    open(os.path.join(tmp, 'ASCConstants.h'), 'w').write(constants)
    open(os.path.join(tmp, 'ASCLinguist.h'), 'w').write(linguist_h)
    open(os.path.join(tmp, 'ASCLinguist.m'), 'w').write(linguist)
    open(os.path.join(tmp, 'harness.mm'), 'w').write(harness)
    exe = os.path.join(tmp, 'rd_issue1230_harness')
    c = subprocess.run(['clang++', '-fobjc-arc', '-w', '-I', tmp, '-o', exe,
                        os.path.join(tmp, 'harness.mm'), '-x', 'objective-c', os.path.join(tmp, 'ASCLinguist.m'),
                        '-framework', 'Foundation', '-framework', 'Carbon'], capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    rc = subprocess.run([exe]).returncode
    # the emptied defaults domain still leaves a plist behind
    plist = os.path.expanduser('~/Library/Preferences/rd_issue1230_harness.plist')
    if os.path.exists(plist):
        os.remove(plist)
    sys.exit(rc)
