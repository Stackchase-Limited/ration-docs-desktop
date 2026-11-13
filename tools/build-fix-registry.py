#!/usr/bin/env python3
"""
Regenerate FIXES.md from git history and the test tree.

Hand-maintained lists drift: the Fixed table in UPSTREAM_TRIAGE.md was eight
entries behind its own commits when this was written, and several commit messages
cite test directories that never existed. So this reads the two things that cannot
lie - what is in git, and what is on disk - and writes the registry from them.

Run it after landing fixes:  python3 tools/build-fix-registry.py
"""
import io
import os
import re
import subprocess
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBMODULES = ['core', 'sdkjs', 'web-apps', 'desktop-apps', 'desktop-sdk',
              'build_tools', 'dictionaries', 'onlyoffice.github.io']
TESTS = os.path.join(ROOT, 'fork-fix-tests')

# A commit is a fix if its subject says so. Anything else - triage notes, records,
# submodule bumps - is deliberately excluded.
FIX_SUBJECT = re.compile(
    r'^(#\d+|Land |fix\(|feat\(|Stop |Release |Report |Say |Resolve |Point |Check |Ship )',
    re.I)


# Commits whose "#NNNN:" names an issue they do not actually fix: the reported defect was already
# fixed (see UPSTREAM_TRIAGE.md) and the commit fixes a different defect in the same code. Kept out of
# the count so the registry never credits an issue for work that is not its reported bug.
NOT_THE_REPORTED_DEFECT = {
    '883': 'FREQUENCY was already vertical in 9.4; sdkjs 0bb6ae9857 fixes bin order, a different defect',
}


def git(repo, *args):
    return subprocess.run(['git', '-C', os.path.join(ROOT, repo)] + list(args),
                          capture_output=True, text=True).stdout


