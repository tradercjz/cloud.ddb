from pydantic import BaseModel, Field
from typing import Optional, Literal, Union, List, Dict, Any
from typing import Annotated

# --- 基类 ---
class BaseTaskStatus(BaseModel):
    """所有任务状态更新的基类。"""
    type: Literal["task_status"] = "task_status"
    message: str = Field(description="向用户展示的友好信息。")

# --- 通用状态子类 ---

class TaskStart(BaseTaskStatus):
    """表示任务开始。"""
    subtype: Literal["start"] = "start"
    task_description: str

class TaskEnd(BaseTaskStatus):
    """表示任务结束。"""
    subtype: Literal["end"] = "end"
    success: bool
    final_message: str
    final_script: Optional[str] = Field(default=None, description="如果任务生成了脚本，则包含该脚本。")

class TaskError(BaseTaskStatus):
    """表示任务中发生严重错误。"""
    subtype: Literal["error"] = "error"
    error_details: str



class PlanGenerationStart(BaseTaskStatus):
    """表示开始生成执行计划。"""
    subtype: Literal["plan_gen_start"] = "plan_gen_start"
    reason: str = Field(description="生成计划的原因（如 'initial', 'debug_fix'）。")

class PlanGenerationEnd(BaseTaskStatus):
    """表示计划生成结束。"""
    subtype: Literal["plan_gen_end"] = "plan_gen_end"
    plan: List[Dict[str, Any]] = Field(description="生成的计划步骤列表。")

class StepExecutionStart(BaseTaskStatus):
    """表示开始执行计划中的一个步骤。"""
    subtype: Literal["step_exec_start"] = "step_exec_start"
    step_index: int
    total_steps: int
    step_info: Dict[str, Any]

class StepExecutionEnd(BaseTaskStatus):
    """表示一个步骤执行结束。"""
    subtype: Literal["step_exec_end"] = "step_exec_end"
    step_index: int
    observation: str
    is_success: bool
    script: Optional[str] = Field(default=None, description="如果步骤执行生成了脚本，则包含该脚本。")

class ReactThought(BaseTaskStatus):
    """Represents the agent's thought process for a step."""
    subtype: Literal["react_thought"] = "react_thought"
    thought: str

class ReactAction(BaseTaskStatus):
    """Represents the agent's chosen action (tool call)."""
    subtype: Literal["react_action"] = "react_action"
    tool_name: str
    tool_args: Dict[str, Any]

class ReactObservation(BaseTaskStatus):
    """Represents the result of an action (observation)."""
    subtype: Literal["react_observation"] = "react_observation"
    observation: str
    is_error: bool



AnyTaskStatus = Annotated[
    Union[
        TaskStart,
        TaskEnd,
        TaskError,
        PlanGenerationStart,
        PlanGenerationEnd,
        StepExecutionStart,
        StepExecutionEnd,
        ReactThought,
        ReactAction,
        ReactObservation,
    ],
    Field(discriminator="subtype"),
]