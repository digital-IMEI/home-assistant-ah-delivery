"""Optional Track & Trace V2 probe for Albert Heijn Delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api import AhApiClient

from .const import TRACK_TRACE_QUERY_TEMPLATE
from .diagnostic_helpers import sanitize_for_diagnostics
from .exceptions import AhDeliveryError
from .models import TrackTraceData, parse_track_trace


async def async_fetch_track_trace(
    client: AhApiClient,
    order_id: int,
    timezone_name: str,
    fetched_at,
    delivery_date: str | None,
) -> tuple[TrackTraceData | None, dict[str, Any]]:
    """Fetch Track & Trace without ever making it a hard dependency.

    appie-go documents FetchOrderTrackTrace as order(id) -> delivery ->
    trackAndTraceV2. We inject the integer order id directly into the query so
    the existing AH GraphQL request path remains untouched.
    """
    query = TRACK_TRACE_QUERY_TEMPLATE.replace("__ORDER_ID__", str(int(order_id)))
    try:
        data = await client._graphql(query)  # noqa: SLF001 - same integration package
    except AhDeliveryError as err:
        return None, {"ok": False, "error": str(err)}

    track = parse_track_trace(data, timezone_name, fetched_at, delivery_date)
    return track, {
        "ok": True,
        "available": track is not None,
        "data": sanitize_for_diagnostics(data),
    }
