{{- define "plethos.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "plethos.portal.fullname" -}}
{{- printf "%s-portal" (include "plethos.fullname" .) -}}
{{- end -}}

{{- define "plethos.controller.fullname" -}}
{{- printf "%s-controller" (include "plethos.fullname" .) -}}
{{- end -}}

{{- define "plethos.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/*
Name of the Secret holding OIDC/SMTP/session credentials.
Not created by this chart (see NOTES.txt) - create it out of band and either
leave portal.secretName unset (uses the default name below) or point it at
a Secret you already manage.
*/}}
{{- define "plethos.portal.secretName" -}}
{{- .Values.portal.secretName | default (printf "%s-secrets" (include "plethos.portal.fullname" .)) -}}
{{- end -}}

{{/*
Env of the portal image, shared by the portal Deployment and the inactivity-check CronJob: the
job signs keep-alive links the portal has to verify, and sends email through the same SMTP server.
*/}}
{{- define "plethos.portal.env" -}}
- name: VCLUSTERCLAIMS_NAMESPACE
  value: {{ .Release.Namespace }}
{{- if .Values.controller.vclustersBaseDomain }}
- name: VCLUSTERS_BASE_DOMAIN
  value: {{ .Values.controller.vclustersBaseDomain }}
{{- end }}
{{- if .Values.portal.oidc.issuer }}
- name: OIDC_ISSUER
  value: {{ .Values.portal.oidc.issuer }}
{{- end }}
- name: OIDC_CLIENT_ID
  value: {{ .Values.portal.oidc.clientId }}
- name: OIDC_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "plethos.portal.secretName" . }}
      key: OIDC_CLIENT_SECRET
- name: PORTAL_SESSION_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "plethos.portal.secretName" . }}
      key: PORTAL_SESSION_SECRET
- name: CSRF_TOKEN_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "plethos.portal.secretName" . }}
      key: CSRF_TOKEN_SECRET
- name: SUPPORT_EMAIL
  value: {{ .Values.portal.supportEmail }}
- name: PORTAL_BASE_URL
  value: {{ .Values.portal.baseUrl }}
- name: SUPPORTED_VCLUSTER_VERSIONS
  value: {{ .Values.supportedVclusterVersions | quote }}
{{- if .Values.portal.smtp.host }}
- name: SMTP_HOST
  value: {{ .Values.portal.smtp.host }}
{{- end }}
- name: SMTP_PORT
  value: {{ .Values.portal.smtp.port | quote }}
- name: SMTP_FROM_ADDRESS
  value: {{ .Values.portal.smtp.fromAddress }}
- name: SMTP_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ include "plethos.portal.secretName" . }}
      key: SMTP_USERNAME
- name: SMTP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "plethos.portal.secretName" . }}
      key: SMTP_PASSWORD
{{- end -}}
