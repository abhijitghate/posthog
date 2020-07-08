import os
from celery import Celery, group
from celery.schedules import crontab
from django.conf import settings
from django.db import connection
import redis
import time
from typing import Optional
from datetime import datetime
from dateutil import parser

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

app = Celery("posthog")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Make sure Redis doesn't add too many connections
# https://stackoverflow.com/questions/47106592/redis-connections-not-being-released-after-celery-task-is-complete
app.conf.broker_pool_limit = 0

# Connect to our Redis instance to store the heartbeat
redis_instance = redis.from_url(settings.REDIS_URL, db=0)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Heartbeat every 10sec to make sure the worker is alive
    sender.add_periodic_task(10.0, redis_heartbeat.s(), name="10 sec heartbeat", priority=0)
    sender.add_periodic_task(
        crontab(day_of_week="mon,fri"), update_event_partitions.s(),  # check twice a week
    )
    sender.add_periodic_task(15 * 60, calculate_cohort.s(), name="debug")
    sender.add_periodic_task(600, check_cached_items.s(), name="check dashboard items")


@app.task
def redis_heartbeat():
    redis_instance.set("POSTHOG_HEARTBEAT", int(time.time()))


@app.task
def update_event_partitions():
    with connection.cursor() as cursor:
        cursor.execute(
            "DO $$ BEGIN IF (SELECT exists(select * from pg_proc where proname = 'update_partitions')) THEN PERFORM update_partitions(); END IF; END $$"
        )


@app.task
def calculate_cohort():
    from posthog.tasks.calculate_cohort import calculate_cohorts

    calculate_cohorts()


@app.task
def check_cached_items():
    from posthog.tasks.update_cache import update_cached_items

    update_cached_items()


@app.task
def update_cache_item_task(key: str, cache_type: str, payload: dict) -> None:
    from posthog.tasks.update_cache import update_cache_item

    update_cache_item(key, cache_type, payload)


@app.task(bind=True)
def debug_task(self):
    print("Request: {0!r}".format(self.request))
