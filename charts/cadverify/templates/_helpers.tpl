{{/*
Expand the name of the chart.
*/}}
{{- define "cadverify.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "cadverify.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "cadverify.labels" -}}
helm.sh/chart: {{ include "cadverify.chart" . }}
{{ include "cadverify.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "cadverify.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cadverify.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Chart name and version
*/}}
{{- define "cadverify.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Database URL
*/}}
{{- define "cadverify.databaseUrl" -}}
postgresql+asyncpg://{{ .Values.postgresql.username }}:{{ .Values.postgresql.password }}@{{ .Values.postgresql.host }}:{{ .Values.postgresql.port }}/{{ .Values.postgresql.database }}
{{- end }}

{{/*
Redis URL
*/}}
{{- define "cadverify.redisUrl" -}}
redis://{{ .Values.redis.host }}:{{ .Values.redis.port }}/0
{{- end }}

{{/* Service account name */}}
{{- define "cadverify.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "cadverify.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end }}

{{/* Internal API origin used by the server-side Next proxy. */}}
{{- define "cadverify.internalApiBase" -}}
{{- default (printf "http://%s-backend:8000" (include "cadverify.fullname" .)) .Values.frontend.apiBase -}}
{{- end }}

{{/* Immutable image references use a digest when supplied. */}}
{{- define "cadverify.backendImage" -}}
{{- if .Values.image.backend.digest -}}
{{- printf "%s@%s" .Values.image.backend.repository .Values.image.backend.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.backend.repository .Values.image.backend.tag -}}
{{- end -}}
{{- end }}

{{- define "cadverify.frontendImage" -}}
{{- if .Values.image.frontend.digest -}}
{{- printf "%s@%s" .Values.image.frontend.repository .Values.image.frontend.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.frontend.repository .Values.image.frontend.tag -}}
{{- end -}}
{{- end }}

