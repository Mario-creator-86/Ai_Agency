"""The AMN GPU work server that runs inside a RunPod Serverless worker.

It is a separate program from the studio: it runs in the worker image (backend/runpod_worker/
Dockerfile) on top of the official worker-comfyui base, next to a local ComfyUI. The studio
imports only ``runpod_worker.contract`` (stdlib only), the shared batch contract.
"""
