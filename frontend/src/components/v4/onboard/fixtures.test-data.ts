/**
 * Real engine output for the first-run tests, trimmed to the processes and
 * quantities the tests read (scratchpad onbui/make-fixtures.py writes it).
 *
 * BEFORE / NOW_BLANK / NOW_RATED: bored-block-mm.iges in aluminum, the same file
 * and engine three times (in-process replay of POST /validate/cost, onb/al-*.json):
 * no machines; a Haas VF-2 and Haas ST-20 declared without owned processes and
 * rates blank (the machine line unchanged); and the two at $85/h and $80/h.
 */
import type { CostReport } from "@/lib/api";
import type { OwnedMachine } from "@/lib/verify/machine-api";
import type { MachineCatalogTemplate } from "@/lib/verify/machine-catalog-api";

export const BEFORE = {
 "filename": "bored-block-mm.iges",
 "status": "OK",
 "reason": null,
 "geometry": {
  "volume_cm3": 2.72,
  "bbox_mm": [
   20.0,
   15.0,
   10.0
  ],
  "face_count": 185386,
  "watertight": true
 },
 "material_class": "aluminum",
 "quantities": [
  10,
  100
 ],
 "estimates": [
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 10,
   "unit_cost_usd": 31.88,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 15.94,
    "high_usd": 47.82,
    "point_usd": 31.88
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.8142,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 2.625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 21.64,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 10.82,
    "high_usd": 32.46,
    "point_usd": 21.64
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.8142,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.2625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 87.25,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 43.62,
    "high_usd": 130.87,
    "point_usd": 87.25
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 1.75,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 85.67,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 42.84,
    "high_usd": 128.51,
    "point_usd": 85.67
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.175,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 10,
   "unit_cost_usd": 564.16,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 253.87,
    "high_usd": 874.44,
    "point_usd": 564.16
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 5.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 73.43,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 33.04,
    "high_usd": 113.82,
    "point_usd": 73.43
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.525,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  }
 ],
 "engine_feasibility": [
  {
   "process": "dmls",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "ded",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "waam",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "cnc_3axis",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "cnc_turning",
   "verdict": "fail",
   "score": 0.0,
   "blockers": [
    "Part lacks positive rotational geometry (eigenvalue ratios: 0.64, 0.79; insufficient outer rotational surface evidence). Required for cnc_turning."
   ]
  },
  {
   "process": "investment_casting",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  }
 ],
 "notes": [],
 "assumptions": [
  {
   "name": "labor_rate",
   "value": 35.0,
   "unit": "$/hr",
   "provenance": "DEFAULT",
   "source": "loaded shop-floor labor"
  }
 ],
 "decision": null
} as unknown as CostReport;