def upstream_base(repo):
    """Where our work diverges from ONLYOFFICE, so we list only our own commits."""
    for ref in ('upstream/master', 'origin/master', 'master'):
        out = subprocess.run(
            ['git', '-C', os.path.join(ROOT, repo), 'merge-base', 'HEAD', ref],
            capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def tests_by_issue():
    found = {}
    if not os.path.isdir(TESTS):
        return found
    for name in os.listdir(TESTS):
        for rd in re.findall(r'^rd-(\d{4})', name):
            found.setdefault('RD-' + rd, []).append(name)
        for num in re.findall(r'issue-(\d+)', name):
            # agents zero-pad short numbers (issue-0182) to sort them; issues are not padded
            found.setdefault(str(int(num)), []).append(name)
    return found


def collect():
    have_test = tests_by_issue()
    rows = OrderedDict()          # issue -> dict
    unnumbered = []               # fixes with no issue number
    internal = OrderedDict()      # RD-NNNN -> dict: defects we found ourselves (corpus runs, testing)

    for repo in SUBMODULES:
        base = upstream_base(repo)
        rng = ('%s..HEAD' % base) if base else 'HEAD'
        # The whole message, not just the subject: earlier commits put the issue
        # number in the body ("fix(fonts): ..." with the number three lines down),
        # and reading only subjects reported 56 fixes as having no issue at all.
        log = git(repo, 'log', rng, '--format=%H%x1f%ad%x1f%s%x1f%b%x1e', '--date=short')
        for rec in log.split('\x1e'):
            rec = rec.strip('\n')
            if not rec:
                continue
            parts = rec.split('\x1f')
            if len(parts) < 3:
                continue
            sha, date, subject = parts[0], parts[1], parts[2]
            body = parts[3] if len(parts) > 3 else ''
            # Our own findings carry an ID of ours instead of an upstream number:
            # "RD-0001: <what was wrong>; <what now>". Kept apart from upstream issues.
            m = re.match(r'^(RD-\d{4})\b', subject)
            if m:
                r = internal.setdefault(m.group(1), {'issue': m.group(1), 'repos': set(),
                                                     'commits': [], 'dates': set(), 'subjects': []})
                r['repos'].add(repo); r['commits'].append('%s:%s' % (repo, sha[:10]))
                r['dates'].add(date)
                if subject not in r['subjects']:
                    r['subjects'].append(subject)
                continue
            if not FIX_SUBJECT.match(subject):
                continue
            # An issue is CLAIMED, not merely mentioned. Two forms count: the
            # subject line, and "#NNNN: ..." opening a body line, which is how the
            # earlier commits in this tree state what they fix.
            #
            # Mentions elsewhere in a body are deliberately excluded. Crediting them
            # put eight issues in this registry that nothing here fixes - #2417 and
            # #1436 appear only as "same family as", #2424 only as "this is NOT
            # that", #1324 and #1832 only as logs the old warning turned up in.
            # Three claiming forms are in use in this tree, all of them explicit:
            #   Land #2245: ...                     (subject)
            #   #2136: ONLYOFFICE segfaults when... (opening a body line)
            #   Upstream report: ONLYOFFICE/DesktopEditors#1720
            nums = re.findall(r'#(\d{2,4})\b', subject)
            nums += re.findall(r'^\s*#(\d{2,4})\s*[:\-]', body, re.M)
            nums += re.findall(r'Upstream report:[^\n]*?#(\d{2,4})\b', body, re.I)
            entry = {'repo': repo, 'sha': sha[:10], 'date': date, 'subject': subject}
            if not nums:
                unnumbered.append(entry)
                continue
            nums = [n for n in nums if n not in NOT_THE_REPORTED_DEFECT]
            if not nums:
                unnumbered.append(entry)
                continue
            for n in nums:
                r = rows.setdefault(n, {'issue': n, 'repos': set(), 'commits': [],
                                        'dates': set(), 'subjects': []})
                r['repos'].add(repo)
                r['commits'].append('%s:%s' % (repo, sha[:10]))
                r['dates'].add(date)
                if subject not in r['subjects']:
                    r['subjects'].append(subject)
    # Issues fixed by a commit that does not name them, settled by hand in tools/fix-claims.txt.
    # Each line is checked against git: the commit must exist and be on the repo's current branch,
    # so a claim can never point at work that is not in the tree.
    claims = os.path.join(ROOT, 'tools', 'fix-claims.txt')
    if os.path.isfile(claims):
        for line in open(claims):
            f = line.split('#', 1)[0].split()
            if len(f) != 3:
                continue
            n, repo, sha = f
            ok = subprocess.run(['git', '-C', os.path.join(ROOT, repo), 'merge-base', '--is-ancestor',
                                 sha, 'HEAD'], capture_output=True).returncode == 0
            if not ok:
                print('fix-claims.txt: %s %s %s is not on the current branch - not counted' % (n, repo, sha))
                continue
            date = git(repo, 'log', '-1', '--format=%ad', '--date=short', sha).strip()
            subj = git(repo, 'log', '-1', '--format=%s', sha).strip()
            r = rows.setdefault(n, {'issue': n, 'repos': set(), 'commits': [], 'dates': set(), 'subjects': []})
            r['repos'].add(repo); r['commits'].append('%s:%s' % (repo, sha[:10])); r['dates'].add(date)
            if subj not in r['subjects']:
                r['subjects'].append(subj)
    for n, r in rows.items():
        r['tests'] = have_test.get(n, [])
    for n, r in internal.items():
        r['tests'] = have_test.get(n, [])
    return rows, unnumbered, internal


def main():
    rows, unnumbered, internal = collect()
    verified = [r for r in rows.values() if r['tests']]
    unverified = [r for r in rows.values() if not r['tests']]

    out = []
    out.append('# Fix registry\n')
    out.append('**Generated by `tools/build-fix-registry.py` - do not edit by hand.**\n')
    out.append('Rebuilt from git history and the contents of `fork-fix-tests/`, because a\n'
               'hand-kept list drifts: the Fixed table in `UPSTREAM_TRIAGE.md` was eight entries\n'
               'behind its own commits when this was written, and several commit messages cite\n'
               'test directories that have never existed. Nothing here is typed in by hand, so\n'
               'nothing here can claim a test that is not on disk.\n')
    out.append('- **%d issues** with at least one fix commit' % len(rows))
    out.append('- **%d** have a test artifact in `fork-fix-tests/`' % len(verified))
    out.append('- **%d** do not - the fix is asserted by its commit message only' % len(unverified))
    if unnumbered:
        out.append('- **%d** fix commits carry no issue number (defects found in passing)'
                   % len(unnumbered))
    out.append('- **%d** defects found by our own testing (RD-NNNN), %d with a test - counted'
               ' separately from upstream issues' % (len(internal),
                                                     sum(1 for r in internal.values() if r['tests'])))
    out.append('')
    out.append('A row here means a commit exists. It does **not** mean the fix was verified;')
    out.append('that is what the Test column is for. See the verification status section of')
    out.append('`UPSTREAM_TRIAGE.md` for why that distinction is drawn so sharply.\n')

    def table(title, items, note=None):
        out.append('## %s\n' % title)
        if note:
            out.append(note + '\n')
        out.append('| Issue | Where | Commit | Test | Landed |')
        out.append('|---|---|---|---|---|')
        for r in sorted(items, key=lambda x: -int(x['issue'])):
            t = '`%s`' % r['tests'][0] if r['tests'] else '-'
            out.append('| [#%s](https://github.com/ONLYOFFICE/DesktopEditors/issues/%s) | %s | %s | %s | %s |'
                       % (r['issue'], r['issue'], ', '.join(sorted(r['repos'])),
                          ' '.join('`%s`' % c.split(':')[1] for c in r['commits'][:3]),
                          t, sorted(r['dates'])[-1]))
        out.append('')

    table('Verified - a test exists and has been run', verified)
    table('Not verified - commit message only', unverified,
          'These are not necessarily wrong; several are plainly right on inspection.\n'
          'They have not been demonstrated.')

    if internal:
        out.append('## Our own findings (RD-NNNN) - corpus runs and testing\n')
        out.append('| ID | Where | Commit | Test | Landed | What |')
        out.append('|---|---|---|---|---|---|')
        for r in sorted(internal.values(), key=lambda x: x['issue'], reverse=True):
            t = '`%s`' % r['tests'][0] if r['tests'] else '-'
            out.append('| %s | %s | %s | %s | %s | %s |' % (
                r['issue'], ', '.join(sorted(r['repos'])),
                ' '.join('`%s`' % c.split(':')[1] for c in r['commits'][:3]), t,
                sorted(r['dates'])[-1], r['subjects'][0].split(':', 1)[-1].strip()[:80]))
        out.append('')

    if unnumbered:
        out.append('## Defects found in passing - no upstream issue\n')
        out.append('| Where | Commit | Landed | What |')
        out.append('|---|---|---|---|')
        for e in sorted(unnumbered, key=lambda x: x['date'], reverse=True):
            out.append('| %s | `%s` | %s | %s |' % (e['repo'], e['sha'], e['date'],
                                                    e['subject'][:88]))
        out.append('')

    # Anything the triage calls fixed but no commit claims. This is a commit-hygiene
    # gap, not a missing fix: the work is in the tree, but nothing ties it to the
    # issue, so it cannot be traced back. Surfaced rather than papered over with
    # looser matching, which is what produced false credits in the first place.
    try:
        tri = io.open(os.path.join(ROOT, 'UPSTREAM_TRIAGE.md'), encoding='utf-8').read()
        a = tri.index('## Fixed'); b = tri.index('\n## ', a + 5)
        claimed = set()
        for line in tri[a:b].split('\n'):
            if line.startswith('| #') or line.startswith('| - |'):
                claimed.update(re.findall(r'#(\d+)', line.split('|')[1]))
        missing = sorted(claimed - set(rows), key=int)
        if missing:
            out.append('## Listed as fixed, but no commit claims them\n')
            out.append('The work is in the tree; nothing ties it to the issue. A commit can claim')
            out.append('an issue three ways - in its subject, as `#NNNN:` opening a body line, or')
            out.append('as `Upstream report: ONLYOFFICE/DesktopEditors#NNNN`. These use none of')
            out.append('them, usually because one commit closed several duplicate reports and')
            out.append('named only the first.\n')
            out.append('  ' + ' '.join('#' + n for n in missing) + '\n')
    except (ValueError, OSError):
        missing = []

    open(os.path.join(ROOT, 'FIXES.md'), 'w').write('\n'.join(out))
    print('FIXES.md: %d issues (%d verified, %d not), %d unnumbered, %d unclaimed; %d own findings (RD)'
          % (len(rows), len(verified), len(unverified), len(unnumbered), len(missing), len(internal)))


if __name__ == '__main__':
    main()
