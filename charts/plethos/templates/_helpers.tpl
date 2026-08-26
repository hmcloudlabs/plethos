{{/*
Base name of the release, used to prefix every resource.
With `helm install plethos ./charts/plethos` this resolves to "plethos", matching
the fixed names used by the k8s/ Kustomize base (plethos-portal, plethos-controller, ...).
Installing under a different release name prefixes resources with that name instead,
so multiple installs can coexist in a cluster without colliding.
*/}}
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
