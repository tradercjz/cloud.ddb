import dolphindb as ddb
from pydantic import Field

from agent.execution_result import ExecutionResult 
from .tool_interface import BaseTool, ToolInput, ensure_generator
from agent.code_executor import CodeExecutor 
 
class RunDolphinDBScriptInput(ToolInput):
    script: str = Field(description="The DolphinDB script to execute.")

class RunDolphinDBScriptTool(BaseTool):
    name = "run_dolphindb_script"
    description = "Executes a given DolphinDB script. Returns the data output on success or an error message on failure."
    args_schema = RunDolphinDBScriptInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor

    @ensure_generator
    def run(self, args: RunDolphinDBScriptInput) -> ExecutionResult:
        return self.executor.run(args.script)