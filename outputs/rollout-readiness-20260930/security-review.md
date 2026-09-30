# Container security review — 2026-09-30

**Release security remains blocked by five HIGH package findings across three CVEs.** No supported Debian trixie package fix is currently published for these findings. Rebuilding an unchanged apt layer cannot be claimed to resolve them. No Dockerfile, base digest, dependency lock, scanner threshold or ignore list was changed.

## Verified evidence

[CI run 36779785629](https://github.com/zandemha2025/cadverify/actions/runs/36779785629) has branch head `772f3b56233789b036dba1f16c0bc77613043db1`. Its container artifact records built PR merge SHA `2622bbe861b9ff0889d53e8c5b0535ccf0ca86ee`; these are different source identities. Backend image ID is `sha256:903d43ee9001e0f5700688380b19c2f02f0e1888f2aedf552a7afab955a26e18`.

Artifact `11128216218` contains the image manifest and CycloneDX inventories. The five installed versions below were confirmed independently in that backend inventory and the failing scan log. `security-evidence.json` preserves artifact/SBOM hashes, source identities and CI step outcomes; `security-ci-excerpt.txt` preserves the relevant scan table and executed STEP success message.

| Installed package | Installed version | CVE | Official Debian status checked today |
| --- | --- | --- | --- |
| libexpat1 | 2.8.3-1~deb13u1 | CVE-2026-93990 | Trixie/security vulnerable; first fix is unstable 2.8.4-2 |
| libx11-6 | 2:1.8.12-1 | CVE-2026-88806 | Trixie vulnerable; unstable also unfixed |
| libx11-data | 2:1.8.12-1 | CVE-2026-88806 | Same source package |
| libx11-xcb1 | 2:1.8.12-1 | CVE-2026-88806 | Same source package |
| libxrender1 | 1:0.9.12-1 | CVE-2026-88807 | Trixie vulnerable; unstable also unfixed |

The scan's fixed-version cells are empty. Debian marks the X11/Xrender trixie issues `no-dsa (Minor issue)`; that classification does not satisfy this repository's HIGH/CRITICAL gate. Sources: [Expat tracker](https://security-tracker.debian.org/tracker/CVE-2026-93990), [X11 tracker](https://security-tracker.debian.org/tracker/CVE-2026-88806), [Xrender tracker](https://security-tracker.debian.org/tracker/CVE-2026-88807).

The existing backend apt layers were cached, but the absence of fixed stable packages is an independent blocker. Merely adding these packages to the upgrade list or invalidating the layer is not a demonstrated fix.

## Small alternatives assessed

The locked Gmsh version is 4.15.2. [Gmsh's official download page](https://gmsh.info/) offers no-X wheels as development snapshots; its [no-X package index](https://gmsh.info/python-packages-dev-nox/gmsh/) has no stable 4.15.2 equivalent and currently lists 5.0.0.dev20260927+nox. A parser/runtime substitution would require broader compatibility validation.

Removing Gmsh's GUI dependencies alone would not remove all affected packages: the installed [Debian libcairo2 package](https://packages.debian.org/trixie/libcairo2) also depends on libx11-6 and libxrender1, and [libfontconfig1](https://packages.debian.org/trixie/libfontconfig1) depends on libexpat1. Removing those shared libraries without changing their consumers would break the image. No development-wheel migration or unverified library backport was introduced.

## Checks and remaining work

- Existing actual-image CI checks passed: backend image build; frontend security scan; frontend default startup/1200×630 share PNG; backend native STEP parser with watertightness, 20×15×10 mm extents and bored-block analytic volume within 0.2 mm³; evidence upload.
- The actual backend image scan failed: five HIGH, zero CRITICAL after existing repository ignores. This is not an unfiltered zero-vulnerability claim.
- Local Docker was absent from PATH, but its installed client was found at `/Applications/Docker.app/Contents/Resources/bin/docker` (29.7.2). `docker version` could not reach the stopped daemon. No shared daemon was started and no local image build/scan was performed. No application code changed, so no redundant code tests were added.
- Closure requires a supported fixed package set or a separately proven compatible runtime change, followed by rebuilt-image HIGH/CRITICAL scans, SBOMs and the existing native STEP/startup checks on the final source revision. Preserve the failing gate until then. Production rollout and production retesting remain unperformed by this review.
