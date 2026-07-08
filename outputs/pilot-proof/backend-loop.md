# CadVerify backend-loop proof transcript

Run at: 2026-07-04 20:31:05 EDT
Backend: http://127.0.0.1:8000  (fresh uvicorn, current HEAD)
Test part: `test_cube.stl` — trimesh-generated 50x40x30mm watertight box

Computed mesh_hash (sha256 of file bytes, matches `compute_mesh_hash`): `97064d08a95658cc160677cd0add4ae22098db38b1a86e890bc03c207c7e4485`

### Signup a real analyst (email+password)

`POST http://127.0.0.1:8000/auth/signup` -> **200**

```json
{
  "user": {
    "id": 21,
    "email": "pilot-proof-1783211465@cadverify-pilotproof.test",
    "role": "analyst"
  },
  "session": "MjEuMTc4MzIxMTQ2Ng.XTeoBjiB3IsCN-SBULis_g"
}
```
- **ASSERT [PASS]** signup returns 200
- **ASSERT [PASS]** new user has role=analyst

### Confirm session via /auth/me

`GET http://127.0.0.1:8000/auth/me` -> **200**

```json
{
  "id": 21,
  "email": "pilot-proof-1783211465@cadverify-pilotproof.test",
  "role": "analyst",
  "auth_provider": "password"
}
```
- **ASSERT [PASS]** /auth/me returns 200 with the session cookie

### POST /api/v1/validate (routing + DFM)

`POST http://127.0.0.1:8000/api/v1/validate` -> **200**

