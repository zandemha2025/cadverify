import { apiClient, type RepairResult, type ValidationResult } from "./api";
import { API_BASE } from "./api-base";
import { partCheckHeaders } from "./verify/check-id";

export async function repairAnalysis(file: File, original: ValidationResult | null = null,
  options: {signal?: AbortSignal; onProgress?: (message: string) => void} = {}): Promise<RepairResult> {
  const {signal,onProgress}=options;
  const start=performance.now();
  let bytes=await file.arrayBuffer();
  const originalHash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),n=>n.toString(16).padStart(2,"0")).join("");
  if (!file.name.toLowerCase().endsWith(".stl")) {
    onProgress?.("Converting source CAD to a full mesh before local repair…");
    const form=new FormData();form.append("file",file);
    const response=await apiClient.fetch(`${API_BASE}/validate/preview-mesh?purpose=repair`,{
      method:"POST",body:form,headers:partCheckHeaders(file),signal,
    });
    bytes=await response.arrayBuffer();
  }
  const local=await new Promise<{bytes?:ArrayBuffer;actions?:string[];reason?:string}>((resolve,reject)=>{
    if (signal?.aborted) { reject(new DOMException("Repair cancelled. No check charged.","AbortError")); return; }
    const worker=new Worker(new URL("./mesh-repair.worker.ts",import.meta.url),{type:"module"});
    const stop=()=>{worker.terminate();signal?.removeEventListener("abort",abort);};
    const abort=()=>{stop();reject(new DOMException("Repair cancelled. No check charged.","AbortError"));};
    signal?.addEventListener("abort",abort,{once:true});
    worker.onerror=(event)=>{event.preventDefault();stop();reject(new Error("Your device could not finish this repair. No verification check was charged. The original file is unchanged."));};
    worker.onmessage=(event)=>{
      if (event.data.progress) {onProgress?.(event.data.progress);return;}
      stop();resolve(event.data);
    };
    worker.postMessage({bytes,scale:file.name.toLowerCase().endsWith(".stl") ? original?.source_units?.scale_to_mm ?? 1 : 1},[bytes]);
  });
  const base:RepairResult={original_analysis:original,original_filename:file.name,repair_applied:false,
    repaired_analysis:null,repaired_file_b64:null,repair_verification:null,
    repair_details:{tier:"browser",actions:local.actions,duration_ms:performance.now()-start}};
  if (!local.bytes || local.reason) return {...base,repair_details:{...base.repair_details,reason:local.reason??"No repaired file was produced. No check was charged."}};
  if (signal?.aborted) throw new DOMException("Repair cancelled. No check charged.","AbortError");
  const filename=`${file.name.replace(/\.[^.]+$/,"")}-repaired.stl`;
  const candidate=new File([local.bytes],filename,{type:"model/stl"});
  onProgress?.("Verifying the repaired file with CadVerify…");
  const form=new FormData();form.append("file",candidate);
  const verified=await apiClient.fetchJson<{verified:boolean;analysis:ValidationResult;sha256:string}>(`${API_BASE}/validate/repair/verify`,{
    method:"POST",body:form,headers:{"x-part-check-id":crypto.randomUUID()},signal,
  });
  if (!verified.verified) return {...base,repair_details:{...base.repair_details,reason:
    `The repaired file did not pass independent geometry verification. No check was charged. ${verified.analysis.universal_issues.filter(i=>i.severity==="error").map(i=>i.message).join(" ")}`}};
  return {...base,repair_applied:true,local_file:candidate,repaired_analysis:verified.analysis,
    repair_details:{...base.repair_details,original_faces:original?.geometry.faces,repaired_faces:verified.analysis.geometry.faces},
    repair_verification:{validation_path:"/api/v1/validate",reverified:true,original_verdict:original?.overall_verdict??"unknown",
      repaired_verdict:verified.analysis.overall_verdict,original_sha256:originalHash,repaired_sha256:verified.sha256,
      download_media_type:"model/stl",download_filename:filename}};
}
