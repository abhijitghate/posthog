from celery import shared_task
from posthog.models import Action
from posthog.celery import app
import logging
import time


logger = logging.getLogger(__name__)


@shared_task
def calculate_action(action_id: int) -> None:
    start_time = time.time()
    action = Action.objects.get(pk=action_id)
    action.calculate_events()
    logger.info("Calculating action {} took {:.2f} seconds".format(action.pk, (time.time() - start_time)))


def calculate_actions_from_last_calculation() -> None:
    actions = Action.objects.filter(deleted=False).only("pk")
    for action in actions:
        start_time = time.time()
        action.calculate_events_for_period(start=action.last_calculated_at)
        logger.info("Calculating action {} took {:.2f} seconds".format(action.pk, (time.time() - start_time)))
