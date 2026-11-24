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

{{- /* An engine image reference: a version tag (never a moving one such as latest or main),
and its digest. A digest this chart knows belongs to one version; under another tag it is a
stale pin, and the render fails. */ -}}
{{- define "sortyard.engine.image" -}}
{{- $tag := toString (required "an engine image needs a tag (a pinned version)" .tag) -}}
{{- if not (regexMatch "^[0-9]+\\.[0-9]+\\.[0-9]+([.-][A-Za-z0-9.-]+)?$" $tag) -}}
{{- fail (printf "an engine image must be pinned to a version such as 1.32.2, not %q" $tag) -}}
{{- end -}}
{{- $known := dict "sha256:7bf69188a6232fea14869b9cef3d94aa82a1601d99517f7e86c71f22da4e0670" "1.32.2" "sha256:4a95866efba29d7e17ab012df5232795e8b0ad0f7d5f9d1ec4df321f7792a754" "1.32.2" -}}
{{- with .digest -}}
{{- $of := get $known . -}}
{{- if and $of (ne $of $tag) -}}
{{- fail (printf "engine image %s: tag %s is pinned to the digest of %s; change the digest with the tag, or clear it" $.repository $tag $of) -}}
{{- end -}}
{{- end -}}
{{- printf "%s:%s" .repository $tag -}}
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

{{- /*
The kernel service (templates/kernel.yaml). Its files are two ConfigMaps: the lane capability
files (mounted by the API too), and the kernel's own (worker configuration, decision policy,
the init container's script).
*/ -}}
{{- define "sortyard.kernel.fullname" -}}
{{- printf "%s-kernel" (include "sortyard.fullname" .) -}}
{{- end -}}

{{- define "sortyard.lanes.fullname" -}}
{{- printf "%s-lanes" (include "sortyard.fullname" .) -}}
{{- end -}}

{{- /* The lane capability files, one key per lane: <name>.toml. */ -}}
{{- define "sortyard.lanes.data" -}}
{{- if not .Values.kernel.lanes -}}
{{- fail "kernel.lanes is required when kernel.enabled=true: at least one lane capability file (name: text)" -}}
{{- end -}}
{{- range $name, $text := .Values.kernel.lanes }}
{{- if not (regexMatch "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$" $name) }}
{{- fail (printf "kernel.lanes: %q is not a file name of lower-case letters, digits and dashes" $name) }}
{{- end }}
{{- if not $text }}
{{- fail (printf "kernel.lanes.%s is empty: it is the text of a lane capability file" $name) }}
{{- end }}
{{ printf "%s.toml" $name }}: {{ toJson $text }}
{{- end }}
{{- end -}}

{{- /* The worker configuration file (sortyard.services.kernel reads it), as TOML: a JSON string
or array of strings is the same TOML value. */ -}}
{{- define "sortyard.kernel.workerConfig" -}}
{{- $w := .Values.kernel.worker -}}
{{- with $w.gitUrl }}
git-url = {{ toJson . }}
{{- end }}
{{- with $w.command }}
command = {{ toJson . }}
{{- end }}
{{- with $w.deadlineSeconds }}
deadline = {{ int . }}
{{- end }}
{{- with $w.ttlSeconds }}
ttl = {{ int . }}
{{- end }}
{{- with $w.tokenAgeSeconds }}
token-age = {{ int . }}
{{- end }}

[agents]
{{- range $mode := list "build" "fix" "review" }}
{{- $argv := index $w.agents $mode }}
{{- if not $argv }}
{{- fail (printf "kernel.worker.agents.%s is required when kernel.enabled=true: the agent command (an argv) for %s work" $mode $mode) }}
{{- end }}
{{ $mode }} = {{ toJson $argv }}
{{- end }}

[secrets]
{{- range $name, $ref := $w.secrets }}
{{ toJson $name }} = { secret = {{ toJson (required (printf "kernel.worker.secrets.%s.secret is required" $name) $ref.secret) }}, key = {{ toJson (required (printf "kernel.worker.secrets.%s.key is required" $name) $ref.key) }} }
{{- end }}

[services]
{{- range $name, $url := $w.services }}
{{ toJson $name }} = {{ toJson $url }}
{{- end }}
{{- end -}}

{{- /* The Secret (key `password`) the kernel reads the database password from: the same as the
API's, and with an external Postgres it must be named. */ -}}
{{- define "sortyard.kernel.database.secretName" -}}
{{- if .Values.postgres.enabled -}}
{{- include "sortyard.postgres.secretName" . -}}
{{- else -}}
{{- required "postgres.auth.existingSecret is required when kernel.enabled=true and postgres.enabled=false: the name of a Secret with key `password` for the external database" .Values.postgres.auth.existingSecret -}}
{{- end -}}
{{- end -}}

{{- define "sortyard.kernel.workers.namespace" -}}
{{- .Values.kernel.workers.namespace | default .Release.Namespace -}}
{{- end -}}
