import json
from upstash_redis import Redis
import os

def get_redis():
    return Redis(url=os.getenv("REDIS_URL"), token=os.getenv("REDIS_TOKEN"))

def load_duty_schedule():
    r = get_redis()
    json_data = r.get("duty_schedule")
    return json.loads(json_data or "{}")
