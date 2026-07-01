"""Error-decomposition driver. Runs current engine on real parts, captures the
full cost breakdown, the independent reference bands (harness R1/R2/R3), and a
rate-sensitivity sweep. Pure local, zero network."""
import os, sys, json, warnings, statistics, math
warnings.simplefilter("ignore")
sys.path.insert(0, "/Users/nazeem/Desktop/developer/cadverify/backend")
os.chdir("/Users/nazeem/Desktop/developer/cadverify/backend")

from src.costing.cli import _run_engine
from src.costing import estimate_decision, EstimateOptions
from src.costing.drivers import extract_drivers
from src.costing.routing import material_family, is_rotational
from src.costing import harness as H

PARTS = "/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts"
CORPUS = "/Users/nazeem/Desktop/developer/cadverify/data/corpus"

# (label, abspath, shape-note, default material_class to try, "real" material_class)
PART_SET = [
    ("ThinPanel_Art2SideCover", f"{CORPUS}/meshes/14f30626bcb47fc481a13644e7a92d6b172e2031b0a62dffb2c686bae07bfcf9.stl",
     "thin flat panel 2mm wall", "polymer"),
    ("FlatBracket_FirewallMount", f"{PARTS}/1090523_b8dd5bfe-0a71-405c-906b-aa8dc51a6c30_EK_0BD1_ECU_Firewall_mount.stl",
     "flat ECU firewall mount/bracket", "polymer"),
    ("Rot_FD3S_ThrottleBody", f"{PARTS}/printables_707203_FD3S_to_GM_throttle_body.STL",
     "large rotational throttle-body adapter", "polymer"),
    ("Rot_Ford_Parktronik", f"{PARTS}/thangs_45359_7169bde8_Ford_Parktronik.STL",
     "small rotational parking-sensor housing", "polymer"),
]

QTYS = [1, 100, 1000, 5000]

def line(s=""): print(s)

def run_part(label, path, note, mclass):
    line("="*100)
    line(f"PART: {label}   [{note}]")
    line(f"file: {os.path.basename(path)}")
    result, mesh, feats = _run_engine(path)
    d = extract_drivers(result.geometry, mesh, feats)
    g = result.geometry
    line(f"GEO: V={d.volume_cm3:.2f} cm3 | area={d.surface_area_cm2:.1f} cm2 | "
         f"bbox(sorted)={tuple(round(x,1) for x in d.bbox_mm)} mm | wall(2V/A)={d.nominal_wall_mm:.2f} mm | "
         f"hull={d.hull_volume_cm3:.1f} cm3 | watertight={g.is_watertight}")
    line(f"     rotational={d.rotational} (axis_len={d.rot_axis_len_mm:.1f} cross_dia={d.rot_cross_dia_mm:.1f})  "
         f"max_bbox={d.max_bbox_mm:.1f}  faces={d.face_count}")
    # default-class run across qtys
    rep = estimate_decision(result, mesh, feats, EstimateOptions(quantities=QTYS, material_class=mclass))
    if rep.status != "OK":
        line(f"STATUS: {rep.status} :: {rep.reason}")
        return
    dec = rep.decision
    line(f"DECISION make_now={dec.make_now_process} ({dec.make_now_material}) | "
         f"tooling={dec.tooling_process} dfm_ready={dec.tooling_dfm_ready} | crossover_qty={dec.crossover_qty}")
    line(f"NOTE: {dec.note}")
    # per-process estimates table at each qty
    for q in QTYS:
        ests = [e for e in rep.estimates if e["quantity"] == q]
        ests.sort(key=lambda e: e["unit_cost_usd"])
        line(f"--- qty {q} (sorted by unit cost) ---")
        for e in ests:
            li = e["line_items"]
            mc = material_family(e["material"]) or mclass
            band = H.ref_band(e["process"], d, mc, q)
            bstr = f"ref[{band[0]:.2f},{band[1]:.2f}]" if band else "ref:none"
            sgn = ""
            if band:
                mid = 0.5*(band[0]+band[1])
                sgn = f" err={(e['unit_cost_usd']/mid-1)*100:+.0f}% in={'Y' if band[0]<=e['unit_cost_usd']<=band[1] else 'N'}"
            line(f"  {e['process']:16s} {e['material']:22s} ${e['unit_cost_usd']:9.2f}/u "
                 f"[mat {li.get('material',0):.2f} mach {li.get('machine',0):.2f} lab {li.get('labor',0):.2f} "
                 f"fix {li.get('amortized_fixed',0):.2f}{' floor %.2f'%li['min_charge_floor'] if 'min_charge_floor' in li else ''}] "
                 f"dfm={'ok' if e['dfm_ready'] else 'FAIL'} {bstr}{sgn}")
    return result, mesh, feats, d, rep

