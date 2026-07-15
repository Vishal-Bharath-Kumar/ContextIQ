{{/*
Return the fully qualified app name, truncated to 63 chars.
*/}}
{{- define "contextiq-common.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all managed resources.
*/}}
{{- define "contextiq-common.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | default "latest" | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: contextiq
{{- end }}

{{/*
Selector labels used by Deployment.spec.selector and Service.spec.selector.
*/}}
{{- define "contextiq-common.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Return the service account name.
*/}}
{{- define "contextiq-common.serviceAccountName" -}}
{{- include "contextiq-common.fullname" . }}-sa
{{- end }}
