
import unittest
from datetime import datetime, timedelta, timezone

# We will need to refactor logic out or import it. 
# For now, let's implement the logic in a standalone function in the test 
# to verify it, then move it to the server, or mock the server function.
# Better: Let's assume we will add a helper function `_find_slots` in the server
# that we can test directly if we import it, or just copy-paste for the test 
# if importing is hard (dependency issues). 
# But importing is best.

def find_available_slots(
    busy_intervals: list[tuple[datetime, datetime]],
    time_min: datetime,
    time_max: datetime,
    duration_minutes: int
) -> list[datetime]:
    """
    Logic to be implemented in the MCP server.
    """
    # Sort by start time
    busy_intervals.sort(key=lambda x: x[0])
    
    # Merge overlapping intervals
    merged = []
    if busy_intervals:
        curr_start, curr_end = busy_intervals[0]
        for next_start, next_end in busy_intervals[1:]:
            if next_start < curr_end:
                # Overlap, extend end max
                curr_end = max(curr_end, next_end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged.append((curr_start, curr_end))
    
    available_slots = []
    current_time = time_min
    
    # Check gaps
    for busy_start, busy_end in merged:
        # If busy interval ends before we start looking, skip it
        if busy_end <= current_time:
            continue
        
        # If busy interval starts after current time, check gap
        if busy_start > current_time:
            gap_duration = (busy_start - current_time).total_seconds() / 60
            # We can fit multiple slots in one gap? 
            # Requirement says "find the correct slot". Usually means list possible start times.
            # Let's say we list every 15 mins or just the start of the gap?
            # Let's list the *start* of available chunks for now, or maybe 30 min increments?
            # A simple greedy approach: if gap >= duration, add start time, then looking for next?
            # Use step of 15 mins.
            
            temp_time = current_time
            while temp_time + timedelta(minutes=duration_minutes) <= busy_start:
                available_slots.append(temp_time)
                # Increment by 30 mins or duration? Let's use 15 min steps for granular slots
                temp_time += timedelta(minutes=15)
                
        # Move current_time past this busy block
        current_time = max(current_time, busy_end)
        
    # Check final gap
    if current_time < time_max:
        temp_time = current_time
        while temp_time + timedelta(minutes=duration_minutes) <= time_max:
                available_slots.append(temp_time)
                temp_time += timedelta(minutes=15)
                
    return available_slots

class TestMeetingLogic(unittest.TestCase):
    def test_no_busy(self):
        start = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
        slots = find_available_slots([], start, end, 30)
        # Should find 9:00, 9:15, 9:30. 9:45 is too late for 30 min slot (ends 10:15 > 10:00)
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0], start)
        self.assertEqual(slots[2], start + timedelta(minutes=30))

    def test_busy_blocking(self):
        start = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        # Busy 9:30 - 10:30
        busy = [(start + timedelta(minutes=30), start + timedelta(minutes=90))]
        
        slots = find_available_slots(busy, start, end, 30)
        
        # Expect:
        # 9:00 (ends 9:30) - OK
        # 9:15 (ends 9:45) - Conflict with 9:30
        # ...
        # 10:30 (ends 11:00) - OK
        
        self.assertIn(start, slots)
        self.assertNotIn(start + timedelta(minutes=15), slots)
        self.assertIn(start + timedelta(minutes=90), slots) # 10:30

    def test_overlap_merge(self):
        start = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        # Busy 9:00-9:30, 9:15-10:00 -> Merged 9:00-10:00
        busy = [
            (start, start + timedelta(minutes=30)),
            (start + timedelta(minutes=15), start + timedelta(minutes=60))
        ]
        slots = find_available_slots(busy, start, end, 60)
        # Gap starts at 10:00 (start+60)
        self.assertEqual(slots[0], start + timedelta(minutes=60))

if __name__ == '__main__':
    unittest.main()