```json
{
  "filename": "test_cube.stl",
  "file_type": "stl",
  "overall_verdict": "issues",
  "best_process": "dlp",
  "analysis_time_ms": 5.2,
  "geometry": {
    "vertices": 8,
    "faces": 12,
    "volume_mm3": 60000.0,
    "surface_area_mm2": 9400.0,
    "bounding_box_mm": [
      50.0,
      40.0,
      30.0
    ],
    "is_watertight": true,
    "is_manifold": true,
    "center_of_mass": [
      0.0,
      0.0,
      0.0
    ],
    "units": "mm"
  },
  "segments": [],
  "features": [
    {
      "kind": "flat",
      "face_count": 2,
      "centroid": [
        -25.0,
        0.0,
        0.0
      ],
      "radius": null,
      "depth": null,
      "area": 1200.0,
      "confidence": 0.98
    },
    {
      "kind": "flat",
      "face_count": 2,
      "centroid": [
        0.0,
        -20.0,
        0.0
      ],
      "radius": null,
      "depth": null,
      "area": 1500.0,
      "confidence": 0.98
    },
    {
      "kind": "flat",
      "face_count": 2,
      "centroid": [
        0.0,
        0.0,
        -15.0
      ],
      "radius": null,
      "depth": null,
      "area": 2000.0,
      "confidence": 0.98
    },
    {
      "kind": "flat",
      "face_count": 2,
      "centroid": [
        0.0,
        0.0,
        15.0
      ],
      "radius": null,
      "depth": null,
      "area": 2000.0,
      "confidence": 0.98
    },
    {
      "kind": "flat",
      "face_count": 2,
      "centroid": [
        0.0,
        20.0,
        0.0
      ],
      "radius": null,
      "depth": null,
      "area": 1500.0,
      "confidence": 0.98
    },
    {
      "kind": "flat",
      "face_count": 2,
      "centroid": [
        25.0,
        0.0,
        0.0
      ],
      "radius": null,
      "depth": null,
      "area": 1200.0,
      "confidence": 0.98
    }
  ],
  "universal_issues": [],
  "process_scores": [
    {
      "process": "dlp",
      "score": 1.0,
      "verdict": "issues",
      "recommended_material": "Standard Resin",
      "recommended_machine": "Carbon M2",
      "estimated_cost_factor": 7.2,
      "standards": [
        "Carbon DLS Design Guide (2024)",
        "Elegoo Saturn 4 Ultra specifications"
      ],
      "issues": [
        {
          "code": "OVERHANG",
          "severity": "warning",
          "message": "2 faces (16.7%) exceed 30.0\u00b0 overhang threshold for dlp. Supports required.",
          "fix_suggestion": "Reorient part or redesign overhangs < 30.0\u00b0 for dlp. DLP typically 30\u00b0 from vertical.",
          "process": "dlp",
          "affected_face_count": 2,
          "affected_faces_sample": [
            3,
            8
          ],
          "region_center": [
            0.0,
            0.0,
            -15.0
          ],
          "citation": {
            "text": "DLP typically 30\u00b0 from vertical."
          },
          "scope": "localized"
        }
      ]
    },
    {
      "process": "sls",
      "score": 1.0,
      "verdict": "pass",
      "recommended_material": "PA12 (Nylon 12)",
      "recommended_machine": "EOS P 396",
      "estimated_cost_factor": 12.0,
      "standards": [
        "EOS PA12 material data sheet",
        "HP MJF Design Guide \u00a74 (powder removal)",
        "ISO/ASTM 52910:2018"
      ],
      "issues": []
    },
    {
      "process": "mjf",
      "score": 1.0,
      "verdict": "pass",
      "recommended_material": "PA12 (Nylon 12)",
      "recommended_machine": "HP Jet Fusion 5200",
      "estimated_cost_factor": 10.8,
      "standards": [
        "HP MJF Design Guide v5.0 (2024)",
        "HP Jet Fusion 5200 specifications"
      ],
      "issues": []
    },
    {
      "process": "binder_jetting",
      "score": 1.0,
      "verdict": "pass",
      "recommended_material": "SS316L",
      "recommended_machine": "ExOne S-Max Pro",
      "estimated_cost_factor": 48.0,
      "standards": [
        "ExOne S-Max Pro specifications",
        "Desktop Metal Shop System Design Guide"
      ],
      "issues": [
        {
          "code": "SINTERING_SHRINKAGE",
          "severity": "info",
          "message": "Binder jetting parts shrink 15-20% during sintering. Ensure CAD model is scaled to compensate.",
          "fix_suggestion": "Scale model 1.18\u20131.22x to compensate for sintering shrinkage. Desktop Metal Studio pre-compensates automatically.",
          "process": "binder_jetting",
          "scope": "whole_part"
        }
      ]
    },
    {
      "process": "cnc_3axis",
      "score": 1.0,
      "verdict": "pass",
      "recommended_material": "Inconel 718",
      "recommended_machine": "Haas VF-2",
      "estimated_cost_factor": 6.0,
      "standards": [
        "Sandvik Coromant Machining Guide (2024)",
        "ASME Y14.5-2018 \u2014 GD&T",
        "Haas VF-2 specifications"
      ],
      "issues": []
    },
    {
      "process": "cnc_5axis",
      "score": 1.0,
      "verdict": "pass",
      "recommended_material": "Inconel 718",
      "recommended_machine": "DMG MORI DMU 50",
      "estimated_cost_factor": 15.0,
      "standards": [
        "DMG MORI DMU 50 specifications",
        "Sandvik Coromant Machining Guide (2024)",
        "ASME Y14.5-2018"
      ],
      "issues": []
    },
    {
      "process": "wire_edm",
      "score": 1.0,
      "verdict": "pass",
      "recommended_material": "API 13Cr",
      "recommended_machine": "Sodick ALC600G",
      "estimated_cost_factor": 30.0,
      "standards": [
        "Sodick ALC600G specifications",
        "Mitsubishi Electric wire EDM design guide"
      ],
      "issues": [
        {
          "code": "CONDUCTIVITY_REQUIRED",
          "severity": "info",
          "message": "Wire EDM requires electrically conductive material.",
          "fix_suggestion": "Verify material is conductive (metals only). Ceramics / polymers cannot be wire-EDM'd.",
          "process": "wire_edm",
          "scope": "whole_part"
        }
      ]
    },
    {
      "process": "fdm",
      "score": 0.9,
      "verdict": "issues",
      "recommended_material"
... [truncated for transcript] ...
```
- **ASSERT [PASS]** /validate returns 200
- **ASSERT [PASS]** /validate response carries geometry

### POST /api/v1/validate/cost (BEFORE any machine/environment declared)

`POST http://127.0.0.1:8000/api/v1/validate/cost` -> **200**