export const NOW_BLANK = {
 "filename": "bored-block-mm.iges",
 "status": "OK",
 "reason": null,
 "geometry": {
  "volume_cm3": 2.72,
  "bbox_mm": [
   20.0,
   15.0,
   10.0
  ],
  "face_count": 185386,
  "watertight": true
 },
 "material_class": "aluminum",
 "quantities": [
  10,
  100
 ],
 "estimates": [
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 10,
   "unit_cost_usd": 31.88,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 15.94,
    "high_usd": 47.82,
    "point_usd": 31.88
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.8142,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 2.625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 21.64,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 10.82,
    "high_usd": 32.46,
    "point_usd": 21.64
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.8142,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.2625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 87.25,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 43.62,
    "high_usd": 130.87,
    "point_usd": 87.25
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 1.75,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 85.67,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 42.84,
    "high_usd": 128.51,
    "point_usd": 85.67
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.175,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 10,
   "unit_cost_usd": 564.16,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 253.87,
    "high_usd": 874.44,
    "point_usd": 564.16
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 5.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 73.43,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 33.04,
    "high_usd": 113.82,
    "point_usd": 73.43
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.525,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  }
 ],
 "engine_feasibility": [
  {
   "process": "dmls",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "ded",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "waam",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "cnc_3axis",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "cnc_turning",
   "verdict": "fail",
   "score": 0.0,
   "blockers": [
    "Part lacks positive rotational geometry (eigenvalue ratios: 0.64, 0.79; insufficient outer rotational surface evidence). Required for cnc_turning."
   ]
  },
  {
   "process": "investment_casting",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  }
 ],
 "notes": [],
 "assumptions": [
  {
   "name": "labor_rate",
   "value": 35.0,
   "unit": "$/hr",
   "provenance": "DEFAULT",
   "source": "loaded shop-floor labor"
  }
 ],
 "decision": null,
 "verification": {
  "verdict": "makeable_in_house",
  "best_machine": "Haas VF-2",
  "inventory_declared": true,
  "per_route": {
   "cnc_3axis": {
    "verdict": "makeable_in_house",
    "machines_evaluated": 1,
    "best_machine": "Haas VF-2",
    "failures": [],
    "machine_rate_usd": null,
    "capital_frac": null
   },
   "ded": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   },
   "dmls": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   },
   "investment_casting": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   },
   "waam": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   }
  }
 }
} as unknown as CostReport;

export const NOW_RATED = {
 "filename": "bored-block-mm.iges",
 "status": "OK",
 "reason": null,
 "geometry": {
  "volume_cm3": 2.72,
  "bbox_mm": [
   20.0,
   15.0,
   10.0
  ],
  "face_count": 185386,
  "watertight": true
 },
 "material_class": "aluminum",
 "quantities": [
  10,
  100
 ],
 "estimates": [
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 10,
   "unit_cost_usd": 31.38,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 15.69,
    "high_usd": 47.06,
    "point_usd": 31.38
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.3365,
     "unit": "$",
     "provenance": "USER",
     "source": "0.0242 hr × $85/hr (fitted machine 'Haas VF-2', its OWN declared rate) × (1-0.35 capital sunk) OWNED-IN-HOUSE marginal [assumption, not shop-validated] × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 2.625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 21.14,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 10.57,
    "high_usd": 31.71,
    "point_usd": 21.14
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.3365,
     "unit": "$",
     "provenance": "USER",
     "source": "0.0242 hr × $85/hr (fitted machine 'Haas VF-2', its OWN declared rate) × (1-0.35 capital sunk) OWNED-IN-HOUSE marginal [assumption, not shop-validated] × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.2625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 87.25,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 43.62,
    "high_usd": 130.87,
    "point_usd": 87.25
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 1.75,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 85.67,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 42.84,
    "high_usd": 128.51,
    "point_usd": 85.67
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.175,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 10,
   "unit_cost_usd": 564.16,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 253.87,
    "high_usd": 874.44,
    "point_usd": 564.16
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 5.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 73.43,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 33.04,
    "high_usd": 113.82,
    "point_usd": 73.43
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.525,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 10,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  }
 ],
 "engine_feasibility": [
  {
   "process": "dmls",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "ded",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "waam",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "cnc_3axis",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "cnc_turning",
   "verdict": "fail",
   "score": 0.0,
   "blockers": [
    "Part lacks positive rotational geometry (eigenvalue ratios: 0.64, 0.79; insufficient outer rotational surface evidence). Required for cnc_turning."
   ]
  },
  {
   "process": "investment_casting",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  }
 ],
 "notes": [],
 "assumptions": [
  {
   "name": "labor_rate",
   "value": 35.0,
   "unit": "$/hr",
   "provenance": "DEFAULT",
   "source": "loaded shop-floor labor"
  }
 ],
 "decision": null,
 "verification": {
  "verdict": "makeable_in_house",
  "best_machine": "Haas VF-2",
  "inventory_declared": true,
  "per_route": {
   "cnc_3axis": {
    "verdict": "makeable_in_house",
    "machines_evaluated": 1,
    "best_machine": "Haas VF-2",
    "failures": [],
    "machine_rate_usd": 85.0,
    "capital_frac": null
   },
   "ded": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   },
   "dmls": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   },
   "investment_casting": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   },
   "waam": {
    "verdict": "makeable_outsource_only",
    "machines_evaluated": 0,
    "best_machine": null,
    "failures": []
   }
  }
 }
} as unknown as CostReport;

