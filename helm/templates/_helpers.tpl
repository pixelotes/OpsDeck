{{/*
Expand the name of the chart.
*/}}
{{- define "opsdeck.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "opsdeck.fullname" -}}
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
{{- define "opsdeck.labels" -}}
helm.sh/chart: {{ include "opsdeck.chart" . }}
{{ include "opsdeck.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "opsdeck.selectorLabels" -}}
app.kubernetes.io/name: {{ include "opsdeck.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "opsdeck.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}
{{/*
Where the internal database lives: the Bitnami subchart's primary Service.
*/}}
{{- define "opsdeck.internalDbHost" -}}
{{- printf "%s-postgresql" .Release.Name }}
{{- end }}

{{/*
The Secret holding the internal database password, and the key inside it. Bitnami
creates <release>-postgresql with key "password" unless auth.existingSecret is given.
*/}}
{{- define "opsdeck.internalDbSecretName" -}}
{{- .Values.postgresql.auth.existingSecret | default (printf "%s-postgresql" .Release.Name) }}
{{- end }}
{{- define "opsdeck.internalDbSecretKey" -}}
{{- (default (dict) .Values.postgresql.auth.secretKeys).userPasswordKey | default "password" }}
{{- end }}

{{/*
DATABASE_URL env entries for whichever database is configured. The password never
appears in the rendered manifest: it is read from a Secret into DB_PASSWORD_RAW and
substituted by the kubelet.
*/}}
{{- define "opsdeck.databaseEnv" -}}
{{- if eq .Values.database.type "internal" }}
- name: DB_PASSWORD_RAW
  valueFrom:
    secretKeyRef:
      name: {{ include "opsdeck.internalDbSecretName" . }}
      key: {{ include "opsdeck.internalDbSecretKey" . }}
- name: DATABASE_URL
  value: postgresql://{{ .Values.postgresql.auth.username }}:$(DB_PASSWORD_RAW)@{{ include "opsdeck.internalDbHost" . }}:5432/{{ .Values.postgresql.auth.database }}
{{- else if eq .Values.database.type "external" }}
- name: DB_PASSWORD_RAW
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.external.existingSecret.name }}
      key: {{ .Values.database.external.existingSecret.key }}
- name: DATABASE_URL
  value: postgresql://{{ .Values.database.external.username }}:$(DB_PASSWORD_RAW)@{{ .Values.database.external.host }}:{{ .Values.database.external.port }}/{{ .Values.database.external.database }}
{{- end }}
{{- end }}
