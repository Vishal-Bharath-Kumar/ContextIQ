{{/*
Vault Agent Injector annotation stanza.
Rendered into the pod template metadata.annotations block of every service Deployment.

Controls:
  vault.enabled    (bool)   — toggle entire stanza; set false in dev
  vault.role       (string) — Kubernetes auth role (must match TASK-US047-02)
  vault.secrets    (list)   — secrets to inject; each item has name/vaultPath/format

Supported formats:
  env     → `export KEY="value"` lines  (shell-sourceable)
  dotenv  → `KEY=value` lines           (12-factor compatible)
  json    → raw JSON blob               (fallback)
*/}}
{{- define "contextiq-common.vault.annotations" -}}
{{- if .Values.vault.enabled -}}
vault.hashicorp.com/agent-inject: "true"
vault.hashicorp.com/role: {{ .Values.vault.role | quote }}
vault.hashicorp.com/agent-pre-populate-only: "false"
vault.hashicorp.com/agent-inject-token: "false"
vault.hashicorp.com/agent-cache-enable: "true"
vault.hashicorp.com/agent-cache-use-auto-auth-token: "true"
{{- range .Values.vault.secrets }}
vault.hashicorp.com/agent-inject-secret-{{ .name }}: {{ .vaultPath | quote }}
{{- if eq .format "env" }}
vault.hashicorp.com/agent-inject-template-{{ .name }}: |
  {{`{{- with secret `}}{{ .vaultPath | quote }}{{` -}}`}}
  {{`{{- range $k, $v := .Data.data }}`}}
  export {{`{{ $k }}`}}={{`"{{ $v }}"`}}
  {{`{{- end }}`}}
  {{`{{- end }}`}}
{{- else if eq .format "dotenv" }}
vault.hashicorp.com/agent-inject-template-{{ .name }}: |
  {{`{{- with secret `}}{{ .vaultPath | quote }}{{` -}}`}}
  {{`{{- range $k, $v := .Data.data }}`}}
  {{`{{ $k }}`}}={{`{{ $v }}`}}
  {{`{{- end }}`}}
  {{`{{- end }}`}}
{{- else }}
vault.hashicorp.com/agent-inject-template-{{ .name }}: |
  {{`{{- with secret `}}{{ .vaultPath | quote }}{{` -}}`}}
  {{`{{- .Data.data | toJSON }}`}}
  {{`{{- end }}`}}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
