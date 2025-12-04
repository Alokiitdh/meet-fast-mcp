# google_meet_server.py
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from gmeet.google_auth import get_calendar_service

# Create the MCP server
mcp = FastMCP(
    name="Google Meet MCP Server",
    instructions="""
This MCP server manages Google Meet meetings via the Google Calendar API.

Tools:
- create-meeting: Create a new Google Meet event
- list-meetings: List upcoming Google Meet events
- get-meeting-details: Get details of a specific meeting
- update-meeting: Update an existing meeting
- delete-meeting: Delete a meeting (calendar event)
""",
)

DEFAULT_CALENDAR_ID = "primary"


def _rfc3339_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rfc3339_in(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# ---------- TOOL 1: create-meeting ----------

@mcp.tool(name="create-meeting")
def create_meeting(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    timezone_str: str = "UTC",
) -> Dict[str, Any]:
    """
    Create a new Google Calendar event with a Google Meet link.

    Args:
        summary: Title of the meeting.
        start_iso: Start time in RFC3339 / ISO 8601 format (e.g. "2025-11-21T10:00:00+05:30").
        end_iso: End time in RFC3339 / ISO 8601 format.
        description: Optional description/agenda.
        attendees: Optional list of attendee email addresses.
        timezone_str: IANA timezone string, e.g. "Asia/Kolkata" or "UTC".

    Returns:
        Basic info including eventId and Google Meet join URL (if available).
    """
    try:
        service = get_calendar_service()

        event_body: Dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start_iso, "timeZone": timezone_str},
            "end": {"dateTime": end_iso, "timeZone": timezone_str},
        }

        if description:
            event_body["description"] = description

        if attendees:
            event_body["attendees"] = [{"email": email} for email in attendees]

        # Request a Google Meet link via conferenceData.createRequest
        event_body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

        created_event = (
            service.events()
            .insert(
                calendarId=DEFAULT_CALENDAR_ID,
                body=event_body,
                conferenceDataVersion=1,
            )
            .execute()
        )

        meet_link = None
        conf = created_event.get("conferenceData", {})
        for ep in conf.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri")
                break

        return {
            "eventId": created_event.get("id"),
            "htmlLink": created_event.get("htmlLink"),
            "hangoutLink": created_event.get("hangoutLink"),  # legacy field
            "meetLink": meet_link,
            "summary": created_event.get("summary"),
            "start": created_event.get("start"),
            "end": created_event.get("end"),
        }
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Failed to create meeting: {e}")


# ---------- TOOL 2: list-meetings ----------

@mcp.tool(name="list-meetings")
def list_meetings(
    time_min_iso: Optional[str] = None,
    time_max_iso: Optional[str] = None,
    max_results: int = 20,
    only_with_meet_link: bool = True,
) -> List[Dict[str, Any]]:
    """
    List upcoming Google Calendar events, optionally filtered to only those with Google Meet links.

    Args:
        time_min_iso: Start of the time window (RFC3339). Defaults to now.
        time_max_iso: End of the time window (RFC3339). Defaults to +7 days from now.
        max_results: Max number of events to return.
        only_with_meet_link: If true, return only events that have Meet/Conference data.

    Returns:
        A list of events with basic details and (if present) the Meet URL.
    """
    try:
        service = get_calendar_service()

        time_min = time_min_iso or _rfc3339_now()
        time_max = time_max_iso or _rfc3339_in(7)

        events_result = (
            service.events()
            .list(
                calendarId=DEFAULT_CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
                showDeleted=False,
            )
            .execute()
        )

        events = events_result.get("items", [])

        def extract_meet_link(event: Dict[str, Any]) -> Optional[str]:
            # New style: conferenceData.entryPoints
            conf = event.get("conferenceData", {})
            for ep in conf.get("entryPoints", []):
                if ep.get("entryPointType") == "video":
                    return ep.get("uri")
            # Legacy field
            return event.get("hangoutLink")

        results = []
        for ev in events:
            meet_link = extract_meet_link(ev)
            if only_with_meet_link and not meet_link:
                continue

            results.append(
                {
                    "eventId": ev.get("id"),
                    "summary": ev.get("summary"),
                    "start": ev.get("start"),
                    "end": ev.get("end"),
                    "meetLink": meet_link,
                    "htmlLink": ev.get("htmlLink"),
                }
            )

        return results
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Failed to list meetings: {e}")


# ---------- TOOL 3: get-meeting-details ----------

@mcp.tool(name="get-meeting-details")
def get_meeting_details(event_id: str) -> Dict[str, Any]:
    """
    Get full details of a specific Google Calendar event (meeting).

    Args:
        event_id: The Google Calendar event ID.

    Returns:
        The full event resource, including conferenceData if available.
    """
    try:
        service = get_calendar_service()
        event = (
            service.events()
            .get(
                calendarId=DEFAULT_CALENDAR_ID,
                eventId=event_id,
                # conferenceDataVersion=1,
            )
            .execute()
        )
        return event
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Failed to get meeting details for {event_id}: {e}")


# ---------- TOOL 4: update-meeting ----------

@mcp.tool(name="update-meeting")
def update_meeting(
    event_id: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    timezone_str: Optional[str] = "UTC",
) -> Dict[str, Any]:
    """
    Update basic fields of an existing meeting.

    Args:
        event_id: ID of the event to update.
        summary: New title (optional).
        description: New description (optional).
        start_iso: New start time (optional, RFC3339).
        end_iso: New end time (optional, RFC3339).
        timezone_str: New time zone (optional).

    Returns:
        The updated event.
    """
    try:
        service = get_calendar_service()

        # Get current event
        event = (
            service.events()
            .get(
                calendarId=DEFAULT_CALENDAR_ID,
                eventId=event_id,
                # conferenceDataVersion=1,
            )
            .execute()
        )

        if summary is not None:
            event["summary"] = summary
        if description is not None:
            event["description"] = description

        if start_iso is not None:
            if "start" not in event:
                event["start"] = {}
            event["start"]["dateTime"] = start_iso
            if timezone_str:
                event["start"]["timeZone"] = timezone_str

        if end_iso is not None:
            if "end" not in event:
                event["end"] = {}
            event["end"]["dateTime"] = end_iso
            if timezone_str:
                event["end"]["timeZone"] = timezone_str

        if timezone_str and "start" in event and "timeZone" not in event["start"]:
            event["start"]["timeZone"] = timezone_str
        if timezone_str and "end" in event and "timeZone" not in event["end"]:
            event["end"]["timeZone"] = timezone_str

        updated_event = (
            service.events()
            .update(
                calendarId=DEFAULT_CALENDAR_ID,
                eventId=event_id,
                body=event,
                conferenceDataVersion=1,  # keep conferenceData (Meet link) intact
            )
            .execute()
        )

        return updated_event
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Failed to update meeting {event_id}: {e}")


# ---------- TOOL 5: delete-meeting ----------

@mcp.tool(name="delete-meeting")
def delete_meeting(event_id: str) -> Dict[str, Any]:
    """
    Delete a Google Calendar event (cancels the meeting).

    Args:
        event_id: The event ID to delete.

    Returns:
        A small status object.
    """
    try:
        service = get_calendar_service()
        service.events().delete(
            calendarId=DEFAULT_CALENDAR_ID,
            eventId=event_id,
        ).execute()

        return {"status": "deleted", "eventId": event_id}
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Failed to delete meeting {event_id}: {e}")


if __name__ == "__main__":
    # 
    mcp.run(transport="http", host="127.0.0.1", port= 8000)
