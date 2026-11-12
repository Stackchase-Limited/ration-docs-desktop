/*
 * #780 - "Support for vector graphic images" (Insert > Image from file).
 *
 * The engine already inserts EMF and WMF pictures as vectors: desktop-sdk
 * client_renderer_wrapper.cpp GetLocalImageUrlLocal accepts them through
 * CImageFileFormatChecker, copies the metafile to media/ and renders it with
 * MetaFile::ConvertToSvg (checked by running core's graphics.framework on a small
 * EMF and a WMF: both recognised, both converted to SVG). SVG was already offered.
 * The dialogs did not offer metafiles: the macOS open panel allows only
 * [ASCConstants images] (no emf/wmf - they could not be chosen at all), and the
 * Windows/Linux "All Images" filter had no *.emf/*.wmf (only "All files" reached them).
 *
 * This test reads the REAL sources: the ASCConstants `images` array literal and the
 * bodies of CFileDialogWrapper::modalOpenImage/modalOpenImages (brace matching), and
 * checks that every image dialog lists emf and wmf, and that the formats offered
 * before are still offered.
 *
 * NOT claimed: no dialog is shown, no picture is inserted in a running editor
 * (needs a GUI check); PDF/EPS as pictures (also asked in the thread) are not
 * supported by the engine and are not tested.
 *
 *   node issue-780-insert-metafile-test.js             -> passes
 *   BASELINE=1 node issue-780-insert-metafile-test.js  -> fails
 * RD_REPO=<desktop-apps checkout>, BASE_REF=<ref> (default: the fix commit's parent).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const REPO = process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps');
const BASE_REF = process.env.BASE_REF || 'a52f7eca4^';
const MAC = 'macos/ONLYOFFICE/Code/Utils/ASCConstants.m';
const QT = 'win-linux/src/components/cfiledialog.cpp';

function read(rel) {
    if (process.env.BASELINE)
        return execFileSync('git', ['-C', REPO, 'show', BASE_REF + ':' + rel], { encoding: 'utf8' });
    return fs.readFileSync(path.join(REPO, rel), 'utf8');
}

function body(src, head) {
    const i = src.indexOf(head);
    if (i < 0) throw new Error('not found: ' + head);
    let j = src.indexOf('{', i), depth = 0;
    for (let k = j; k < src.length; ++k) {
        if (src[k] === '{') ++depth;
        else if (src[k] === '}' && --depth === 0) return src.slice(j, k + 1);
    }
    throw new Error('unbalanced: ' + head);
}

let failed = 0;
function check(ok, what) {
    console.log((ok ? 'ok   ' : 'FAIL ') + what);
    if (!ok) ++failed;
}

// macOS: the array the open panel gets as allowedFileTypes
const mac = body(read(MAC), '+ (NSArray *)images');
const arr = /@\[([^\]]*)\]/.exec(mac);
const macTypes = arr ? arr[1].match(/@"([^"]+)"/g).map(s => s.slice(2, -1)) : [];
for (const ext of ['jpg', 'png', 'gif', 'bmp', 'tiff', 'heic', 'svg', 'emf', 'wmf'])
    check(macTypes.includes(ext), 'macOS image panel allows .' + ext);

// Windows/Linux: the filter list of both image dialogs
const qt = read(QT);
for (const fn of ['QStringList CFileDialogWrapper::modalOpenImage(', 'QStringList CFileDialogWrapper::modalOpenImages(']) {
    const b = body(qt, fn);
    const all = /tr\("All Images"\)\s*\+\s*"\s*\(([^)]*)\)/.exec(b);
    const pats = all ? all[1].split(/\s+/) : [];
    const name = fn.slice(fn.indexOf('::') + 2, -1);
    for (const ext of ['jpg', 'png', 'gif', 'bmp', 'svg', 'emf', 'wmf'])
        check(pats.includes('*.' + ext), name + ' "All Images" has *.' + ext);
    check(b.includes('AVS_OFFICESTUDIO_FILE_UNKNOWN'), name + ' still offers All files');
}

console.log(failed ? failed + ' check(s) FAILED' : 'PASS: EMF/WMF are offered by every image file dialog');
process.exit(failed ? 1 : 0);
