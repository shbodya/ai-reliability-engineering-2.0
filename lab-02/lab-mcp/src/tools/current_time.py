"""current_time tool."""

from datetime import datetime, timezone

from mcp.types import ToolAnnotations

from core.server import mcp


@mcp.tool(
    annotations=ToolAnnotations(
        title="Current UTC time",
        readOnlyHint=True,
    ),
)
def current_time() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
