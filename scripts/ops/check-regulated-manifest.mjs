import { readFile } from "node:fs/promises";

const manifestPath = process.argv[2] || "/tmp/cadverify-regulated-rendered.yaml";
const manifest = await readFile(manifestPath, "utf8");

const checks = [
  ["no Helm-rendered Secret", !/^kind: Secret$/m.test(manifest)],
  ["no local blob PVC", !/^kind: PersistentVolumeClaim$/m.test(manifest)],
  ["deny/allow NetworkPolicies rendered", /^kind: NetworkPolicy$/m.test(manifest)],
  ["PodDisruptionBudgets rendered", /^kind: PodDisruptionBudget$/m.test(manifest)],
  ["HorizontalPodAutoscalers rendered", /^kind: HorizontalPodAutoscaler$/m.test(manifest)],
  ["read-only root filesystem", /readOnlyRootFilesystem: true/.test(manifest)],
  ["privilege escalation disabled", /allowPrivilegeEscalation: false/.test(manifest)],
  ["all Linux capabilities dropped", /capabilities:\s*\n\s*drop:\s*\n\s*- ALL/.test(manifest)],
  ["RuntimeDefault seccomp", /seccompProfile:\s*\n\s*type: RuntimeDefault/.test(manifest)],
  ["service account token disabled", /automountServiceAccountToken: false/.test(manifest)],
  ["external runtime Secret referenced", /secretRef:\s*\n\s*name: "?cadverify-runtime"?/.test(manifest)],
  ["frontend auth-proxy secret referenced", /name: AUTH_PROXY_SECRET\s*\n\s*valueFrom:\s*\n\s*secretKeyRef:[\s\S]{0,160}key: AUTH_PROXY_SECRET/.test(manifest)],
  ["regulated frontend initiates SAML", /name: SSO_LOGIN_PATH\s*\n\s*value: ["']?\/auth\/saml\/login["']?/.test(manifest)],
  ["password login disabled", /name: PASSWORD_LOGIN_ENABLED\s*\n\s*value: ["']?0["']?/.test(manifest)],
  ["magic link disabled", /name: MAGIC_LINK_ENABLED\s*\n\s*value: ["']?0["']?/.test(manifest)],
  ["regulated boundary startup guard enabled", (manifest.match(/name: PRODUCTION_REGULATED_BOUNDARY_REQUIRED\s*\n\s*value: ["']?1["']?/g) || []).length >= 2],
  ["cryptographic secret quality gate enabled", (manifest.match(/name: PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED\s*\n\s*value: ["']?1["']?/g) || []).length >= 2],
  ["remote reconstruction disabled", /name: RECONSTRUCTION_BACKEND\s*\n\s*value: ["']?local["']?/.test(manifest) && /name: RECONSTRUCTION_ALLOW_REMOTE_EGRESS\s*\n\s*value: ["']?0["']?/.test(manifest)],
  ["external Sentry sink overridden empty", (manifest.match(/name: SENTRY_DSN\s*\n\s*value: ["']{2}/g) || []).length >= 2],
  ["S3 object store selected", /name: OBJECT_STORE_BACKEND\s*\n\s*value: ["']?s3["']?/.test(manifest)],
  ["TLS ingress rendered", /^\s*tls:$/m.test(manifest)],
  ["HTTPS redirect enforced", /nginx\.ingress\.kubernetes\.io\/ssl-redirect: ["']?true["']?/.test(manifest)],
  ["backend ingress is limited to /api/v1", /^\s*- path: \/api\/v1$/m.test(manifest) && !/^\s*- path: \/api$/m.test(manifest)],
  ["public share pages remain on Next", !/^\s*- path: \/s$/m.test(manifest)],
  ["SSO and SCIM ingress routes rendered", /^\s*- path: \/auth$/m.test(manifest) && /^\s*- path: \/scim\/v2$/m.test(manifest)],
  ["no mutable latest image", !/^\s*image: .*:latest\s*$/m.test(manifest)],
  ["images pinned by sha256 digest", (manifest.match(/^\s*image: ["']?.+@sha256:[a-f0-9]{64}["']?\s*$/gm) || []).length >= 4],
  ["no broad or instance-metadata egress", !/cidr: ["']?(?:0\.0\.0\.0\/0|::\/0|169\.254\.169\.254\/32)["']?/.test(manifest)],
];

const failed = checks.filter(([, ok]) => !ok).map(([name]) => name);
for (const [name, ok] of checks) {
  console.log(`${ok ? "PASS" : "FAIL"}: ${name}`);
}

if (failed.length) {
  console.error(`Regulated manifest gate failed: ${failed.join(", ")}`);
  process.exitCode = 1;
}