def sensitivity(label, path, mclass, proc_value, qty):
    """Bucket-1 probe: swing in unit cost of `proc_value` at `qty` when rates move
    from generic defaults to plausible shop-specific values. Returns dict."""
    result, mesh, feats = _run_engine(path)
    def unit(overrides, region="US"):
        rep = estimate_decision(result, mesh, feats,
              EstimateOptions(quantities=[qty], material_class=mclass,
                              region=region, rate_overrides=overrides))
        for e in rep.estimates:
            if e["process"] == proc_value:
                return e["unit_cost_usd"]
        return None
    base = unit({})
    # map process_value -> ProcessType name for dotted overrides
    from src.analysis.models import ProcessType
    pname = {p.value: p.name for p in ProcessType}[proc_value]
    out = {"base_US_margin0": base}
    out["labor_25"] = unit({"labor_rate": 25.0})
    out["labor_60"] = unit({"labor_rate": 60.0})
    out["margin_25pct"] = unit({"margin": 0.25})
    out["margin_50pct"] = unit({"margin": 0.50})
    # machine rate +-40%
    from src.costing.rates import RATE_CARD_V0
    mr = RATE_CARD_V0["process"][{p.value:p for p in ProcessType}[proc_value]]["machine_rate"]
    out["machine_-40"] = unit({f"machine_rate.{pname}": mr*0.6})
    out["machine_+40"] = unit({f"machine_rate.{pname}": mr*1.4})
    out["region_CN"] = unit({}, region="CN")
    out["region_EU"] = unit({}, region="EU")
    # combined realistic shop price: margin 0.35 + labor 45 + region US
    out["realistic_price_m35_l45"] = unit({"margin": 0.35, "labor_rate": 45.0})
    return out

def main():
    runs = {}
    for label, path, note, mclass in PART_SET:
        runs[label] = run_part(label, path, note, mclass)
        line("")
    # Sensitivity sweeps on the recommended make-now process at qty 100 + 1000
    line("#"*100)
    line("BUCKET-1 RATE SENSITIVITY (recommended make-now process)")
    for label, path, note, mclass in PART_SET:
        r = runs.get(label)
        if not r: continue
        rep = r[4]
        dec = rep.decision
        proc = dec.recommendation[100]["process"]
        for q in (100, 1000):
            s = sensitivity(label, path, mclass, proc, q)
            base = s["base_US_margin0"]
            vals = [v for k,v in s.items() if v is not None]
            line(f"{label} [{proc} q{q}] base=${base:.2f}")
            for k,v in s.items():
                if v is None: continue
                line(f"    {k:24s} ${v:8.2f}  ({(v/base-1)*100:+.0f}% vs base)")
            line(f"    --> full-sweep spread: ${min(vals):.2f} .. ${max(vals):.2f}  "
                 f"(x{max(vals)/min(vals):.2f}, half-width +-{(max(vals)-min(vals))/(max(vals)+min(vals))*100:.0f}%)")
    # Throttle body + parktronik: also run as ALUMINUM (the real material) to expose routing/class miss
    line("#"*100)
    line("ROUTING PROBE: rotational parts re-run as ALUMINUM (the real material class)")
    for label, path, note, mclass in PART_SET:
        if "Rot_" not in label: continue
        result, mesh, feats = _run_engine(path)
        d = extract_drivers(result.geometry, mesh, feats)
        for mc in ("polymer", "aluminum"):
            rep = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100,1000], material_class=mc))
            if rep.status!="OK":
                line(f"{label} class={mc}: {rep.status}"); continue
            dec=rep.decision
            r100=dec.recommendation[100]; r1000=dec.recommendation[1000]
            # cnc_turning estimate if present
            tcost={}
            for e in rep.estimates:
                if e["process"]=="cnc_turning":
                    tcost[e["quantity"]]=e["unit_cost_usd"]
            line(f"{label} class={mc}: make_now={dec.make_now_process} "
                 f"q100 {r100['process']} ${r100['unit_cost_usd']:.2f} | q1000 {r1000['process']} ${r1000['unit_cost_usd']:.2f}"
                 f"  cnc_turning={ {k:round(v,2) for k,v in tcost.items()} }")

if __name__=="__main__":
    main()