export const MACHINES_BLANK = [
 {
  "name": "Haas VF-2",
  "process": "cnc_3axis",
  "count": 1,
  "max_workpiece_kg": 200.0,
  "hourly_rate_usd": null,
  "capital_frac": null,
  "capabilities": {
   "x": 762.0,
   "y": 406.0,
   "z": 508.0,
   "axes": 3
  },
  "materials": [
   "stainless",
   "aluminum",
   "steel"
  ],
  "material_thickness_map": null,
  "id": "m1",
  "provenance": "user",
  "notes": null,
  "created_at": null,
  "updated_at": null
 },
 {
  "name": "Haas ST-20",
  "process": "cnc_turning",
  "count": 1,
  "max_workpiece_kg": 200.0,
  "hourly_rate_usd": null,
  "capital_frac": null,
  "capabilities": {
   "swing_dia": 254.0,
   "between_centers": 533.0
  },
  "materials": [
   "stainless",
   "aluminum"
  ],
  "material_thickness_map": null,
  "id": "m2",
  "provenance": "user",
  "notes": null,
  "created_at": null,
  "updated_at": null
 }
] as unknown as OwnedMachine[];

export const MACHINES_RATED = [
 {
  "name": "Haas VF-2",
  "process": "cnc_3axis",
  "count": 1,
  "max_workpiece_kg": 200.0,
  "hourly_rate_usd": 85.0,
  "capital_frac": null,
  "capabilities": {
   "x": 762.0,
   "y": 406.0,
   "z": 508.0,
   "axes": 3
  },
  "materials": [
   "stainless",
   "aluminum",
   "steel"
  ],
  "material_thickness_map": null,
  "id": "m1",
  "provenance": "user",
  "notes": null,
  "created_at": null,
  "updated_at": null
 },
 {
  "name": "Haas ST-20",
  "process": "cnc_turning",
  "count": 1,
  "max_workpiece_kg": 200.0,
  "hourly_rate_usd": 80.0,
  "capital_frac": null,
  "capabilities": {
   "swing_dia": 254.0,
   "between_centers": 533.0
  },
  "materials": [
   "stainless",
   "aluminum"
  ],
  "material_thickness_map": null,
  "id": "m2",
  "provenance": "user",
  "notes": null,
  "created_at": null,
  "updated_at": null
 }
] as unknown as OwnedMachine[];

