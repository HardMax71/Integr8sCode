{{/*
Expand the name of the chart.
*/}}
{{- define "integr8scode.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "integr8scode.fullname" -}}
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
{{- define "integr8scode.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "integr8scode.labels" -}}
helm.sh/chart: {{ include "integr8scode.chart" . }}
{{ include "integr8scode.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: integr8scode
{{- end }}

{{/*
Selector labels
*/}}
{{- define "integr8scode.selectorLabels" -}}
app.kubernetes.io/name: {{ include "integr8scode.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "integr8scode.serviceAccountName" -}}
{{- if .Values.rbac.create }}
{{- default (include "integr8scode.fullname" .) .Values.rbac.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.rbac.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Backend image reference
*/}}
{{- define "integr8scode.backendImage" -}}
{{- printf "%s:%s" .Values.images.backend.repository .Values.images.backend.tag }}
{{- end }}

{{/*
Frontend image reference
*/}}
{{- define "integr8scode.frontendImage" -}}
{{- printf "%s:%s" .Values.images.frontend.repository .Values.images.frontend.tag }}
{{- end }}

{{/*
Redis host - uses Bitnami sub-chart naming convention
*/}}
{{- define "integr8scode.redisHost" -}}
{{- if .Values.redis.enabled }}
{{- printf "%s-redis-master" .Release.Name }}
{{- else }}
{{- .Values.externalRedis.host }}
{{- end }}
{{- end }}

{{/*
MongoDB host - uses Bitnami sub-chart naming convention
*/}}
{{- define "integr8scode.mongodbHost" -}}
{{- if .Values.mongodb.enabled }}
{{- printf "%s-mongodb" .Release.Name }}
{{- else }}
{{- .Values.externalMongodb.host }}
{{- end }}
{{- end }}

{{/*
MongoDB URL - with URL-encoded credentials (RFC 3986)
*/}}
{{- define "integr8scode.mongodbUrl" -}}
{{- if .Values.mongodb.enabled }}
{{- if .Values.mongodb.auth.enabled }}
{{- printf "mongodb://%s:%s@%s:27017/integr8scode?authSource=admin" (.Values.mongodb.auth.rootUser | urlquery) (.Values.mongodb.auth.rootPassword | urlquery) (include "integr8scode.mongodbHost" .) }}
{{- else }}
{{- printf "mongodb://%s:27017/integr8scode" (include "integr8scode.mongodbHost" .) }}
{{- end }}
{{- else }}
{{- .Values.externalMongodb.url }}
{{- end }}
{{- end }}

{{/*
Kafka bootstrap servers
*/}}
{{- define "integr8scode.kafkaBootstrapServers" -}}
{{- printf "%s-kafka:29092" .Release.Name }}
{{- end }}

{{/*
Schema Registry URL
*/}}
{{- define "integr8scode.schemaRegistryUrl" -}}
{{- printf "http://%s-schema-registry:8081" .Release.Name }}
{{- end }}

{{/*
Jaeger host
*/}}
{{- define "integr8scode.jaegerHost" -}}
{{- printf "%s-jaeger" .Release.Name }}
{{- end }}

{{/*
Generate worker labels
*/}}
{{- define "integr8scode.workerLabels" -}}
{{ include "integr8scode.labels" .root }}
app.kubernetes.io/component: {{ .name }}
{{- end }}

{{/*
Generate worker selector labels
*/}}
{{- define "integr8scode.workerSelectorLabels" -}}
app.kubernetes.io/name: {{ include "integr8scode.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .name }}
{{- end }}