```json
{
  "filename": "test_cube.stl",
  "status": "OK",
  "reason": null,
  "geometry": {
    "volume_cm3": 60.0,
    "surface_area_cm2": 94.0,
    "bbox_mm": [
      50.0,
      40.0,
      30.0
    ],
    "watertight": true,
    "face_count": 12
  },
  "material_class": "steel",
  "quantities": [
    50,
    5000
  ],
  "estimates": [
    {
      "process": "forging",
      "material": "Mild Steel",
      "quantity": 50,
      "unit_cost_usd": 622.57,
      "fixed_cost_usd": 30000.0,
      "variable_cost_usd": 20.89,
      "est_error_band_pct": 55.0,
      "confidence": {
        "low_usd": 280.16,
        "high_usd": 964.99,
        "point_usd": 622.57,
        "level": 0.8,
        "method": "assumption-band",
        "validated": false,
        "n_samples": 0,
        "half_width_pct": 55.0,
        "basis": "\u00b155% stated assumption band (cycle-time / tooling defaults) propagated around the point estimate \u2014 no ground truth yet",
        "label": "assumption-based, not yet validated"
      },
      "dfm_ready": false,
      "dfm_verdict": "fail",
      "dfm_score": 0.0,
      "dfm_blockers": [
        "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging."
      ],
      "dfm_blocker_details": [
        {
          "code": "INSUFFICIENT_DRAFT",
          "severity": "error",
          "message": "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging.",
          "fix_suggestion": "Add >= 5.0\u00b0 draft to all walls in pull direction. FIA: 5\u00b0 external, 7-10\u00b0 internal.",
          "process": "forging",
          "affected_face_count": 8,
          "affected_faces_sample": [
            0,
            1,
            2,
            5,
            7,
            9,
            10,
            11
          ],
          "required_value": 5.0,
          "citation": {
            "standard": "FIA",
            "text": "5\u00b0 external, 7-10\u00b0 internal."
          },
          "scope": "localized"
        }
      ],
      "line_items": {
        "amortized_fixed": 602.1,
        "material": 0.9273,
        "machine": 12.5438,
        "labor": 7.0
      },
      "drivers": [
        {
          "name": "material_cost",
          "value": 0.9273,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "billet from bar = net 0.4710 kg (CAD volume 60.00 cm\u00b3 \u00d7 Mild Steel density 7.85 g/cm\u00b3) \u00d7 (1+0.25 flash/scale loss) [forge assumption, not shop-validated] = 0.5887 kg \u00d7 $1.5/kg (material-DB unit price (DEFAULT book value)) \u00d7 (1+0.05 scrap) \u00d7 region-material \u00d71",
          "error_band_pct": 5.0
        },
        {
          "name": "machine_cost",
          "value": 12.5438,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "0.1045 hr \u00d7 $120/hr \u00d7 region-labor \u00d71  [heat 0.589kg billet (net 0.471kg \u00d7 1+0.25 flash/scale) \u00d7 2.5min/kg = 1.5min + press 0.05hr + trim 0.03hr = 0.1045 hr  (near-net blank \u2014 finish machining NOT bundled) [forge assumption, not shop-validated]]",
          "error_band_pct": 55.0
        },
        {
          "name": "cycle_time",
          "value": 0.1045,
          "unit": "hr",
          "provenance": "DEFAULT",
          "source": "heat 0.589kg billet (net 0.471kg \u00d7 1+0.25 flash/scale) \u00d7 2.5min/kg = 1.5min + press 0.05hr + trim 0.03hr = 0.1045 hr  (near-net blank \u2014 finish machining NOT bundled) [forge assumption, not shop-validated]",
          "error_band_pct": 55.0
        },
        {
          "name": "labor_cost",
          "value": 7.0,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "post-process 0.2 hr \u00d7 $35/hr \u00d7 region-labor \u00d71",
          "error_band_pct": 20.0
        },
        {
          "name": "setup_cost",
          "value": 2.1,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "setup 3hr \u00d7 $35/hr \u00d7 ceil(50/250) = 1 setups \u00f7 50 \u00d7 region-labor \u00d71",
          "error_band_pct": 20.0
        },
        {
          "name": "tooling_cost",
          "value": 30000.0,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "hardened closed-die set: size tier M (max bbox 50mm) \u00d7 2 family-mult \u00d7 moderate (=1.00) = $30,000; \u00b155%, OVERRIDABLE [assumption, not shop-validated]",
          "error_band_pct": 55.0
        }
      ],
      "lead_time": {
        "low_days": 44.8,
        "high_days": 83.2,
        "mid_days": 64.0,
        "components": {
          "queue": 12.0,
          "tooling_lead": 45.0,
          "production": 1.0,
          "post_process": 3.0,
          "ship": 3.0
        },
        "capacity": {
          "n_machines": 2,
          "machine_hours_per_day": 16.0,
          "provenance": "DEFAULT",
          "basis": "capacity-bound: 2 machines \u00d7 16 hr/day parallel pool; production = ceil(50\u00b70.104hr \u00f7 (2\u00d716)) = 1 d"
        }
      }
    },
    {
      "process": "forging",
      "material": "Mild Steel",
      "quantity": 5000,
      "unit_cost_usd": 26.89,
      "fixed_cost_usd": 30000.0,
      "variable_cost_usd": 20.89,
      "est_error_band_pct": 55.0,
      "confidence": {
        "low_usd": 12.1,
        "high_usd": 41.68,
        "point_usd": 26.89,
        "level": 0.8,
        "method": "assumption-band",
        "validated": false,
        "n_samples": 0,
        "half_width_pct": 55.0,
        "basis": "\u00b155% stated assumption band (cycle-time / tooling defaults) propagated around the point estimate \u2014 no ground truth yet",
        "label": "assumption-based, not yet validated"
      },
      "dfm_ready": false,
      "dfm_verdict": "fail",
      "dfm_score": 0.0,
      "dfm_blockers": [
        "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging."
      ],
      "dfm_blocker_details": [
        {
          "code": "INSUFFICIENT_DRAFT",
          "se
... [truncated for transcript] ...
```
- **ASSERT [PASS]** /validate/cost returns 200
- **ASSERT [PASS]** decision.make_now_process is set (got 'cnc_3axis')

