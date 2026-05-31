"""pod_count tool."""

import json
import os
import ssl
import urllib.request

from mcp.types import ToolAnnotations

from core.server import mcp


SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"


def _api_call(path: str) -> dict:
    token_path = os.path.join(SA_DIR, "token")
    ca_path = os.path.join(SA_DIR, "ca.crt")
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    with open(token_path) as f:
        token = f.read().strip()
    ctx = ssl.create_default_context(cafile=ca_path)
    req = urllib.request.Request(
        f"https://{host}:{port}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return json.loads(resp.read().decode())


@mcp.tool(
    annotations=ToolAnnotations(
        title="Pod count in namespace",
        readOnlyHint=True,
    ),
)
def pod_count(namespace: str) -> str:
    """Return number of pods in the given namespace via in-cluster API."""
    try:
        data = _api_call(f"/api/v1/namespaces/{namespace}/pods")
        return f"{namespace}: {len(data.get('items', []))} pods"
    except Exception as exc:
        return f"error: {exc}"
