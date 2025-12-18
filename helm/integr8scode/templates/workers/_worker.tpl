{{/*
Generate a worker deployment.
Usage: {{ include "integr8scode.worker" (dict "root" . "name" "k8s-worker" "config" .Values.workers.k8sWorker) }}
*/}}
{{- define "integr8scode.worker" -}}
{{- $root := .root -}}
{{- $name := .name -}}
{{- $config := .config -}}
{{- if $config.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "integr8scode.fullname" $root }}-{{ $name }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    {{- include "integr8scode.labels" $root | nindent 4 }}
    app.kubernetes.io/component: {{ $name }}
spec:
  replicas: {{ $config.replicas | default 1 }}
  selector:
    matchLabels:
      app: {{ include "integr8scode.fullname" $root }}-{{ $name }}
  template:
    metadata:
      labels:
        app: {{ include "integr8scode.fullname" $root }}-{{ $name }}
        {{- include "integr8scode.labels" $root | nindent 8 }}
        app.kubernetes.io/component: {{ $name }}
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/secrets/env-secret.yaml") $root | sha256sum }}
    spec:
      serviceAccountName: {{ include "integr8scode.serviceAccountName" $root }}
      containers:
      - name: {{ $name }}
        image: {{ include "integr8scode.backendImage" $root }}
        imagePullPolicy: {{ $root.Values.global.imagePullPolicy | default "IfNotPresent" }}
        command:
          {{- toYaml $config.command | nindent 10 }}
        envFrom:
        - secretRef:
            name: {{ include "integr8scode.fullname" $root }}-env
        env:
        - name: KAFKA_CONSUMER_GROUP_ID
          value: {{ $config.consumerGroupId | quote }}
        - name: TRACING_SERVICE_NAME
          value: {{ $name | quote }}
        {{- if $config.requiresKubeconfig }}
        - name: KUBECONFIG
          value: "/app/kubeconfig.yaml"
        {{- end }}
        resources:
          {{- if $config.resources }}
          {{- toYaml $config.resources | nindent 10 }}
          {{- else }}
          {{- toYaml $root.Values.workers.common.resources | nindent 10 }}
          {{- end }}
        {{- if $config.requiresKubeconfig }}
        volumeMounts:
        - name: kubeconfig
          mountPath: /app/kubeconfig.yaml
          subPath: kubeconfig.yaml
          readOnly: true
        {{- end }}
      {{- if $config.requiresKubeconfig }}
      volumes:
      - name: kubeconfig
        secret:
          secretName: {{ $root.Values.kubeconfig.secretName }}
      {{- end }}
      restartPolicy: Always
{{- end }}
{{- end -}}