**make_now_process = `cnc_3axis`** (used below to declare a matching machine)
- **ASSERT [PASS]** at least one process estimate present
- **ASSERT [PASS]** unit_cost_usd (34.96) == Σ line_items (34.96) [byte-tight sum check, process=cnc_3axis qty=50]
- **ASSERT [PASS]** confidence.validated is False (n=0, honest)
- **ASSERT [PASS]** confidence.n_samples == 0 (no real ground truth yet)
- **ASSERT [PASS]** verification block ABSENT before any machine/environment is declared (no-op invariant)
- **ASSERT [PASS]** cost decision PERSISTED (saved.id present)

Persisted decision id: `01KWQTZ7B05X360R0M7PS7HRXG`

### POST /api/v1/machine-inventory (declare a cnc_3axis machine)

`POST http://127.0.0.1:8000/api/v1/machine-inventory` -> **201**

```json
{
  "id": "01KWQTZ7BHVQ9WPNDG14J7NY0T",
  "name": "Pilot-Proof Haas VF-2 (3-axis mill)",
  "process": "cnc_3axis",
  "count": 1,
  "max_workpiece_kg": 200.0,
  "hourly_rate_usd": 85.0,
  "capital_frac": 0.15,
  "capabilities": {
    "x": 500.0,
    "y": 400.0,
    "z": 500.0,
    "axes": 3
  },
  "materials": [
    "Mild Steel"
  ],
  "material_thickness_map": null,
  "notes": "Declared for backend-loop pilot proof (B2).",
  "provenance": "user",
  "created_at": "2026-07-05T00:31:06.096535+00:00",
  "updated_at": "2026-07-05T00:31:06.096535+00:00"
}
```
- **ASSERT [PASS]** machine declaration returns 201
- **ASSERT [PASS]** declared machine carries provenance=user

### GET /api/v1/machine-inventory (confirm it lists)

`GET http://127.0.0.1:8000/api/v1/machine-inventory` -> **200**

```json
{
  "machines": [
    {
      "id": "01KWQTZ7BHVQ9WPNDG14J7NY0T",
      "name": "Pilot-Proof Haas VF-2 (3-axis mill)",
      "process": "cnc_3axis",
      "count": 1,
      "max_workpiece_kg": 200.0,
      "hourly_rate_usd": 85.0,
      "capital_frac": 0.15,
      "capabilities": {
        "x": 500.0,
        "y": 400.0,
        "z": 500.0,
        "axes": 3
      },
      "materials": [
        "Mild Steel"
      ],
      "material_thickness_map": null,
      "notes": "Declared for backend-loop pilot proof (B2).",
      "provenance": "user",
      "created_at": "2026-07-05T00:31:06.096535+00:00",
      "updated_at": "2026-07-05T00:31:06.096535+00:00"
    }
  ],
  "next_cursor": null
}
```

### POST /api/v1/validate/cost (AFTER machine declared -> Phase C verification block)

`POST http://127.0.0.1:8000/api/v1/validate/cost` -> **200**

