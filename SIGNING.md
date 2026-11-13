# Code signing

How Ration Docs release artefacts are signed. The pipeline is written and tested;
**the only missing input is the certificates.** Until they exist, releases ship unsigned
(see RELEASE_NOTES.md, "not signed or notarised").

| Platform | Script | Needs |
|---|---|---|
| macOS app, .pkg, .dmg | `desktop-apps/macos/sign_and_notarize.sh` | Developer ID Application + Developer ID Installer certificates, App Store Connect API key |
| Windows payload, .exe installer, .msi | `desktop-apps/package/sign/Sign.ps1` (called by `make.ps1 -Sign`, `make_inno.ps1 -Sign`, `make_advinst.ps1 -Sign`) | an OV/EV code signing certificate in a cloud HSM: Azure Trusted Signing, DigiCert KeyLocker or SSL.com eSigner |
| Linux | - | nothing yet (no repository key; out of scope here) |

## Where secrets live

- **In the CI secret store of the machine that signs, and nowhere else.** The scripts read
  them from environment variables only.
- **Never in git** (no `.env.secret` committed; `macos/fastlane/.env.secret` is loaded by
  the old fastlane lane and must stay untracked), **never on lab02**, never in a build log
  (`Sign.ps1` redacts the secrets it knows about; `notarytool` never prints the key).
- The Apple `.p8` key can be passed as a file path (`RD_NOTARY_KEY_PATH`, a file outside
  any checkout) or as content (`RD_NOTARY_KEY`, written to a 0600 temp file and deleted at
  exit).
- The Developer ID certificates (with private keys) live in a dedicated keychain on the
  macOS build machine (`RD_KEYCHAIN`), not in a person's login keychain. Keep the `.p12`
  export and its password in the team password manager.
- Windows keys never leave the provider's HSM; what the build machine holds is an API
  credential that can be revoked.

## macOS

### What to obtain (once)

1. Apple Developer Program membership for the organisation (Team ID).
2. **Developer ID Application** certificate (signs the app). Create the CSR on the build
   machine so the private key is born there; import into the CI keychain.
3. **Developer ID Installer** certificate (signs the .pkg).
4. **App Store Connect API key** with the Developer role (Users and Access > Integrations >
   Team Keys): key ID, issuer ID, `AuthKey_<id>.p8` (downloadable once).

### Environment

| Variable | Value |
|---|---|
| `RD_SIGN_IDENTITY` | `Developer ID Application: <Org> (<TEAMID>)` or its SHA-1 |
| `RD_INSTALLER_IDENTITY` | `Developer ID Installer: <Org> (<TEAMID>)` (only with `--pkg`) |
| `RD_KEYCHAIN` | path of the CI keychain (optional; default search list) |
| `RD_NOTARY_KEY_ID`, `RD_NOTARY_ISSUER` | API key ID and issuer UUID |
| `RD_NOTARY_KEY_PATH` or `RD_NOTARY_KEY` | the .p8 file, or its content |
| `RD_NOTARY_PROFILE` | alternative to the three above: a `notarytool store-credentials` profile |

### Commands

```sh
# 0. unlock the CI keychain (CI step; password from the secret store)
security unlock-keychain -p "$RD_KEYCHAIN_PASSWORD" "$RD_KEYCHAIN"

# 1. sign every Mach-O inside out, verify, notarize, staple; build + sign + notarize the pkg
desktop-apps/macos/sign_and_notarize.sh \
    --app "desktop-apps/macos/build/Release/Ration Docs.app" --pkg

# 2. build the DMG from the stapled app (fastlane's appdmg step), then sign/notarize it
npx appdmg desktop-apps/macos/fastlane/resources/appdmg.json RationDocs-<ver>-arm64.dmg
desktop-apps/macos/sign_and_notarize.sh --dmg RationDocs-<ver>-arm64.dmg

# 3. independent checks
codesign --verify --deep --strict --verbose=2 "Ration Docs.app"
spctl --assess --type execute -vv "Ration Docs.app"     # "accepted  source=Notarized Developer ID"
xcrun stapler validate "Ration Docs.app"
spctl --assess --type install -vv Ration-Docs-<ver>-arm64.pkg
spctl --assess --type open --context context:primary-signature -vv RationDocs-<ver>-arm64.dmg
```

Repeat per architecture (arm64, x86_64): each bundle is signed separately.

### Entitlements (per binary, `desktop-apps/macos/entitlements/`)

| Binary | Entitlements | Why |
|---|---|---|
| `Ration Docs` (main) | allow-jit, device.audio-input, device.camera | AI agent tools run docbuilder (JavaScriptCore) in-process; Info.plist offers camera/microphone to pages |
| `editors_helper (Renderer)` | allow-jit | V8 + WebAssembly. Without it every renderer dies at start (tested) |
| `editors_helper (GPU)` | allow-jit | SwiftShader JIT when the GPU is unusable. Without it the GPU helper crashes on that path (tested) |
| `editors_helper` (utility, network) | none | |
| `converter/x2t` | allow-jit | JavaScriptCore for every save/print/conversion; without it 6-9x slower |
| Sparkle Downloader.xpc | Sparkle's own (sandbox, network.client) | |
| everything else | none (hardened runtime only) | |

Deliberately **not** used: `disable-library-validation` (all code carries our Team ID),
`allow-unsigned-executable-memory`, `allow-dyld-environment-variables`, and
`get-task-allow` (the notary service rejects it - the Xcode target's
`ONLYOFFICE.entitlements` still has it, so do not ship what the Xcode phase signs without
running this script over it).

### Testing without a certificate

