from typing import Any, Dict, Generator, Optional, List
from agent.execution_result import ExecutionResult
from agent.tools.tool_interface import BaseTool

class ToolNotFoundError(Exception):
    pass

class ToolArgumentValidationError(Exception):
    pass

class ToolManager:
    """增强的工具管理器"""
    
    def __init__(self, tools: list[BaseTool]):
        self.tools = {tool.name: tool for tool in tools}
       

    def get_tool_definitions(self, mode: str = "ACT") -> list[dict]:
        """
        根据模式返回不同的工具定义列表。
        PLAN 模式下，只暴露 'plan_mode_response'。
        """
        all_tools = list(self.tools.values())

        if mode == 'PLAN': 
            return [tool.get_definition() for tool in all_tools ]
        else: # ACT mode
            # 在ACT模式下，暴露所有实际操作的工具
            base_tools = [tool.get_definition() for tool in all_tools if tool.name != 'plan_mode_response']
            return base_tools

    def call_tool(self, tool_name: str, args: dict) ->  Generator[Any, None, ExecutionResult]:
        # 调用常规工具
        if tool_name not in self.tools:
            raise ToolNotFoundError(f"Tool '{tool_name}' not found.")
    
        tool = self.tools[tool_name]
        try:
            # Pydantic v2 用 model_validate
            validated_args = tool.args_schema.model_validate(args)
            z = yield from  tool.run(validated_args)
            return z
        except Exception as e:
            raise ToolArgumentValidationError(f"Error validating arguments for tool '{tool_name}': {e}") from e
     
    def get_all_tool_names(self) -> List[str]:
        """获取所有可用工具名称"""
        tool_names = list(self.tools.keys())
        
        if self.enable_mcp and self.mcp_tool_adapter:
            try:
                mcp_tools = self.mcp_tool_adapter.get_available_tools()
                for tool in mcp_tools:
                    tool_names.append(tool["name"].replace(".", "_"))
            except Exception:
                pass
        
        return tool_names
    
    def get_tool_help(self, tool_name: str) -> Optional[str]:
        """获取工具帮助信息"""
        # 检查常规工具
        if tool_name in self.tools:
            tool = self.tools[tool_name]
            return f"**{tool.name}**\n\n{tool.description}"
        
        # 检查MCP工具
        if self.enable_mcp and self.mcp_tool_adapter:
            try:
                mcp_tool_name = tool_name.replace("_", ".")
                return self.mcp_tool_adapter.get_tool_help(mcp_tool_name)
            except Exception:
                pass
        
        return None
    
    async def cleanup(self):
        """清理资源"""
        if self.enable_mcp and self.mcp_server_manager:
            try:
                await self.mcp_server_manager.stop_all_servers()
            except Exception as e:
                print(f"Warning: Failed to stop MCP servers during cleanup: {e}")