```json
{
  "filename": "test_cube.stl",
  "status": "OK",
  "reason": null,
  "geometry": {
    "volume_cm3": 60.0,
    "surface_area_cm2": 94.0,
    "bbox_mm": [
      50.0,
      40.0,
      30.0
    ],
    "watertight": true,
    "face_count": 12
  },
  "material_class": "steel",
  "quantities": [
    50,
    5000
  ],
  "estimates": [
    {
      "process": "forging",
      "material": "Mild Steel",
      "quantity": 50,
      "unit_cost_usd": 622.57,
      "fixed_cost_usd": 30000.0,
      "variable_cost_usd": 20.89,
      "est_error_band_pct": 55.0,
      "confidence": {
        "low_usd": 280.16,
        "high_usd": 964.99,
        "point_usd": 622.57,
        "level": 0.8,
        "method": "assumption-band",
        "validated": false,
        "n_samples": 0,
        "half_width_pct": 55.0,
        "basis": "\u00b155% stated assumption band (cycle-time / tooling defaults) propagated around the point estimate \u2014 no ground truth yet",
        "label": "assumption-based, not yet validated"
      },
      "dfm_ready": false,
      "dfm_verdict": "fail",
      "dfm_score": 0.0,
      "dfm_blockers": [
        "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging."
      ],
      "dfm_blocker_details": [
        {
          "code": "INSUFFICIENT_DRAFT",
          "severity": "error",
          "message": "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging.",
          "fix_suggestion": "Add >= 5.0\u00b0 draft to all walls in pull direction. FIA: 5\u00b0 external, 7-10\u00b0 internal.",
          "process": "forging",
          "affected_face_count": 8,
          "affected_faces_sample": [
            0,
            1,
            2,
            5,
            7,
            9,
            10,
            11
          ],
          "required_value": 5.0,
          "citation": {
            "standard": "FIA",
            "text": "5\u00b0 external, 7-10\u00b0 internal."
          },
          "scope": "localized"
        }
      ],
      "line_items": {
        "amortized_fixed": 602.1,
        "material": 0.9273,
        "machine": 12.5438,
        "labor": 7.0
      },
      "drivers": [
        {
          "name": "material_cost",
          "value": 0.9273,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "billet from bar = net 0.4710 kg (CAD volume 60.00 cm\u00b3 \u00d7 Mild Steel density 7.85 g/cm\u00b3) \u00d7 (1+0.25 flash/scale loss) [forge assumption, not shop-validated] = 0.5887 kg \u00d7 $1.5/kg (material-DB unit price (DEFAULT book value)) \u00d7 (1+0.05 scrap) \u00d7 region-material \u00d71",
          "error_band_pct": 5.0
        },
        {
          "name": "machine_cost",
          "value": 12.5438,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "0.1045 hr \u00d7 $120/hr \u00d7 region-labor \u00d71  [heat 0.589kg billet (net 0.471kg \u00d7 1+0.25 flash/scale) \u00d7 2.5min/kg = 1.5min + press 0.05hr + trim 0.03hr = 0.1045 hr  (near-net blank \u2014 finish machining NOT bundled) [forge assumption, not shop-validated]]",
          "error_band_pct": 55.0
        },
        {
          "name": "cycle_time",
          "value": 0.1045,
          "unit": "hr",
          "provenance": "DEFAULT",
          "source": "heat 0.589kg billet (net 0.471kg \u00d7 1+0.25 flash/scale) \u00d7 2.5min/kg = 1.5min + press 0.05hr + trim 0.03hr = 0.1045 hr  (near-net blank \u2014 finish machining NOT bundled) [forge assumption, not shop-validated]",
          "error_band_pct": 55.0
        },
        {
          "name": "labor_cost",
          "value": 7.0,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "post-process 0.2 hr \u00d7 $35/hr \u00d7 region-labor \u00d71",
          "error_band_pct": 20.0
        },
        {
          "name": "setup_cost",
          "value": 2.1,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "setup 3hr \u00d7 $35/hr \u00d7 ceil(50/250) = 1 setups \u00f7 50 \u00d7 region-labor \u00d71",
          "error_band_pct": 20.0
        },
        {
          "name": "tooling_cost",
          "value": 30000.0,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "hardened closed-die set: size tier M (max bbox 50mm) \u00d7 2 family-mult \u00d7 moderate (=1.00) = $30,000; \u00b155%, OVERRIDABLE [assumption, not shop-validated]",
          "error_band_pct": 55.0
        }
      ],
      "lead_time": {
        "low_days": 44.8,
        "high_days": 83.2,
        "mid_days": 64.0,
        "components": {
          "queue": 12.0,
          "tooling_lead": 45.0,
          "production": 1.0,
          "post_process": 3.0,
          "ship": 3.0
        },
        "capacity": {
          "n_machines": 2,
          "machine_hours_per_day": 16.0,
          "provenance": "DEFAULT",
          "basis": "capacity-bound: 2 machines \u00d7 16 hr/day parallel pool; production = ceil(50\u00b70.104hr \u00f7 (2\u00d716)) = 1 d"
        }
      }
    },
    {
      "process": "forging",
      "material": "Mild Steel",
      "quantity": 5000,
      "unit_cost_usd": 26.89,
      "fixed_cost_usd": 30000.0,
      "variable_cost_usd": 20.89,
      "est_error_band_pct": 55.0,
      "confidence": {
        "low_usd": 12.1,
        "high_usd": 41.68,
        "point_usd": 26.89,
        "level": 0.8,
        "method": "assumption-band",
        "validated": false,
        "n_samples": 0,
        "half_width_pct": 55.0,
        "basis": "\u00b155% stated assumption band (cycle-time / tooling defaults) propagated around the point estimate \u2014 no ground truth yet",
        "label": "assumption-based, not yet validated"
      },
      "dfm_ready": false,
      "dfm_verdict": "fail",
      "dfm_score": 0.0,
      "dfm_blockers": [
        "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging."
      ],
      "dfm_blocker_details": [
        {
          "code": "INSUFFICIENT_DRAFT",
          "se
... [truncated for transcript] ...
```
- **ASSERT [PASS]** /validate/cost returns 200
- **ASSERT [PASS]** verification block now PRESENT (machine declared)
- **ASSERT [PASS]** verification.inventory_declared == True
- **ASSERT [PASS]** verdict lattice populated (got 'makeable_in_house')
- **ASSERT [PASS]** per_route carries the cnc_3axis fit entry

