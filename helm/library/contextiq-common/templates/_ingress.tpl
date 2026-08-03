{{/*
Reusable Ingress template (nginx ingress controller).
Caller: {{ include "contextiq-common.ingress" . }}
*/}}
{{- define "contextiq-common.ingress" -}}
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "contextiq-common.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    {{- include "contextiq-common.labels" . | nindent 4 }}
spec:
  ingressClassName: {{ .Values.ingress.className }}
  rules:
    - host: {{ .Values.ingress.host }}
      http:
        paths:
          - path: {{ .Values.ingress.path }}
            pathType: Prefix
            backend:
              service:
                name: {{ include "contextiq-common.fullname" . }}
                port:
                  number: {{ .Values.service.port }}
{{- end }}
{{- end }}
