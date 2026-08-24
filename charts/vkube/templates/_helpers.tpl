{{/*
Base name of the release, used to prefix every resource.
With `helm install vkube ./charts/vkube` this resolves to "vkube", matching
the fixed names used by the k8s/ Kustomize base (vkube-portal, vkube-controller, ...).
Installing under a different release name prefixes resources with that name instead,
so multiple installs can coexist in a cluster without colliding.
*/}}
{{- define "vkube.fullname" -}}
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

{{- define "vkube.portal.fullname" -}}
{{- printf "%s-portal" (include "vkube.fullname" .) -}}
{{- end -}}

{{- define "vkube.controller.fullname" -}}
{{- printf "%s-controller" (include "vkube.fullname" .) -}}
{{- end -}}

{{- define "vkube.labels" -}}
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
{{- define "vkube.portal.secretName" -}}
{{- .Values.portal.secretName | default (printf "%s-secrets" (include "vkube.portal.fullname" .)) -}}
{{- end -}}