Per-route `cnc_3axis` fit: verdict=`makeable_in_house`, machines_evaluated=1, best_machine=`Pilot-Proof Haas VF-2 (3-axis mill)`
- **ASSERT [PASS]** second cost decision persisted too

### PUT /api/v1/part-context/97064d08a95658cc160677cd0add4ae22098db38b1a86e890bc03c207c7e4485 (declare sour service environment)

`PUT http://127.0.0.1:8000/api/v1/part-context/97064d08a95658cc160677cd0add4ae22098db38b1a86e890bc03c207c7e4485` -> **200**

```json
{
  "mesh_hash": "97064d08a95658cc160677cd0add4ae22098db38b1a86e890bc03c207c7e4485",
  "program": null,
  "parent_assembly": null,
  "units_per_parent": null,
  "annual_volume": null,
  "provenance": "user",
  "service_environment": {
    "sour_service": true,
    "corrosive": true,
    "medium": "sour gas (H2S)",
    "standard": "NACE MR0175"
  }
}
```
- **ASSERT [PASS]** part-context PUT returns 200
- **ASSERT [PASS]** declared context carries provenance=user
- **ASSERT [PASS]** declared context round-trips sour_service=true

### GET /api/v1/part-context/{mesh_hash} (confirm persisted)

`GET http://127.0.0.1:8000/api/v1/part-context/97064d08a95658cc160677cd0add4ae22098db38b1a86e890bc03c207c7e4485` -> **200**

```json
{
  "mesh_hash": "97064d08a95658cc160677cd0add4ae22098db38b1a86e890bc03c207c7e4485",
  "program": null,
  "parent_assembly": null,
  "units_per_parent": null,
  "annual_volume": null,
  "provenance": "user",
  "service_environment": {
    "medium": "sour gas (H2S)",
    "standard": "NACE MR0175",
    "corrosive": true,
    "sour_service": true
  }
}
```
- **ASSERT [PASS]** part-context GET returns 200

### POST /api/v1/validate/cost (AFTER sour-service environment declared)

`POST http://127.0.0.1:8000/api/v1/validate/cost` -> **200**

