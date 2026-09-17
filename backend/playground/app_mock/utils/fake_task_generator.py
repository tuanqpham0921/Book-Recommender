from app.domains.node_types import UnknownNodeTypeEnum
from pydantic import Field
from app.domains.base_request import BaseRequest
import random

class FakeTask(BaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN
    description: str = Field(default="Fake task", description="Description of the fake task")

def get_random_dependes_on(execution_order: list[str]) -> list[str]:
    num_list = random.randint(1, len(execution_order))
    return random.sample(execution_order, num_list)

def generate_fake_tasks(accepted: list[BaseRequest], execution_order: list[str]) -> list[FakeTask]:
    for i in range(10):
        fake_task = FakeTask(
            depends_on=get_random_dependes_on(execution_order),
            target_goal = ["goal_1"],
            id = f"task_{i}",
            description = f"Fake task {i}",
            reasoning = f"Fake task {i}",
            confidence = 1.0
        )
        execution_order.append(fake_task.id)
        accepted.append(fake_task)
    return accepted, execution_order
        