/** Three templates as GET /machine-inventory/catalog serves them on staging (b25cce4). */
export const CATALOG = [
 {
  "name": "Prusa MK4S",
  "process": "fdm",
  "count": 1,
  "max_workpiece_kg": null,
  "hourly_rate_usd": null,
  "capital_frac": null,
  "capabilities": {
   "x": 250.0,
   "y": 210.0,
   "z": 220.0,
   "min_layer_um": 50.0,
   "max_layer_um": 350.0,
   "min_feature_mm": 0.4,
   "maker_spec": {
    "catalog": "Prusa MK4S",
    "fields": [
     "materials"
    ]
   }
  },
  "materials": [
   "PLA",
   "PETG"
  ],
  "material_thickness_map": null,
  "notes": "Prefilled from catalog 'Prusa MK4S' (Prusa Research). Materials from the maker's spec; edit anything your machine differs on. The maker publishes no build-plate load.",
  "provenance": "catalog_template",
  "field_provenance": {
   "materials": {
    "source": "maker_spec",
    "catalog": "Prusa MK4S",
    "maker": "Prusa Research",
    "url": "https://www.prusa3d.com/product/original-prusa-mk4s-3d-printer-5/",
    "note": "Prusa lists PLA, PETG, Flex, PVA, PC, PP, CPE and PVB. ABS, ASA, HIPS and PA need the Original Prusa Enclosure with filtration, so they aren't prefilled.",
    "checked": "2026-10-19"
   }
  },
  "spec": {
   "source_url": "https://www.prusa3d.com/product/original-prusa-mk4s-3d-printer-5/",
   "max_workpiece_kg": null,
   "max_workpiece_kg_note": "The maker publishes no build-plate load.",
   "materials_basis": "maker_spec",
   "materials_url": "https://www.prusa3d.com/product/original-prusa-mk4s-3d-printer-5/",
   "materials_note": "Prusa lists PLA, PETG, Flex, PVA, PC, PP, CPE and PVB. ABS, ASA, HIPS and PA need the Original Prusa Enclosure with filtration, so they aren't prefilled.",
   "checked": "2026-10-19"
  }
 },
 {
  "name": "Carbon M2",
  "process": "dlp",
  "count": 1,
  "max_workpiece_kg": null,
  "hourly_rate_usd": null,
  "capital_frac": null,
  "capabilities": {
   "x": 189.0,
   "y": 118.0,
   "z": 326.0,
   "min_layer_um": 25.0,
   "max_layer_um": 100.0,
   "min_feature_mm": 0.075
  },
  "materials": null,
  "material_thickness_map": null,
  "notes": "Prefilled from catalog 'Carbon M2' (Carbon). The maker publishes no build-plate load. Not prefilled (no registry material): RPU 70, EPU 41, CE 221.",
  "provenance": "catalog_template",
  "field_provenance": {},
  "spec": {
   "source_url": "https://learn.carbon3d.com/hardware/m1-m2-features",
   "max_workpiece_kg": null,
   "max_workpiece_kg_note": "The maker publishes no build-plate load.",
   "materials_basis": "maker_spec",
   "materials_url": "https://docs.carbon3d.com/files/design-guides/dg_dls-design-quick-guide.pdf",
   "materials_note": "Carbon lists RPU 70, EPU 41 and CE 221.",
   "checked": "2026-10-19"
  }
 },
 {
  "name": "Haas VF-2",
  "process": "cnc_3axis",
  "count": 1,
  "max_workpiece_kg": 1361.0,
  "hourly_rate_usd": null,
  "capital_frac": null,
  "capabilities": {
   "x": 762.0,
   "y": 406.0,
   "z": 508.0,
   "axes": 3,
   "maker_spec": {
    "catalog": "Haas VF-2",
    "fields": [
     "max_workpiece_kg",
     "materials"
    ]
   }
  },
  "materials": [
   "aluminum",
   "steel"
  ],
  "material_thickness_map": null,
  "notes": "Prefilled from catalog 'Haas VF-2' (Haas). Workpiece weight and materials from the maker's spec; edit anything your machine differs on.",
  "provenance": "catalog_template",
  "field_provenance": {
   "max_workpiece_kg": {
    "source": "maker_spec",
    "catalog": "Haas VF-2",
    "maker": "Haas",
    "url": "https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html",
    "note": "Max weight on table, evenly distributed: 3000 lb (1361 kg).",
    "checked": "2026-10-19"
   },
   "materials": {
    "source": "maker_described",
    "catalog": "Haas VF-2",
    "maker": "Haas",
    "url": "https://www.haascnc.com/productivity/spindles/8-1k-40t-in.html",
    "note": "Haas lists no materials; it calls the standard 8100-rpm 40-taper spindle all-purpose. Aluminum and steel only: add stainless or titanium if you cut them.",
    "checked": "2026-10-19"
   }
  },
  "spec": {
   "source_url": "https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html",
   "max_workpiece_kg": 1361.0,
   "max_workpiece_kg_note": "Max weight on table, evenly distributed: 3000 lb (1361 kg).",
   "materials_basis": "maker_described",
   "materials_url": "https://www.haascnc.com/productivity/spindles/8-1k-40t-in.html",
   "materials_note": "Haas lists no materials; it calls the standard 8100-rpm 40-taper spindle all-purpose. Aluminum and steel only: add stainless or titanium if you cut them.",
   "checked": "2026-10-19"
  }
 }
] as unknown as MachineCatalogTemplate[];

