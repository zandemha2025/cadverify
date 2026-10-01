#!/bin/sh
# Actual upstream remediation, not a vulnerability waiver. See native-fixes.vex.json.
set -eu
mkdir -p /patched
for spec in expat=2.8.5-2 libx11=2:1.8.12-1 libxrender=1:0.9.12-1; do
    name=${spec%%=*}
    version=${spec#*=}
    mkdir -p "/build/$name"
    cd "/build/$name"
    apt-get source "$spec"
    cd "$name-"*/
    case "$name" in
        libx11) patch --fuzz=0 -p1 < /patches/x11.patch ;;
        libxrender) patch --fuzz=0 -p1 < /patches/xrender.patch ;;
    esac
    # The local revision identifies exactly these patched binaries in the SBOM.
    python - "$name" "$version" <<'PY'
import pathlib
import sys
name, version = sys.argv[1:]
p = pathlib.Path('debian/changelog')
p.write_text(f'''{name} ({version}+cadverify1) unstable; urgency=high

  * Rebuild with upstream fixes for the CadVerify production image.

 -- CadVerify <security@cadverify.invalid>  Thu, 01 Oct 2026 16:00:00 +0000

''' + p.read_text())
PY
    # Keep the packages' native test suites enabled.
    dpkg-buildpackage -us -uc -b -j2
done
cp /build/expat/libexpat1_*_*.deb /patched/
cp /build/libx11/libx11-6_*_*.deb /build/libx11/libx11-data_*_all.deb \
    /build/libx11/libx11-xcb1_*_*.deb /patched/
cp /build/libxrender/libxrender1_*_*.deb /patched/
