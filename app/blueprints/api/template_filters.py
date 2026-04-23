"""
API routes - all /api/* endpoints
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app

from . import bp


@bp.app_template_filter('to_est')
def to_est_filter(dt_string):
    """Convert UTC datetime string to Eastern Time (EST/EDT)"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD)
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return dt_string  # Return date-only as-is

            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))

        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))

        # Format as YYYY-MM-DD HH:MM:SS
        return est_dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        current_app.logger.error(f"Error converting datetime to EST: {e}")
        return dt_string if isinstance(dt_string, str) else 'N/A'

@bp.app_template_filter('to_est_time')
def to_est_time_filter(dt_string):
    """Convert UTC datetime string to Eastern Time, showing only time portion"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD) - return N/A for time-only display
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return 'N/A'  # No time component for date-only strings

            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))

        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))

        # Format as HH:MM:SS
        return est_dt.strftime('%H:%M:%S')
    except Exception as e:
        current_app.logger.error(f"Error converting datetime to EST: {e}")
        if isinstance(dt_string, str):
            # Fallback: try to extract time portion
            parts = dt_string.split(' ')
            if len(parts) > 1:
                return parts[1].split('.')[0] if '.' in parts[1] else parts[1]
        return 'N/A'