`--identity -` gives an ad-hoc signature with the real hardened runtime and the real
entitlements (plus `disable-library-validation`, standing in for the shared Team ID that
ad-hoc signatures lack). Run it on a **copy** with its own bundle id
(`com.stackchase.rationdocs.<x>.test`); `spctl` then reports "rejected", as expected.
Proven 2026-11-13 on a clone of `.rd-work/appbuild`: verify passes, all processes run with
`flags=adhoc,runtime`, docx/xlsx/pptx/pdf open and render, edits save through x2t, x2t
maps "JS JIT Generated Code".

## Windows

### Choosing a provider

| Provider | Certificate | Notes |
|---|---|---|
| **Azure Trusted Signing** | Microsoft-issued, short-lived, renewed automatically | cheapest; organisation must pass Microsoft's identity validation (3+ years of history for public trust); signtool `/dlib` |
| **DigiCert KeyLocker** | OV or EV from DigiCert | signtool + KSP; per-signature quota on some plans |
| **SSL.com eSigner** | OV or EV from SSL.com | CodeSignTool, **one call and one billed signature per file** - the payload has hundreds of DLLs; check `Sign.ps1 -DryRun` count against the plan |

Since June 2023 every publicly trusted code signing key must be in an HSM, which is why a
`.pfx` on disk is not an option.

### Environment (CI secrets on the Windows build machine)

`RD_SIGN_PROVIDER` = `AzureTrustedSigning` | `DigiCertKeyLocker` | `SSLcomESigner`, plus:

- Azure: `RD_AZURE_TS_ENDPOINT`, `RD_AZURE_TS_ACCOUNT`, `RD_AZURE_TS_PROFILE`,
  `RD_AZURE_TS_DLIB` (path to `Azure.CodeSigning.Dlib.dll`, NuGet
  `Microsoft.Trusted.Signing.Client`), `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
  `AZURE_CLIENT_SECRET` (service principal with "Trusted Signing Certificate Profile Signer").
- DigiCert: `SM_HOST`, `SM_API_KEY`, `SM_CLIENT_CERT_FILE`, `SM_CLIENT_CERT_PASSWORD`,
  `RD_DIGICERT_KEYPAIR_ALIAS`, and `RD_DIGICERT_CERT_FILE` (public .crt) or
  `RD_DIGICERT_CERT_SHA1`. Install KeyLocker Tools (smctl + KSP) first.
- SSL.com: `ES_USERNAME`, `ES_PASSWORD`, `ES_CREDENTIAL_ID`, `ES_TOTP_SECRET`,
  `RD_CODESIGNTOOL` (path to `CodeSignTool.bat`; needs Java).
- Optional: `RD_SIGNTOOL`, `RD_TIMESTAMP_URL`, `RD_SIGN_DESCRIPTION`, `RD_SIGN_URL`.

### Commands

```powershell
cd desktop-apps\package
.\sign\Sign.ps1 -Path build\x64\desktop -DryRun   # what will be signed / skipped, env check
.\make.ps1 -Version 2026.2.0.0 -Arch x64 -Sign     # signs every .exe/.dll of the payload
.\make_inno.ps1 -Version 2026.2.0.0 -Arch x64 -Sign   # setup.exe and its uninstaller
.\make_advinst.ps1 -Version 2026.2.0.0 -Arch x64 -Sign   # the .msi (#2372)
# independent checks
signtool verify /pa /v <installer>.exe
signtool verify /pa /v <package>.msi
Get-AuthenticodeSignature <file> | Format-List Status, SignerCertificate, TimeStamperCertificate
```

`Sign.ps1 -File a.exe,b.msi` signs individual files. Files with a valid signature already
(VC++ runtime, earlier runs) are skipped unless `-Force`.

Not yet exercised: `Sign.ps1` has never run (no Windows machine or PowerShell in this
cycle), and the Windows build itself still has to be compiled first (RELEASE_NOTES).
Do a `-DryRun` and a signing run on a test build before the release.

## Release manager checklist

Before the release:
- [ ] Certificates/keys exist and are in the CI secret stores (macOS keychain + API key;
      Windows provider credentials). Expiry dates noted in the team calendar.
- [ ] `security find-identity -v -p codesigning "$RD_KEYCHAIN"` lists both Developer ID identities.
- [ ] Windows: `Sign.ps1 -Path build\x64\desktop -DryRun` shows "all required variables
      are set" and the expected file list.
- [ ] Version/build numbers final (signing must be the last change to the binaries).

Per macOS architecture:
- [ ] `sign_and_notarize.sh --app ... --pkg` exits 0; log shows "all N Mach-O files:
      runtime, timestamp OK", notarization "Accepted", stapled.
- [ ] `spctl --assess` accepted, source=Notarized Developer ID.
- [ ] DMG built from the stapled app, then `sign_and_notarize.sh --dmg ...` exits 0.
- [ ] Smoke test on a clean Mac (or new user) from the downloaded DMG, quarantine intact:
      opens without a Gatekeeper prompt beyond "downloaded from the Internet"; open and save a
      docx, xlsx, pptx and a PDF.

Windows (x64, then arm64/x86 if shipped):
- [ ] `make.ps1 -Sign`, `make_inno.ps1 -Sign`, `make_advinst.ps1 -Sign` all exit 0, each
      ending with "signed and verified N file(s)".
- [ ] `signtool verify /pa` passes on the .exe and .msi; the UAC prompt shows the publisher
      (not "Unknown publisher") on a clean VM.
- [ ] SmartScreen: an OV certificate starts with no reputation; expect warnings until it
      builds up (EV/Trusted Signing are treated the same now).

After:
- [ ] Publish SHA-256 sums beside the artefacts as before; RELEASE_NOTES no longer says
      "not signed" for the platforms that are.
- [ ] Remove the RELEASE_NOTES quarantine instructions for signed platforms.
- [ ] Nothing secret in the build logs that are kept (grep for key IDs/passwords).
