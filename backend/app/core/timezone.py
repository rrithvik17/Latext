from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_and_convert_timezone(local_dt: datetime, tz_name: str) -> datetime:
    """
    Validates that local_dt is a valid, non-ambiguous datetime in the timezone tz_name.
    Returns the corresponding UTC datetime (timezone-aware).
    Raises ValueError if invalid or ambiguous.
    """
    # Ensure local_dt is naive for interpretation in the selected timezone
    if local_dt.tzinfo is not None:
        local_dt = local_dt.replace(tzinfo=None)

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise ValueError(f"Invalid timezone: '{tz_name}'")
    except Exception:
        raise ValueError(f"Invalid timezone: '{tz_name}'")

    # Localize with fold=0 and fold=1 to test for DST transitions
    dt_fold0 = local_dt.replace(tzinfo=tz, fold=0)
    dt_fold1 = local_dt.replace(tzinfo=tz, fold=1)

    utc0 = dt_fold0.astimezone(ZoneInfo("UTC"))
    utc1 = dt_fold1.astimezone(ZoneInfo("UTC"))

    # Convert back to local timezone to check validity
    back_local0 = utc0.astimezone(tz)
    back_local1 = utc1.astimezone(tz)

    is_valid0 = back_local0.replace(tzinfo=None) == local_dt
    is_valid1 = back_local1.replace(tzinfo=None) == local_dt

    # If it is not valid in either fold configuration, the time fell in a DST gap (skipped time)
    if not is_valid0 or not is_valid1:
        raise ValueError(
            "The selected local time does not exist because it falls in a daylight saving time (DST) gap "
            "(spring forward gap). Please select a different time."
        )

    # If both folds are valid but lead to different UTC instants, the time is ambiguous (fold overlap)
    if utc0 != utc1:
        raise ValueError(
            "The selected local time is ambiguous because of a daylight saving time (DST) shift "
            "(autumn fallback overlap). Please select a different time."
        )

    return utc0