/**
 * Staging (b25cce4), a new work-email trial account: bored-block-mm.iges in
 * aluminum, first checked with no machines, then re-checked after adding a Haas
 * VF-2 from the catalog unedited (maker's 1361 kg, aluminum and steel, rate
 * blank). Records 01M59BFYANN69P4M7Z5G9ECPET and 01M59BGPPZ4CG8BM5YM2PHBNMA.
 */
export const STAGING_BEFORE = {
 "filename": "bored-block-mm.iges",
 "status": "OK",
 "reason": null,
 "geometry": {
  "volume_cm3": 2.72,
  "bbox_mm": [
   20.0,
   15.0,
   10.0
  ],
  "face_count": 185386,
  "watertight": true
 },
 "material_class": "aluminum",
 "quantities": [
  1,
  100
 ],
 "estimates": [
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 1,
   "unit_cost_usd": 134.25,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 67.13,
    "high_usd": 201.38,
    "point_usd": 134.25
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.8142,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 26.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 21.64,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 10.82,
    "high_usd": 32.46,
    "point_usd": 21.64
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.8142,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.2625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 1,
   "unit_cost_usd": 300.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 120.0,
    "high_usd": 480.0,
    "point_usd": 300.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 35.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 1,
   "unit_cost_usd": 250.0,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 125.0,
    "high_usd": 375.0,
    "point_usd": 250.0
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 85.67,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 42.84,
    "high_usd": 128.51,
    "point_usd": 85.67
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.175,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 1,
   "unit_cost_usd": 5471.41,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 2462.13,
    "high_usd": 8480.68,
    "point_usd": 5471.41
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 52.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 73.43,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 33.04,
    "high_usd": 113.82,
    "point_usd": 73.43
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.525,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 1,
   "unit_cost_usd": 300.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 120.0,
    "high_usd": 480.0,
    "point_usd": 300.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 35.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  }
 ],
 "engine_feasibility": [
  {
   "process": "dmls",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "ded",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "waam",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "cnc_3axis",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "cnc_turning",
   "verdict": "fail",
   "score": 0.0,
   "blockers": [
    "Part lacks positive rotational geometry (eigenvalue ratios: 0.64, 0.79; insufficient outer rotational surface evidence). Required for cnc_turning."
   ]
  },
  {
   "process": "investment_casting",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  }
 ],
 "notes": [],
 "assumptions": [
  {
   "name": "labor_rate",
   "unit": "$/hr",
   "value": 35.0,
   "source": "loaded shop-floor labor",
   "provenance": "DEFAULT"
  }
 ],
 "decision": null
} as unknown as CostReport;

