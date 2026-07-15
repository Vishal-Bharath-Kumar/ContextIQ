{{/*
Reusable ClusterIP Service template.
Caller: {{ include "contextiq-common.service" . }}
*/}}
{{- define "contextiq-common.service" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "contextiq-common.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    {{- include "contextiq-common.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.targetPort }}
      protocol: TCP
      name: http
  selector:
    {{- include "contextiq-common.selectorLabels" . | nindent 4 }}
{{- end }}
