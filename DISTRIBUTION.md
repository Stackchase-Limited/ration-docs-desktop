# Distribution: GitHub holds the files, ration.works is the address

Release artefacts live as GitHub **Release assets** on a public repository, and every
public link the product shows goes through `ration.works`, which redirects.

## Why the indirection

The URLs below are **compiled into the binaries** — `win-linux/src/defines.h` for the
application, `desktop-apps/package/Makefile` for the deb metadata, `panelabout.js` for
the About box. Changing one means cutting a new release. Routing them through a domain
we control means the repository can be renamed, moved between orgs, or replaced by a
mirror without stranding every copy already installed.

It also fixes something that was wrong: the About box's *View Corresponding Source*
link pointed at `lab02.ration.works`, which asks for a sign-in. AGPL §6 requires that
recipients of a binary can **get** the corresponding source; a link only employees can
open names an offer without honouring it. `ration.works/source` must resolve, publicly
and without authentication, for the release to be compliant.

## The paths

| Path | Purpose | Where it appears |
|---|---|---|
| `/` | Product site | About box site link (`URL_SITE`) |
| `/downloads` | Downloads page: the application, its platforms, per-file links | `DOWNLOAD_PAGE` |
| `/releases` | Release notes / changelog | `RELEASE_NOTES`, About box changelog link |
| `/source` | **Corresponding source.** Must be public and unauthenticated | About box, deb `Source:` field |
| `/support` | Issues or support contact | deb `SUPPORT_URL` |

`/downloads` is a page rather than a direct file link, so one address covers every
platform and survives a version bump. Per-file links on that page can point straight at
the GitHub asset URLs, which are the form

    https://github.com/<org>/<repo>/releases/download/<tag>/<file>

and are anonymous-downloadable for a public repository.

## What still has to be set up

1. **The GitHub repository** — public, holding source and Releases. Not created yet:
   nothing has been pushed to GitHub from here, and nothing should be until the org and
   repository name are settled, because publishing source is not reversible.
2. **The redirects** on ration.works. The server was not known when this was written, so
   the mapping is recorded here rather than as a config file. Each is a 302 to the
   corresponding GitHub page, except `/downloads`, which is a page of ours.
3. **AGPL check before publishing binaries**: `/source` must serve the exact revision
   the binaries were built from. Tagging the release commit in the public repository and
   pointing `/source` at the tag is the simplest way to keep the two in step.

## Artefact sizes, for choosing where they go

| File | Size |
|---|---|
| `RationDocs-2026.1.0-arm64.dmg` (macOS) | 760 MB |
| Linux arm64 payload, uncompressed | 1.9 GB |

GitHub's limit is 2 GB per Release asset, so both fit; the Linux tar.xz and deb are well
under it. Release asset bandwidth is not counted against LFS or repository quotas.
