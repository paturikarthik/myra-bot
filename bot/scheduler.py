from datetime import datetime, timedelta
import pytz

# Singapore timezone
SGT = pytz.timezone('Asia/Singapore')

# You can update this list anytime
SCHOOL_HOLIDAYS = [
    ("2025-01-01", "2025-08-03"),  # Until 3 August 2025
    ("2025-12-07", "2026-01-11"),  # 7 December 2025 - 11 January 2026
    ("2026-05-10", "2026-08-02"),  # 10 May 2026 - 2 August 2026
]

def get_singapore_time():
    """Get current time in Singapore timezone"""
    return datetime.now(SGT)

def is_school_holiday(date: datetime = None) -> bool:
    """Check if the given date is during school holidays"""
    if date is None:
        date = get_singapore_time()
    
    date_str = date.strftime("%Y-%m-%d")
    
    for start, end in SCHOOL_HOLIDAYS:
        if start <= date_str <= end:
            return True
    return False

def is_friday_saturday_sunday(date: datetime = None) -> bool:
    """Check if the given date is Friday, Saturday, or Sunday"""
    if date is None:
        date = get_singapore_time()
    return date.weekday() in [4, 5, 6]  # 4=Friday, 5=Saturday, 6=Sunday

def is_tomorrow_public_holiday(duty_schedule: dict) -> bool:
    """Check if tomorrow is a public holiday based on duty schedule"""
    tomorrow = get_singapore_time() + timedelta(days=1)
    
    possible_formats = [
        tomorrow.strftime("%b %d"),        # "Jul 09"
        tomorrow.strftime("%b %e").strip(),# "Jul  9"
        tomorrow.strftime("%d %b"),        # "09 Jul"
        tomorrow.strftime("%b %d (%a)"),   # "Jul 09 (Wed)"
        tomorrow.strftime("%-d %b") if hasattr(tomorrow, 'strftime') else "",  # platform-safe
    ]
    
    for slot, name in duty_schedule.items():
        slot_upper = slot.upper()
        if "PH" in slot_upper:
            for fmt in possible_formats:
                if fmt in slot or fmt in slot_upper:
                    return True
    return False

def should_trigger_refresh(duty_schedule: dict) -> bool:
    """Check if refresh should be triggered (3 PM on specific days)"""
    now = get_singapore_time()
    
    if now.hour != 15 or now.minute != 0:
        return False
    
    return (
        is_friday_saturday_sunday(now) or
        is_school_holiday(now) or
        is_tomorrow_public_holiday(duty_schedule)
    )

def should_send_reminder() -> bool:
    """Check if reminder should be sent (9 PM)"""
    now = get_singapore_time()
    
    return now.hour == 21 and now.minute == 0

def get_tomorrow_key() -> str:
    """Return the duty schedule key for tomorrow (e.g. 'Jul 24 (Thu) PM')"""
    tomorrow = get_singapore_time() + timedelta(days=1)
    return tomorrow.strftime("%b %d (%a) PM")

def debug_schedule_flags(duty_schedule: dict):
    """Print debug info about why refresh/reminder might be triggered"""
    now = get_singapore_time()
    print("Current Time:", now.strftime("%Y-%m-%d %H:%M:%S"))
    print("Is School Holiday:", is_school_holiday(now))
    print("Is F/S/S:", is_friday_saturday_sunday(now))
    print("Is Tomorrow PH:", is_tomorrow_public_holiday(duty_schedule))
    print("Should Trigger Refresh:", should_trigger_refresh(duty_schedule))
    print("Should Send Reminder:", should_send_reminder())
