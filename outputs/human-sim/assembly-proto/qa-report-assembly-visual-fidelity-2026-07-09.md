# Assembly Visual Fidelity

- Run: 2026-07-09
- Status: PASS
- Fixtures: 1
- Boundary: This proves deterministic assembly/context population for synthetic customer-like fixtures: parent assembly identity, part identity, coordinate system, declared service environment, part-to-parent transform, browser WebGL render health, and visual change from exploded to seated state. It is not customer proprietary CAD, native CAD certification, vendor certification, or live customer signoff.

## Fixture Cases

| Result | Fixture | Parent Assembly | Part | Steps | Evidence |
| --- | --- | --- | --- | ---: | --- |
| PASS | DOOR-HANDLE-ASSEMBLY-FIDELITY-001 | front-left-door-shell | exterior-door-handle | 4 | pass |

## Step Evidence

| Fixture | Result | Step | Duration ms | Evidence |
| --- | --- | --- | ---: | --- |
| DOOR-HANDLE-ASSEMBLY-FIDELITY-001 | pass | assembly fixture declares parent, part, coordinate system, and environment | 0 | {"parentAssembly":"front-left-door-shell","parentKind":"automotive-door-outer-panel","part":"exterior-door-handle","partKind":"pull-handle","coordinateSystem":{"units":"mm","x":"door width, hinge side negative and latch  |
| DOOR-HANDLE-ASSEMBLY-FIDELITY-001 | pass | browser renders exploded and seated populated-context states | 1340 | {"screenshotBytes":{"before":106105,"after":101264},"beforePixelHash":"535dc814","afterPixelHash":"deee344b","visualDelta":{"changedSampledPixels":3792,"samples":64800,"meanDelta":8}} |
| DOOR-HANDLE-ASSEMBLY-FIDELITY-001 | pass | part seats into parent assembly within transform tolerance | 0 | {"anchorErrors":[{"id":"front-mount-left","transformedMm":[188,-120,25.5],"targetMm":[188,-120,25.5],"errorMm":0},{"id":"front-mount-right","transformedMm":[332,-120,25.5],"targetMm":[332,-120,25.5],"errorMm":0}],"maxAnc |
| DOOR-HANDLE-ASSEMBLY-FIDELITY-001 | pass | seated canvas has nonblank cinematic and part-specific pixel evidence | 0 | {"before":{"label":"exploded-preview","width":960,"height":540,"pixelHash":"535dc814","handleCenter":{"x":522,"y":270,"ndc":[0.0866,0,0.9915]},"doorCenter":{"x":525,"y":266,"ndc":[0.0936,-0.0148,0.9917]},"full":{"count": |

## Screenshots

- DOOR-HANDLE-ASSEMBLY-FIDELITY-001 before: /home/user/cadverify/outputs/human-sim/assembly-proto/screenshots/assembly-visual-fidelity-2026-07-09/01-door-handle-assembly-fidelity-001-exploded-preview.png
- DOOR-HANDLE-ASSEMBLY-FIDELITY-001 after: /home/user/cadverify/outputs/human-sim/assembly-proto/screenshots/assembly-visual-fidelity-2026-07-09/02-door-handle-assembly-fidelity-001-seated-in-parent.png

## Failed

```json
[]
```
