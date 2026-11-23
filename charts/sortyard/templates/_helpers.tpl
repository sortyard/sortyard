{{- define "sortyard.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "sortyard.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "sortyard.selector" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "sortyard.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{- define "sortyard.postgres.fullname" -}}
{{- printf "%s-postgres" (include "sortyard.fullname" .) -}}
{{- end -}}

{{- define "sortyard.postgres.host" -}}
{{- if .Values.postgres.enabled -}}
{{- include "sortyard.postgres.fullname" . -}}
{{- else -}}
{{- required "postgres.external.host is required when postgres.enabled=false" .Values.postgres.external.host -}}
{{- end -}}
{{- end -}}

{{- define "sortyard.postgres.port" -}}
{{- if .Values.postgres.enabled -}}5432{{- else -}}{{ .Values.postgres.external.port }}{{- end -}}
{{- end -}}

{{- define "sortyard.postgres.secretName" -}}
{{- .Values.postgres.auth.existingSecret | default (include "sortyard.postgres.fullname" .) -}}
{{- end -}}

{{- /*
The workflow engine server (templates/engine.yaml). Its store is a Postgres server and nothing
else: engine.database.host when set (an external server, with its own required Secret
reference), otherwise the same server as the API's.
*/ -}}
{{- define "sortyard.engine.fullname" -}}
{{- printf "%s-engine" (include "sortyard.fullname" .) -}}
{{- end -}}

{{- define "sortyard.engine.target" -}}
{{- printf "%s:%v" (include "sortyard.engine.fullname" .) .Values.engine.service.port -}}
{{- end -}}

{{- define "sortyard.engine.image" -}}
{{- $tag := required "an engine image needs a tag (a pinned version)" .tag -}}
{{- if eq (toString $tag) "latest" }}{{ fail "an engine image must be pinned to a version, not latest" }}{{ end -}}
{{- printf "%s:%s" .repository (toString $tag) -}}
{{- with .digest }}@{{ . }}{{ end -}}
{{- end -}}

{{- define "sortyard.engine.database.host" -}}
{{- .Values.engine.database.host | default (include "sortyard.postgres.host" .) -}}
{{- end -}}

{{- define "sortyard.engine.database.port" -}}
{{- if .Values.engine.database.host -}}{{ .Values.engine.database.port }}{{- else -}}{{ include "sortyard.postgres.port" . }}{{- end -}}
{{- end -}}

{{- define "sortyard.engine.database.username" -}}
{{- if .Values.engine.database.host -}}
{{- required "engine.database.username is required when engine.database.host is set" .Values.engine.database.username -}}
{{- else -}}
{{- .Values.postgres.auth.username -}}
{{- end -}}
{{- end -}}

{{- /* The Secret (key `password`) the engine reads its database password from. Only the
chart's own Postgres has a default; an external database must name its Secret. */ -}}
{{- define "sortyard.engine.database.secretName" -}}
{{- if .Values.engine.database.host -}}
{{- required "engine.database.existingSecret is required when engine.database.host is set: the name of a Secret with key `password` for the engine's external database" .Values.engine.database.existingSecret -}}
{{- else if .Values.postgres.enabled -}}
{{- include "sortyard.postgres.secretName" . -}}
{{- else -}}
{{- required "postgres.auth.existingSecret is required when engine.enabled=true and postgres.enabled=false: the name of a Secret with key `password` for the external database (or set engine.database.host and engine.database.existingSecret to give the engine its own)" .Values.postgres.auth.existingSecret -}}
{{- end -}}
{{- end -}}
