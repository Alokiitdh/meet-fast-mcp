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
    mcp.run(transport="http", host="127.0.0.1", port= 8001)


def _get_all_blocking_calendars(service) -> List[str]:
    """
    Returns calendar IDs that should block availability.
    Skips calendars marked as 'free' or 'transparent'.
    """
    calendars = []
    page_token = None

    while True:
        resp = (
            service.calendarList()
            .list(pageToken=page_token)
            .execute()
        )

        for cal in resp.get("items", []):
            # Only calendars that actually block time
            if cal.get("selected", True) and cal.get("accessRole") != "reader":
                calendars.append(cal["id"])

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return calendars
    
# ---------- TOOL 6: freebusy ----------

@mcp.tool(name="freebusy")
def freebusy(
    time_min_iso: str,
    time_max_iso: str,
    include_all_calendars: bool = True,
    timezone_str: str = "UTC",
) -> Dict[str, List[Dict[str, str]]]:
    """
    Query Google Calendar FreeBusy API to get all busy time ranges,
    including Out of Office, Focus Time, and secondary calendars.

    Args:
        time_min_iso: Start of time window (RFC3339 UTC).
        time_max_iso: End of time window (RFC3339 UTC).
        include_all_calendars: If true, includes all blocking calendars.
        timezone_str: Timezone for response (default: UTC).

    Returns:
        {
          "<calendar_id>": [
            {"start": "...", "end": "..."}
          ]
        }
    """
    try:
        service = get_calendar_service()

        if include_all_calendars:
            calendar_ids = _get_all_blocking_calendars(service)
        else:
            calendar_ids = [DEFAULT_CALENDAR_ID]

        body = {
            "timeMin": time_min_iso,
            "timeMax": time_max_iso,
            "timeZone": timezone_str,
            "items": [{"id": cal_id} for cal_id in calendar_ids],
        }

        response = service.freebusy().query(body=body).execute()

        busy_map: Dict[str, List[Dict[str, str]]] = {}

        for cal_id, data in response.get("calendars", {}).items():
            busy_map[cal_id] = data.get("busy", [])

        return busy_map


    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Failed to query freebusy: {e}")


# ---------- TOOL 7: find-best-meeting-time ----------

@mcp.tool(name="find-best-meeting-time")
def find_best_meeting_time(
    duration_minutes: int,
    time_min_iso: str,
    time_max_iso: str,
    calendar_ids: Optional[List[str]] = None,
    timezone_str: str = "UTC"
) -> List[str]:
    """
    Find available meeting slots that accommodate the requested duration.
    
    Args:
        duration_minutes: Length of the meeting in minutes.
        time_min_iso: Start of search window (RFC3339).
        time_max_iso: End of search window (RFC3339).
        calendar_ids: List of calendar IDs to check for conflicts (defaults to primary + blocking).
        timezone_str: Timezone for input/output interpretation (default: UTC).
        
    Returns:
        List of available start times (RFC3339 strings) for the meeting.
    """
    try:
        service = get_calendar_service()
        
        # 1. Determine calendars to check
        if calendar_ids is None:
             calendar_ids = _get_all_blocking_calendars(service)
             if DEFAULT_CALENDAR_ID not in calendar_ids:
                 calendar_ids.append(DEFAULT_CALENDAR_ID)

        # 2. Query FreeBusy
        body = {
            "timeMin": time_min_iso,
            "timeMax": time_max_iso,
            "timeZone": timezone_str,
            "items": [{"id": cal_id} for cal_id in calendar_ids],
        }
        resp = service.freebusy().query(body=body).execute()
        
        # 3. Parse and merge busy intervals
        busy_intervals = []
        for cal_data in resp.get("calendars", {}).values():
            for error in cal_data.get("errors", []):
                # Log or ignore errors? For now ignore.
                pass
            for busy in cal_data.get("busy", []):
                # Parse to datetime
                start = datetime.fromisoformat(busy["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(busy["end"].replace("Z", "+00:00"))
                busy_intervals.append((start, end))
                
        busy_intervals.sort(key=lambda x: x[0])
        
        merged = []
        if busy_intervals:
            curr_start, curr_end = busy_intervals[0]
            for next_start, next_end in busy_intervals[1:]:
                if next_start < curr_end:
                    curr_end = max(curr_end, next_end)
                else:
                    merged.append((curr_start, curr_end))
                    curr_start, curr_end = next_start, next_end
            merged.append((curr_start, curr_end))
            
        # 4. Find gaps
        search_start = datetime.fromisoformat(time_min_iso.replace("Z", "+00:00"))
        search_end = datetime.fromisoformat(time_max_iso.replace("Z", "+00:00"))
        
        available_slots = []
        current_time = search_start
        
        for busy_start, busy_end in merged:
            if busy_end <= current_time:
                continue
            
            if busy_start > current_time:
                # Gap found
                temp_time = current_time
                while temp_time + timedelta(minutes=duration_minutes) <= busy_start:
                    available_slots.append(temp_time.isoformat())
                    temp_time += timedelta(minutes=15)
            
            current_time = max(current_time, busy_end)
            
        # Check final gap
        if current_time < search_end:
            temp_time = current_time
            while temp_time + timedelta(minutes=duration_minutes) <= search_end:
                available_slots.append(temp_time.isoformat())
                temp_time += timedelta(minutes=15)
                
        return available_slots

    except Exception as e:
        raise ToolError(f"Failed to find meeting slots: {e}")
