# RunPod handoff for source development

The existing optional adapter is in backend/app/providers/runpod/ and the GPU worker source is in backend/runpod_worker/. Preserve schemas, cost accounting, caching, idempotency, cancellation, GPU STOP and policy gates. No endpoint, credential or model weight is included. Do not deploy, build/push a cloud container, resolve/download large models, purchase GPU time or call a paid endpoint for an audit. Use offline transport fakes. Connection/setup details are in docs/RUNPOD_INTEGRATION.md.

This summary replaces private operational records only in the GitHub copy.