export const STAGING_NOW = {
 "filename": "bored-block-mm.iges",
 "status": "OK",
 "reason": null,
 "geometry": {
  "volume_cm3": 2.72,
  "bbox_mm": [
   20.0,
   15.0,
   10.0
  ],
  "face_count": 185386,
  "watertight": true
 },
 "material_class": "aluminum",
 "quantities": [
  1,
  100
 ],
 "estimates": [
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 1,
   "unit_cost_usd": 133.59,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 66.79,
    "high_usd": 200.38,
    "point_usd": 133.59
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.1792,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × (1-0.35 capital sunk) OWNED-IN-HOUSE marginal [assumption, not shop-validated] × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 26.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "cnc_3axis",
   "material": "6061-T6 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 20.97,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 10.49,
    "high_usd": 31.46,
    "point_usd": 20.97
   },
   "lead_time": {
    "low_days": 7.0,
    "high_days": 13.0
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.1792,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0242 hr × $75/hr × (1-0.35 capital sunk) OWNED-IN-HOUSE marginal [assumption, not shop-validated] × region-labor ×1  [rough 0.6 cm³ ÷ (30 cm³/min·60) = 0.000 hr + finish 14.3 cm² ÷ 600 cm²/hr = 0.024 hr  [stock oriented candidate bbox billet 3.0 cm³ × 1.10 = 3.3 cm³ [assumption, not shop-validated]; MRR aluminum]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0242,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.2625,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 1,
   "unit_cost_usd": 300.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 120.0,
    "high_usd": 480.0,
    "point_usd": 300.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 35.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "ded",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 1.0012,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0083 hr × $120/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 1kg/hr deposition = 0.0083hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0083,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 1,
   "unit_cost_usd": 250.0,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 125.0,
    "high_usd": 375.0,
    "point_usd": 250.0
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 17.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "dmls",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 85.67,
   "est_error_band_pct": 50.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 42.84,
    "high_usd": 128.51,
    "point_usd": 85.67
   },
   "lead_time": {
    "low_days": 9.8,
    "high_days": 18.2
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 52.4194,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.2912 hr × $180/hr × region-labor ×1  [build-job 325mm ÷ 6mm/hr = 54.2hr full build ÷ 186 parts/build (packing 0.08, env (250, 250, 325)) = 0.291hr/part; oriented candidate oriented XYZ (15.0, 20.0, 10.0)mm; spaced-grid capacity limit (packing/setup assumption, not a verified nesting plan)]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.2912,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.175,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 1,
   "unit_cost_usd": 5471.41,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 2462.13,
    "high_usd": 8480.68,
    "point_usd": 5471.41
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 52.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "investment_casting",
   "material": "A356 Aluminum",
   "quantity": 100,
   "unit_cost_usd": 73.43,
   "est_error_band_pct": 55.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.8,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 33.04,
    "high_usd": 113.82,
    "point_usd": 73.43
   },
   "lead_time": {
    "low_days": 33.6,
    "high_days": 62.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 6.614,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.1203 hr × $55/hr × region-labor ×1  [pour 0.12hr + solidify/cool 0.010kg poured (net 0.007kg × 1+0.4 yield) × 1.5min/kg = 0.0min = 0.1203 hr  [foundry assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.1203,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 12.25,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 0.525,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 1,
   "unit_cost_usd": 300.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 120.0,
    "high_usd": 480.0,
    "point_usd": 300.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 35.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  },
  {
   "process": "waam",
   "material": "AlSi10Mg",
   "quantity": 100,
   "unit_cost_usd": 30.0,
   "est_error_band_pct": 60.0,
   "dfm_ready": true,
   "dfm_verdict": "issues",
   "fixed_cost_usd": 0,
   "variable_cost_usd": 0,
   "dfm_score": 0.9,
   "dfm_blockers": [],
   "line_items": {},
   "confidence": {
    "low_usd": 12.0,
    "high_usd": 48.0,
    "point_usd": 30.0
   },
   "lead_time": {
    "low_days": 12.6,
    "high_days": 23.4
   },
   "drivers": [
    {
     "name": "machine_cost",
     "value": 0.2503,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "0.0028 hr × $90/hr × region-labor ×1  [deposit 0.0083kg (net 0.0073kg × 1.15 near-net overbuild) ÷ 3kg/hr deposition = 0.0028hr  [COARSE deposition-rate model — DED/WAAM cost is highly geometry/path/shop-specific; assumption, not shop-validated]]",
     "error_band_pct": null
    },
    {
     "name": "cycle_time",
     "value": 0.0028,
     "unit": "hr",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "labor_cost",
     "value": 0.0,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    },
    {
     "name": "setup_cost",
     "value": 3.5,
     "unit": "$",
     "provenance": "DEFAULT",
     "source": "",
     "error_band_pct": null
    }
   ]
  }
 ],
 "engine_feasibility": [
  {
   "process": "dmls",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "ded",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "waam",
   "verdict": "issues",
   "score": 0.9,
   "blockers": []
  },
  {
   "process": "cnc_3axis",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  },
  {
   "process": "cnc_turning",
   "verdict": "fail",
   "score": 0.0,
   "blockers": [
    "Part lacks positive rotational geometry (eigenvalue ratios: 0.64, 0.79; insufficient outer rotational surface evidence). Required for cnc_turning."
   ]
  },
  {
   "process": "investment_casting",
   "verdict": "issues",
   "score": 0.8,
   "blockers": []
  }
 ],
 "notes": [],
 "assumptions": [
  {
   "name": "labor_rate",
   "unit": "$/hr",
   "value": 35.0,
   "source": "loaded shop-floor labor",
   "provenance": "DEFAULT"
  }
 ],
 "decision": null,
 "verification": {
  "verdict": "makeable_in_house",
  "best_machine": "Haas VF-2",
  "inventory_declared": true,
  "per_route": {
   "ded": {
    "verdict": "makeable_outsource_only",
    "failures": [],
    "best_machine": null,
    "machines_evaluated": 0
   },
   "dmls": {
    "verdict": "makeable_outsource_only",
    "failures": [],
    "best_machine": null,
    "machines_evaluated": 0
   },
   "waam": {
    "verdict": "makeable_outsource_only",
    "failures": [],
    "best_machine": null,
    "machines_evaluated": 0
   },
   "cnc_3axis": {
    "verdict": "makeable_in_house",
    "failures": [],
    "maker_spec": {
     "fields": [
      "max_workpiece_kg",
      "materials"
     ],
     "catalog": "Haas VF-2"
    },
    "best_machine": "Haas VF-2",
    "capital_frac": null,
    "machine_rate_usd": null,
    "machines_evaluated": 1
   },
   "investment_casting": {
    "verdict": "makeable_outsource_only",
    "failures": [],
    "best_machine": null,
    "machines_evaluated": 0
   }
  }
 }
} as unknown as CostReport;

export const STAGING_MACHINES = [
 {
  "id": "vf2",
  "name": "Haas VF-2",
  "process": "cnc_3axis",
  "count": 1,
  "max_workpiece_kg": 1361.0,
  "hourly_rate_usd": null,
  "capital_frac": null,
  "capabilities": {
   "x": 762,
   "y": 406,
   "z": 508,
   "axes": 3,
   "maker_spec": {
    "fields": [
     "max_workpiece_kg",
     "materials"
    ],
    "catalog": "Haas VF-2"
   }
  },
  "materials": [
   "aluminum",
   "steel"
  ],
  "material_thickness_map": null,
  "notes": "Prefilled from catalog 'Haas VF-2' (Haas). Workpiece weight and materials from the maker's spec; edit anything your machine differs on.",
  "provenance": "user",
  "field_provenance": {
   "max_workpiece_kg": {
    "source": "maker_spec",
    "catalog": "Haas VF-2",
    "maker": "Haas",
    "url": "https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html",
    "note": "Max weight on table, evenly distributed: 3000 lb (1361 kg).",
    "checked": "2026-10-19"
   },
   "materials": {
    "source": "maker_described",
    "catalog": "Haas VF-2",
    "maker": "Haas",
    "url": "https://www.haascnc.com/productivity/spindles/8-1k-40t-in.html",
    "note": "Haas lists no materials; it calls the standard 8100-rpm 40-taper spindle all-purpose. Aluminum and steel only: add stainless or titanium if you cut them.",
    "checked": "2026-10-19"
   }
  },
  "created_at": null,
  "updated_at": null
 }
] as unknown as OwnedMachine[];