```json
{
  "filename": "test_cube.stl",
  "status": "OK",
  "reason": null,
  "geometry": {
    "volume_cm3": 60.0,
    "surface_area_cm2": 94.0,
    "bbox_mm": [
      50.0,
      40.0,
      30.0
    ],
    "watertight": true,
    "face_count": 12
  },
  "material_class": "steel",
  "quantities": [
    50,
    5000
  ],
  "estimates": [
    {
      "process": "forging",
      "material": "Mild Steel",
      "quantity": 50,
      "unit_cost_usd": 622.57,
      "fixed_cost_usd": 30000.0,
      "variable_cost_usd": 20.89,
      "est_error_band_pct": 55.0,
      "confidence": {
        "low_usd": 280.16,
        "high_usd": 964.99,
        "point_usd": 622.57,
        "level": 0.8,
        "method": "assumption-band",
        "validated": false,
        "n_samples": 0,
        "half_width_pct": 55.0,
        "basis": "\u00b155% stated assumption band (cycle-time / tooling defaults) propagated around the point estimate \u2014 no ground truth yet",
        "label": "assumption-based, not yet validated"
      },
      "dfm_ready": false,
      "dfm_verdict": "fail",
      "dfm_score": 0.0,
      "dfm_blockers": [
        "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging."
      ],
      "dfm_blocker_details": [
        {
          "code": "INSUFFICIENT_DRAFT",
          "severity": "error",
          "message": "8 sidewall faces (100.0% of sidewall area) below 5.0\u00b0 draft for forging.",
          "fix_suggestion": "Add >= 5.0\u00b0 draft to all walls in pull direction. FIA: 5\u00b0 external, 7-10\u00b0 internal.",
          "process": "forging",
          "affected_face_count": 8,
          "affected_faces_sample": [
            0,
            1,
            2,
            5,
            7,
            9,
            10,
            11
          ],
          "required_value": 5.0,
          "citation": {
            "standard": "FIA",
            "text": "5\u00b0 external, 7-10\u00b0 internal."
          },
          "scope": "localized"
        }
      ],
      "line_items": {
        "amortized_fixed": 602.1,
        "material": 0.9273,
        "machine": 12.5438,
        "labor": 7.0
      },
      "drivers": [
        {
          "name": "material_cost",
          "value": 0.9273,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "billet from bar = net 0.4710 kg (CAD volume 60.00 cm\u00b3 \u00d7 Mild Steel density 7.85 g/cm\u00b3) \u00d7 (1+0.25 flash/scale loss) [forge assumption, not shop-validated] = 0.5887 kg \u00d7 $1.5/kg (material-DB unit price (DEFAULT book value)) \u00d7 (1+0.05 scrap) \u00d7 region-material \u00d71",
          "error_band_pct": 5.0
        },
        {
          "name": "machine_cost",
          "value": 12.5438,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "0.1045 hr \u00d7 $120/hr \u00d7 region-labor \u00d71  [heat 0.589kg billet (net 0.471kg \u00d7 1+0.25 flash/scale) \u00d7 2.5min/kg = 1.5min + press 0.05hr + trim 0.03hr = 0.1045 hr  (near-net blank \u2014 finish machining NOT bundled) [forge assumption, not shop-validated]]",
          "error_band_pct": 55.0
        },
        {
          "name": "cycle_time",
          "value": 0.1045,
          "unit": "hr",
          "provenance": "DEFAULT",
          "source": "heat 0.589kg billet (net 0.471kg \u00d7 1+0.25 flash/scale) \u00d7 2.5min/kg = 1.5min + press 0.05hr + trim 0.03hr = 0.1045 hr  (near-net blank \u2014 finish machining NOT bundled) [forge assumption, not shop-validated]",
          "error_band_pct": 55.0
        },
        {
          "name": "labor_cost",
          "value": 7.0,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "post-process 0.2 hr \u00d7 $35/hr \u00d7 region-labor \u00d71",
          "error_band_pct": 20.0
        },
        {
          "name": "setup_cost",
          "value": 2.1,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "setup 3hr \u00d7 $35/hr \u00d7 ceil(50/250) = 1 setups \u00f7 50 \u00d7 region-labor \u00d71",
          "error_band_pct": 20.0
        },
        {
          "name": "tooling_cost",
          "value": 30000.0,
          "unit": "$",
          "provenance": "DEFAULT",
          "source": "hardened closed-die set: size tier M (max bbox 50mm) \u00d7 2 family-mult \u00d7 moderate (=1.00) = $30,000; \u00b155%, OVERRIDABLE [assumption, not shop-validated]",
          "error_band_pct": 55.0
        }
      ],
      "lead_time": {
        "low_days": 44.8,
        "high_days": 83.2,
        "mid_days": 64.0,
        "components": {
          "queue": 12.0,
          "tooling_lead": 45.0,
          "production": 1.0,
          "post_process": 3.0,
          "ship": 3.0
        },
        "capacity": {
          "n_machines": 2,
          "machine_hours_per_day": 16.0,
          "provenance": "DEFAULT",
          "basis": "capacity-bound: 2 machines \u00d7 16 hr/day parallel pool; production = ceil(50\u00b70.104hr \u00f7 (2\u00d716)) = 1 d"
        }
      },
      "environment_excluded": true,
      "environment_exclusion_reason": "Mild Steel excluded: sour service requires NACE MR0175 qualification (material not NACE MR0175 / sour_service)"
    },
    {
      "process": "forging",
      "material": "Mild Steel",
      "quantity": 5000,
      "unit_cost_usd": 26.89,
      "fixed_cost_usd": 30000.0,
      "variable_cost_usd": 20.89,
      "est_error_band_pct": 55.0,
      "confidence": {
        "low_usd": 12.1,
        "high_usd": 41.68,
        "point_usd": 26.89,
        "level": 0.8,
        "method": "assumption-band",
        "validated": false,
        "n_samples": 0,
        "half_width_pct": 55.0,
        "basis": "\u00b155% stated assumption band (cycle-time / tooling defaults) propagated around the point estimate \u2014 no ground truth yet",
        "label": "assumption-based, not yet validated"
      },
      "dfm_ready": false,
      "dfm_verdict": "fail",
      "dfm_score": 0.0,
      "dfm_blockers": [
   
... [truncated for transcript] ...
```
- **ASSERT [PASS]** /validate/cost returns 200
- **ASSERT [PASS]** verification block present
- **ASSERT [PASS]** verification.environment_declared == True
- **ASSERT [PASS]** env_exclusions is non-empty (Mild Steel is not NACE-qualified)
- **ASSERT [PASS]** at least one env_exclusion cites NACE MR0175 by name

