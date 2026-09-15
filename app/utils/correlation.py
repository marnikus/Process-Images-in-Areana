import random
import string
from datetime import datetime

def generate_correlation_id(dt: datetime | None = None) -> str:
    """Generate unique correlation ID like 20260915-142530-A7F3"""
    if dt is None:
        dt = datetime.now()
    date_part = dt.strftime("%Y%m%d-%H%M%S")
    rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{date_part}-{rand_part}"

def build_final_prompt(correlation_id: str, user_prompt: str) -> str:
    """Build final prompt with JOB-ID header."""
    return f"[JOB-ID: {correlation_id}]\n{user_prompt}"

def extract_job_id_from_prompt(prompt: str) -> str | None:
    """Extract JOB-ID from prompt if present."""
    import re
    m = re.search(r"\[JOB-ID:\s*([^\]]+)\]", prompt)
    if m:
        return m.group(1).strip()
    return None