{{/*
Fail closed when a production overlay is incomplete. This does not certify the
environment; it prevents the chart from accepting the most dangerous launch
mistakes (mutable images, Helm-held secrets, local blob storage, no TLS, and
single-replica workloads).
*/}}
{{- define "cadverify.validateProductionValues" -}}
{{- if .Values.production.enabled -}}
  {{- if ne .Values.production.operatorAcknowledgement "CONFIGURED_EXTERNAL_DEPENDENCIES" -}}
    {{- fail "production install requires --set production.operatorAcknowledgement=CONFIGURED_EXTERNAL_DEPENDENCIES" -}}
  {{- end -}}
  {{- if or (eq .Values.release "") (eq .Values.release "dev") (eq .Values.release "latest") -}}
    {{- fail "production.release must be an immutable release identifier" -}}
  {{- end -}}
  {{- if or (eq .Values.deploymentEnvironment "") (eq .Values.deploymentEnvironment "development") -}}
    {{- fail "production requires an explicit deploymentEnvironment" -}}
  {{- end -}}
  {{- if or (eq .Values.image.backend.tag "latest") (eq .Values.image.frontend.tag "latest") -}}
    {{- if or (not .Values.image.backend.digest) (not .Values.image.frontend.digest) -}}
      {{- fail "production images must use immutable tags or digests, never latest" -}}
    {{- end -}}
  {{- end -}}
  {{- range $component, $config := dict "backend" .Values.image.backend "frontend" .Values.image.frontend -}}
    {{- if and $config.digest (not (regexMatch "^sha256:[a-f0-9]{64}$" $config.digest)) -}}
      {{- fail (printf "image.%s.digest must be a sha256 digest" $component) -}}
    {{- end -}}
  {{- end -}}
  {{- if not .Values.runtimeSecret.existingSecret -}}
    {{- fail "production requires runtimeSecret.existingSecret managed outside Helm" -}}
  {{- end -}}
  {{- if .Values.auth.publicPasswordSignup -}}
    {{- fail "production requires verified account creation; auth.publicPasswordSignup must be false" -}}
  {{- end -}}
  {{- if ne .Values.objectStore.backend "s3" -}}
    {{- fail "production requires objectStore.backend=s3" -}}
  {{- end -}}
  {{- if not .Values.objectStore.s3.bucket -}}
    {{- fail "production requires objectStore.s3.bucket" -}}
  {{- end -}}
  {{- if not .Values.objectStore.s3.region -}}
    {{- fail "production requires objectStore.s3.region" -}}
  {{- end -}}
  {{- if and .Values.objectStore.s3.endpoint (not (hasPrefix "https://" .Values.objectStore.s3.endpoint)) -}}
    {{- fail "production objectStore.s3.endpoint must use https" -}}
  {{- end -}}
  {{- if not .Values.ingress.enabled -}}
    {{- fail "production requires ingress.enabled=true" -}}
  {{- end -}}
  {{- if not .Values.ingress.tls -}}
    {{- fail "production requires ingress TLS configuration" -}}
  {{- end -}}
  {{- $ingressTLSHost := dict -}}
  {{- range .Values.ingress.tls -}}
    {{- range .hosts -}}
      {{- if eq . $.Values.ingress.host -}}
        {{- $_ := set $ingressTLSHost "found" true -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
  {{- if not (hasKey $ingressTLSHost "found") -}}
    {{- fail "production ingress TLS hosts must include ingress.host" -}}
  {{- end -}}
  {{- if or (lt (int .Values.replicaCount.backend) 2) (lt (int .Values.replicaCount.worker) 2) (lt (int .Values.replicaCount.frontend) 2) -}}
    {{- fail "production requires at least two backend, worker, and frontend replicas" -}}
  {{- end -}}
  {{- if not .Values.podDisruptionBudget.enabled -}}
    {{- fail "production requires podDisruptionBudget.enabled=true" -}}
  {{- end -}}
  {{- if not .Values.topologySpreadConstraints.enabled -}}
    {{- fail "production requires topologySpreadConstraints.enabled=true" -}}
  {{- end -}}
  {{- if .Values.serviceAccount.automountServiceAccountToken -}}
    {{- fail "production must not automount Kubernetes service account tokens" -}}
  {{- end -}}
  {{- if and (not .Values.serviceAccount.create) (or (not .Values.serviceAccount.name) (eq .Values.serviceAccount.name "default")) -}}
    {{- fail "production requires a dedicated Kubernetes service account" -}}
  {{- end -}}
  {{- if not .Values.containerSecurityContext.readOnlyRootFilesystem -}}
    {{- fail "production requires a read-only container root filesystem" -}}
  {{- end -}}
  {{- if or (eq (int .Values.podSecurityContext.runAsUser) 0) (eq (int .Values.podSecurityContext.runAsGroup) 0) (eq (int .Values.podSecurityContext.fsGroup) 0) -}}
    {{- fail "production requires explicit non-root runAsUser, runAsGroup, and fsGroup" -}}
  {{- end -}}
  {{- if and .Values.autoscaling.backend.enabled (lt (int .Values.autoscaling.backend.minReplicas) 2) -}}
    {{- fail "production backend autoscaling.minReplicas must be at least two" -}}
  {{- end -}}
  {{- if and .Values.autoscaling.frontend.enabled (lt (int .Values.autoscaling.frontend.minReplicas) 2) -}}
    {{- fail "production frontend autoscaling.minReplicas must be at least two" -}}
  {{- end -}}
  {{- if .Values.production.regulated -}}
    {{- if not (hasPrefix "regulated-" .Values.deploymentEnvironment) -}}
      {{- fail "regulated production deploymentEnvironment must start with regulated-" -}}
    {{- end -}}
    {{- if or (not .Values.image.backend.digest) (not .Values.image.frontend.digest) -}}
      {{- fail "regulated production requires backend and frontend image digests" -}}
    {{- end -}}
    {{- if not .Values.objectStore.s3.kmsKeyId -}}
      {{- fail "regulated production requires objectStore.s3.kmsKeyId" -}}
    {{- end -}}
    {{- if not (has .Values.objectStore.s3.region (list "us-gov-west-1" "us-gov-east-1")) -}}
      {{- fail "regulated object storage must use an AWS GovCloud region" -}}
    {{- end -}}
    {{- if not (regexMatch "^arn:aws-us-gov:kms:us-gov-(west|east)-1:[0-9]{12}:key/[A-Za-z0-9-]+$" .Values.objectStore.s3.kmsKeyId) -}}
      {{- fail "regulated objectStore.s3.kmsKeyId must be a GovCloud KMS key ARN" -}}
    {{- end -}}
    {{- if not (contains (printf ":kms:%s:" .Values.objectStore.s3.region) .Values.objectStore.s3.kmsKeyId) -}}
      {{- fail "regulated S3 bucket region and KMS key region must match" -}}
    {{- end -}}
    {{- range $component, $config := dict "backend" .Values.image.backend "frontend" .Values.image.frontend -}}
      {{- if not (regexMatch "^[0-9]{12}\\.dkr\\.ecr\\.us-gov-(west|east)-1\\.amazonaws\\.com/.+$" $config.repository) -}}
        {{- fail (printf "regulated image.%s.repository must be a GovCloud ECR repository" $component) -}}
      {{- end -}}
    {{- end -}}
    {{- if not .Values.networkPolicy.enabled -}}
      {{- fail "regulated production requires networkPolicy.enabled=true" -}}
    {{- end -}}
    {{- if or (not .Values.networkPolicy.ingressControllerNamespaceLabels) (not .Values.networkPolicy.ingressControllerPodLabels) -}}
      {{- fail "regulated production requires exact ingress-controller namespace and pod labels" -}}
    {{- end -}}
    {{- if or (not .Values.networkPolicy.observabilityNamespaceLabels) (not .Values.networkPolicy.observabilityPodLabels) -}}
      {{- fail "regulated production requires exact observability namespace and pod labels" -}}
    {{- end -}}
    {{- $workloadRules := dict
          "backend" .Values.networkPolicy.backendEgressRules
          "worker" .Values.networkPolicy.workerEgressRules
          "migration" .Values.networkPolicy.migrationEgressRules -}}
    {{- range $workload, $rules := $workloadRules -}}
      {{- if not $rules -}}
        {{- fail (printf "regulated production requires explicit networkPolicy.%sEgressRules" $workload) -}}
      {{- end -}}
      {{- $egressPorts := dict -}}
      {{- range $rules -}}
        {{- if has .cidr (list "0.0.0.0/0" "::/0" "169.254.169.254/32") -}}
          {{- fail (printf "regulated networkPolicy.%sEgressRules contains a prohibited broad/metadata CIDR" $workload) -}}
        {{- end -}}
        {{- range .ports -}}
          {{- if eq (upper (default "TCP" .protocol)) "TCP" -}}
            {{- $_ := set $egressPorts (toString .port) true -}}
          {{- end -}}
        {{- end -}}
      {{- end -}}
      {{- range $requiredPort := index $.Values.networkPolicy.requiredPorts $workload -}}
        {{- if not (hasKey $egressPorts (toString $requiredPort)) -}}
          {{- fail (printf "regulated networkPolicy.%sEgressRules must include TCP port %v" $workload $requiredPort) -}}
        {{- end -}}
      {{- end -}}
    {{- end -}}
    {{- if not .Values.audit.enabled -}}
      {{- fail "regulated production requires audit.enabled=true" -}}
    {{- end -}}
    {{- if not .Values.observability.otel.enabled -}}
      {{- fail "regulated production requires in-boundary OpenTelemetry" -}}
    {{- end -}}
    {{- if not (hasPrefix "https://" .Values.observability.otel.endpoint) -}}
      {{- fail "regulated OpenTelemetry requires an https collector endpoint" -}}
    {{- end -}}
    {{- if not .Values.observability.otel.caSecret -}}
      {{- fail "regulated OpenTelemetry requires observability.otel.caSecret" -}}
    {{- end -}}
    {{- if ne .Values.auth.mode "saml" -}}
      {{- fail "the approved regulated delivery baseline requires auth.mode=saml" -}}
    {{- end -}}
    {{- if .Values.frontend.magicLink.enabled -}}
      {{- fail "regulated SAML production must disable frontend.magicLink.enabled" -}}
    {{- end -}}
    {{- if and .Values.frontend.ssoLoginPath (ne .Values.frontend.ssoLoginPath "/auth/saml/login") -}}
      {{- fail "regulated SAML production requires frontend.ssoLoginPath=/auth/saml/login" -}}
    {{- end -}}
    {{- if not (has .Values.reconstruction.backend (list "local" "none")) -}}
      {{- fail "regulated production permits only local or disabled reconstruction" -}}
    {{- end -}}
    {{- if .Values.reconstruction.allowRemoteEgress -}}
      {{- fail "regulated production prohibits remote reconstruction egress" -}}
    {{- end -}}
    {{- if ne .Values.ingress.className "nginx" -}}
      {{- fail "the regulated baseline requires the reviewed nginx ingress class" -}}
    {{- end -}}
    {{- if ne (index .Values.ingress.annotations "nginx.ingress.kubernetes.io/ssl-redirect") "true" -}}
      {{- fail "regulated nginx ingress must force HTTPS redirects" -}}
    {{- end -}}
    {{- if and (has .Values.auth.mode (list "saml" "hybrid")) (not .Values.saml.existingSecret) -}}
      {{- fail "regulated SAML requires saml.existingSecret with settings.json and advanced_settings.json" -}}
    {{- end -}}
    {{- if and (has .Values.auth.mode (list "saml" "hybrid")) (or (not (hasPrefix "https://" .Values.saml.spEntityId)) (not (hasPrefix "https://" .Values.saml.spAcsUrl)) (not (hasPrefix "https://" .Values.saml.spSloUrl))) -}}
      {{- fail "regulated SAML entity, ACS, and SLO URLs must use https" -}}
    {{- end -}}
    {{- if not .Values.production.documentationRenderOnly -}}
      {{- if not .Values.regulatedControls.inClusterEncryption -}}
        {{- fail "regulated production requires evidenced in-cluster encryption" -}}
      {{- end -}}
      {{- if or (contains "111111111111" .Values.image.backend.repository) (contains "111111111111" .Values.image.frontend.repository) -}}
        {{- fail "replace the documentation-only ECR account before deployment" -}}
      {{- end -}}
      {{- if contains "replace-me" .Values.objectStore.s3.kmsKeyId -}}
        {{- fail "replace the documentation-only KMS key before deployment" -}}
      {{- end -}}
      {{- if or (contains "example." .Values.ingress.host) (contains "replace-me" .Values.objectStore.s3.bucket) -}}
        {{- fail "replace documentation-only host and bucket values before deployment" -}}
      {{- end -}}
      {{- if or (contains "0000000000000000" .Values.image.backend.digest) (contains "0000000000000000" .Values.image.frontend.digest) -}}
        {{- fail "replace documentation-only image digests before deployment" -}}
      {{- end -}}
      {{- range $workload, $rules := $workloadRules -}}
        {{- range $rules -}}
          {{- if regexMatch "^(192\\.0\\.2|198\\.51\\.100|203\\.0\\.113)\\." .cidr -}}
            {{- fail (printf "replace TEST-NET CIDRs in networkPolicy.%sEgressRules before deployment" $workload) -}}
          {{- end -}}
        {{- end -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- end }}