verification.verdict (post-environment) = `makeable_outsource_only`
- env_exclusion: gate=`environment` axis=`Ductile Iron` -> Ductile Iron excluded: sour service requires NACE MR0175 qualification (material not NACE MR0175 / sour_service)
- env_exclusion: gate=`environment` axis=`Mild Steel` -> Mild Steel excluded: sour service requires NACE MR0175 qualification (material not NACE MR0175 / sour_service)
- **ASSERT [PASS]** third cost decision persisted too

### GET /api/v1/cost-decisions (confirm all decisions listed)

`GET http://127.0.0.1:8000/api/v1/cost-decisions?limit=20` -> **200**

```json
{
  "cost_decisions": [
    {
      "id": "01KWQTZ7B05X360R0M7PS7HRXG",
      "filename": "test_cube.stl",
      "file_type": "stl",
      "label": null,
      "make_now_process": "cnc_3axis",
      "crossover_qty": null,
      "quantities": [
        50,
        5000
      ],
      "created_at": "2026-07-05T00:31:06.072255+00:00",
      "is_public": false,
      "share_url": null
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```
- **ASSERT [PASS]** cost-decisions list returns 200
- **ASSERT [PASS]** pre-machine decision id 01KWQTZ7B05X360R0M7PS7HRXG appears in GET /cost-decisions
- **ASSERT [PASS]** post-machine decision id 01KWQTZ7B05X360R0M7PS7HRXG appears in GET /cost-decisions
- **ASSERT [PASS]** post-environment decision id 01KWQTZ7B05X360R0M7PS7HRXG appears in GET /cost-decisions

**Note on the identical id above:** all three `/validate/cost` calls in this
run used the SAME file + SAME cost params (`material_class=steel`,
`qty=50,5000`, no overrides/shop/region change) — only the *world* around the
part changed (machine declared, then environment declared). By design
(`cost_decision_service.persist_cost_decision`, dedup key
`(user_id, mesh_hash, params_hash)`), a repeat cost of the same file+params
updates the SAME row rather than spawning duplicates — that is why one ULID
appears three times. This was verified as intentional (not a persistence bug)
by reading the service source before asserting on it. The row's `result_json`
was re-saved on each call, so it reflects the LAST computed state (post
environment-exclusion). A different `qty`/`material_class`/etc. would have
produced a second row, and separately-costed distinct parts (different
mesh_hash) always do.

---
## Result: ALL ASSERTIONS PASSED

The Verify core loop (routing/DFM -> should-cost -> Phase C machine verification -> environment exclusion citing NACE -> persistence/list) is proven live against a fresh backend at current HEAD.
