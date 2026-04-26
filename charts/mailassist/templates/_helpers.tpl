{{/*
Expand the name of the chart.
Truncated to 63 characters (Kubernetes name limit).
*/}}
{{- define "mailassist.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this.
If fullnameOverride is provided, use that. If nameOverride is provided, use that
as the base. Otherwise combine release name and chart name.
*/}}
{{- define "mailassist.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "mailassist.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels for all resources.
*/}}
{{- define "mailassist.labels" -}}
helm.sh/chart: {{ include "mailassist.chart" . }}
{{ include "mailassist.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels used in matchLabels and pod templates.
*/}}
{{- define "mailassist.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mailassist.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the ServiceAccount to use.
If serviceAccount.create is true, use the custom name or fall back to fullname.
If serviceAccount.create is false, use the custom name or fall back to "default".
*/}}
{{- define "mailassist.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "mailassist.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the Secret to use.
If secrets.existingSecret is set, use that. Otherwise use the fullname.
*/}}
{{- define "mailassist.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- include "mailassist.fullname" . }}
{{- end }}
{{- end }}

{{/*
Create a fully qualified name for PostgreSQL resources.
*/}}
{{- define "mailassist.postgresql.fullname" -}}
{{- printf "%s-postgresql" (include "mailassist.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a fully qualified name for Valkey resources.
*/}}
{{- define "mailassist.valkey.fullname" -}}
{{- printf "%s-valkey" (include "mailassist.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Generate the DATABASE_URL.
When postgresql.enabled is true, build the internal connection string.
When postgresql.enabled is false, use the external URL from externalDatabase.url.
*/}}
{{- define "mailassist.databaseUrl" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "postgresql+asyncpg://%s:%s@%s:5432/%s" .Values.postgresql.auth.username .Values.secrets.postgresPassword (include "mailassist.postgresql.fullname" .) .Values.postgresql.auth.database }}
{{- else }}
{{- .Values.externalDatabase.url }}
{{- end }}
{{- end }}

{{/*
Generate the VALKEY_URL.
When valkey.enabled is true, build the internal connection string.
When valkey.enabled is false, use the external URL from externalValkey.url.
*/}}
{{- define "mailassist.valkeyUrl" -}}
{{- if .Values.valkey.enabled }}
{{- printf "redis://:%s@%s:6379/0" .Values.secrets.valkeyPassword (include "mailassist.valkey.fullname" .) }}
{{- else }}
{{- .Values.externalValkey.url }}
{{- end }}
{{- end }}
