# file: agent/tools/enhanced_ddb_tools.py

import dolphindb as ddb
from pydantic import Field, field_validator
from typing import Generator, List, Dict, Any, Optional
import json
import os

from agent.execution_result import ExecutionResult
from context.context_builder import ContextBuilder
from context.pruner import Document
from llm.llm_prompt import llm
from rag.candidate_selector import LLMCandidateSelector
from rag.rag_status import AnyRagStatus, RagEnd, RagIndexLoaded, RagRerankStart, RagSelectionStart, RagStart
from rag.text_index_manager import TextIndexManager
from rag.types import BaseIndexModel 
from .tool_interface import BaseTool, ToolInput, ensure_generator
from agent.code_executor import CodeExecutor
from services.jina_faiss_service import JinaFaissService

class InspectDatabaseInput(ToolInput):
    """检查数据库连接和基本信息"""
    pass


class InspectDatabaseTool(BaseTool):
    name = "inspect_database"
    description = "Check database connection status and get basic system information like version, memory usage, and available databases."
    args_schema = InspectDatabaseInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    @ensure_generator
    def run(self, args: InspectDatabaseInput) -> ExecutionResult:
        """检查数据库状态"""
        inspection_script = """
        // Database inspection script
        info = dict(STRING, ANY)
        info["version"] = version()
        info["license"] = license()
        info["node_count"] = getClusterPerf().size()
        info["databases"] =  getClusterDFSDatabases()
      
        info
        """
        
        result = self.executor.run(inspection_script)
        return result

class ListTablesInput(ToolInput):
    database_name: Optional[str] = Field(default=None, description="Database name to list tables from. If not provided, lists tables from current session.")
    pattern: Optional[str] = Field(default=None, description="Pattern to filter table names (SQL LIKE pattern)")


class ListTablesTool(BaseTool):
    name = "list_tables"
    description = "List all tables in a database or current session, optionally filtered by pattern."
    args_schema = ListTablesInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    @ensure_generator
    def run(self, args: ListTablesInput) -> ExecutionResult:
        if args.database_name:
            script = f"""
            getTables(database("{args.database_name}"))
            """
        else:
            script = """
            // List tables in current session
            objs = objs(true)
            tables = select name, type, form from objs where type="TABLE"
            tables
            """
        
        result = self.executor.run(script)
        return result


class DescribeTableInput(ToolInput):
    table_name: str = Field(description="Name of the table to describe")
    database_name: Optional[str] = Field(default=None, description="Database name if table is in a specific database")


class DescribeTableTool(BaseTool):
    name = "describe_table"
    description = "Get detailed schema information about a table including column names, types, and sample data."
    args_schema = DescribeTableInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    @ensure_generator
    def run(self, args: DescribeTableInput) -> ExecutionResult:
        if args.database_name:
            table_ref = f'database("{args.database_name}").loadTable("{args.table_name}")'
        else:
            table_ref = args.table_name
        
        script = f"""
        // Describe table structure and sample data
        t = {table_ref}
        
        result = dict(STRING, ANY)
        result["table_name"] = "{args.table_name}"
        result["schema"] = schema(t)
        result["column_count"] = t.columns().size()
        result["row_count"] = t.size()
        
        // Get sample data (first 5 rows)
        try {{
            result["sample_data"] = select top 5 * from t
        }} catch(ex) {{
            result["sample_data"] = "Unable to fetch sample data: " + ex
        }}
        
        result
        """
        
        result = self.executor.run(script)
        return result


class ValidateScriptInput(ToolInput):
    script: str = Field(description="DolphinDB script to validate for syntax errors")


class ValidateScriptTool(BaseTool):
    name = "validate_script"
    description = "Check a DolphinDB script for syntax errors without executing it."
    args_schema = ValidateScriptInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    @ensure_generator
    def run(self, args: ValidateScriptInput) -> ExecutionResult:
        # DolphinDB doesn't have a built-in syntax validator, so we'll try to parse it
        validation_script = f"""
        try {{
            parseExpr(`{args.script.replace('`', '``')})
            "Script syntax is valid"
        }} catch(ex) {{
            "Syntax error: " + ex
        }}
        """
        
        result = self.executor.run(validation_script)
        return result


class QueryDataInput(ToolInput):
    query: str = Field(description="SQL query to execute")
    limit: Optional[int] = Field(default=100, description="Maximum number of rows to return")


class QueryDataTool(BaseTool):
    name = "query_data"
    description = "Execute a SELECT query and return results with optional row limit."
    args_schema = QueryDataInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    @ensure_generator
    def run(self, args: QueryDataInput) -> ExecutionResult:
        # Add limit to query if not already present
        query = args.query.strip()
        # if args.limit and not query.lower().startswith('select top'):
        #     if query.lower().startswith('select'):
        #         query = query.replace('select', f'select top {args.limit}', 1)
        
        result = self.executor.run(query)
        return result


class CreateSampleDataInput(ToolInput):
    data_type: str = Field(description="Type of sample data to create (e.g., 'trades', 'quotes', 'timeseries')")
    row_count: Optional[int] = Field(default=1000, description="Number of rows to generate")
    table_name: Optional[str] = Field(default=None, description="Name for the created table")


class CreateSampleDataTool(BaseTool):
    name = "create_sample_data"
    description = "Create sample data for testing purposes. Supports common financial data types."
    args_schema = CreateSampleDataInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    @ensure_generator
    def run(self, args: CreateSampleDataInput) -> ExecutionResult:
        table_name = args.table_name or f"sample_{args.data_type}"
        
        if args.data_type.lower() == "trades":
            script = f"""
            // Create sample trades data
            n = {args.row_count}
            symbols = `AAPL`MSFT`GOOGL`AMZN`TSLA
            {table_name} = table(
                take(symbols, n) as symbol,
                2023.01.01T09:30:00.000 + rand(6.5*60*60*1000, n) as timestamp,
                20.0 + rand(100.0, n) as price,
                100 + rand(1000, n) as qty,
                rand(`B`S, n) as side
            )
            select count(*) as row_count from {table_name}
            """
        elif args.data_type.lower() == "quotes":
            script = f"""
            // Create sample quotes data
            n = {args.row_count}
            symbols = `AAPL`MSFT`GOOGL`AMZN`TSLA
            {table_name} = table(
                take(symbols, n) as symbol,
                2023.01.01T09:30:00.000 + rand(6.5*60*60*1000, n) as timestamp,
                20.0 + rand(100.0, n) as bid_price,
                20.1 + rand(100.0, n) as ask_price,
                100 + rand(1000, n) as bid_size,
                100 + rand(1000, n) as ask_size
            )
            select count(*) as row_count from {table_name}
            """
        elif args.data_type.lower() == "timeseries":
            script = f"""
            // Create sample time series data
            n = {args.row_count}
            {table_name} = table(
                2023.01.01T00:00:00.000 + (0..(n-1)) * 60000 as timestamp,
                100.0 + cumsum(rand(2.0, n) - 1.0) as value,
                rand(10.0, n) as volume
            )
            select count(*) as row_count from {table_name}
            """
        else:
            return f"Unsupported data type: {args.data_type}. Supported types: trades, quotes, timeseries"
        
        result = self.executor.run(script)
        return result


class OptimizeQueryInput(ToolInput):
    query: str = Field(description="Query to analyze and optimize")


class OptimizeQueryTool(BaseTool):
    name = "optimize_query"
    description = "Analyze a query and suggest optimizations for better performance."
    args_schema = OptimizeQueryInput
    
    def __init__(self, executor: CodeExecutor):
        self.executor = executor
    
    @ensure_generator
    def run(self, args: OptimizeQueryInput) -> ExecutionResult:
        # This is a simplified optimization analyzer
        # In practice, you might want to use DolphinDB's query plan analysis
        
        analysis_script = f"""
        // Basic query analysis
        query_text = `{args.query.replace('`', '``')}`
        
        analysis = dict(STRING, ANY)
        analysis["original_query"] = query_text
        
        // Check for common optimization opportunities
        suggestions = string[]
        
        if(query_text.regexFind("select \\\\* from") != -1)
            suggestions.append!("Consider selecting only needed columns instead of SELECT *")
        
        if(query_text.regexFind("where.*=.*or.*=") != -1)
            suggestions.append!("Consider using IN clause instead of multiple OR conditions")
        
        if(query_text.regexFind("order by") != -1 && query_text.regexFind("limit|top") == -1)
            suggestions.append!("Consider adding LIMIT/TOP clause when using ORDER BY")
        
        analysis["suggestions"] = suggestions
        analysis["query_length"] = query_text.size()
        
        analysis
        """
        
        result = self.executor.run(analysis_script)
        return result
        

class GetFunctionDocumentationInput(ToolInput):
    """Input model for the function documentation tool."""
    function_name: str = Field(description="The name of the DolphinDB function to look up documentation for. Should not be empty.")

    # Pydantic v2 的写法
    @field_validator('function_name')
    @classmethod
    def function_name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('function_name must not be empty')
        return v

class GetFunctionDocumentationTool(BaseTool):
    """
    A tool to retrieve detailed documentation for a specific DolphinDB function.
    """
    name = "get_function_documentation"
    description = (
        "Retrieves the full documentation for a specific DolphinDB function from the knowledge base. "
        "Use this when you are unsure about a function's arguments, behavior, or see an error message "
        "related to a specific function call (e.g., 'wrong number of arguments')."
    )
    args_schema = GetFunctionDocumentationInput

    def __init__(self, project_path: str):
        """
        Initializes the tool.
        
        Args:
            project_path: The root path of the project, used to locate the 'documentation/funcs' folder.
        """
        # 路径现在指向 funcs 子目录
        self.base_doc_path = os.path.join(project_path, "documentation", "funcs")

    @ensure_generator
    def run(self, args: GetFunctionDocumentationInput) -> ExecutionResult:
        """
        Reads and returns the content of a function's documentation file 
        from the structured directory: documentation/funcs/{first_char}/{function_name}.md
        """
        function_name = args.function_name.strip()

        # 1. 获取函数名的首字母
        first_char = function_name[0].lower()
        
        # 2. 检查首字母是否是合法的目录名 (例如，a-z)
        if not 'a' <= first_char <= 'z':
            return f"Error: Invalid function name '{function_name}'. It must start with a letter."

        # 3. 构造完整的文件路径
        #    函数名本身也统一转为小写，以匹配文件名
        doc_file_path = os.path.join(self.base_doc_path, first_char, f"{function_name.lower()}.md")

        # 4. 检查文件是否存在
        if not os.path.exists(doc_file_path):
            return ExecutionResult(
                success=False,
                error_message=f"Documentation for function '{function_name}' not found in '{doc_file_path}'."
            )

        try:
            # 5. 读取文件内容
            with open(doc_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 6. 检查文件内容是否为空
            if not content or not content.strip():
                return (
                    f"Warning: Documentation for function '{function_name}' was found, "
                    "but the file is empty. No details are available."
                )

            return ExecutionResult(
                success=True,
                executed_script=f"Documentation for function '{function_name}' retrieved successfully.",
                data=(
                f"--- Documentation for {function_name} ---\n\n"
                f"{content}\n\n"
                f"--- End of Documentation ---"
            )
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                executed_script=f"Failed to read documentation for function '{function_name}'.",
                error_message=str(e)
            )
        

class SearchKnowledgeBaseInput(ToolInput):
    """Input model for the knowledge base search tool."""
    query: str = Field(description="The specific error message, function name, or concept to search for in the documentation and code snippets.")
    conversation_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The recent conversation history as a list of message objects, to provide context for the search."
    )
class SearchKnowledgeBaseTool(BaseTool):
    """
    A tool to search the project's knowledge base (RAG system) for relevant information.
    Use this tool when you encounter an error, are unsure about a function's usage,
    or need more context to solve a problem. It provides context from documentation and code examples.
    """
    name = "search_knowledge_base"
    description = (
        "Searches the knowledge base for documentation and code examples related to a query. "
        "This is the primary tool for debugging and self-correction."
    )
    args_schema = SearchKnowledgeBaseInput

    def __init__(self, jina_service: JinaFaissService):
        self.project_path = "/home/jzchen/ddb_agent"
        self.index_file = "/home/jzchen/ddb_agent/.ddb_agent/file_index.json"
        self.index_manager = TextIndexManager("/home/jzchen/ddb_agent", self.index_file)
        self.context_builder = ContextBuilder(model_name=os.getenv("LLM_MODEL"), max_window_size=128000)
        self.jina_faiss_service = jina_service

        @llm.prompt()
        def _default_chat_prompt(conversation_history: List[Dict[str, str]]):
            """"
            You are a helpful DolphinDB assistant. Continue the conversation naturally.
            The user's latest message is the last one in the history.
            请严格按照相关资料来回答用户问题，如果没有搜到相关资料，请回答我不清楚,千万不要臆造"
            """
        
        self.chat_prompt_func = _default_chat_prompt

        pass
    
    @llm.prompt()
    def _rag_final_answer_prompt(self, user_query: str, context_files_str: str) -> dict:
        """
        You are an expert DolphinDB research assistant. Your primary goal is to answer the user's query based *exclusively* on the provided context documents.

        **Context Documents:**
        I have retrieved the following documents that might be relevant to the user's query. Each document's content is provided.

        <CONTEXT>
        {{ context_files_str }}
        </CONTEXT>

        **User's Query:**
        "{{ user_query }}"

        **Your Task:**
        1.  Carefully read the user's query and the content of the provided context documents.
        2.  Formulate a comprehensive and direct answer to the user's query.
        3.  After your answer, you MUST include a "References" section.
        4.  In the "References" section, for each document you used to formulate your answer, you MUST list its file path and include a direct quote of the most relevant passage using Markdown blockquote syntax.

        **CRITICAL: If the provided context does not contain enough information to answer the query, you must state that clearly, for example: "The provided documentation does not contain specific information about this topic." Do not invent answers.**

        **MANDATORY OUTPUT FORMAT:**

        [Your comprehensive answer to the user's query goes here.]

        ---
        **References:**
        *   **`path/to/relevant_file1.md`**:
            > [A direct and relevant quote from the file content goes here.]
        *   **`path/to/relevant_file2.dos`**:
            > [Another direct and relevant quote from the file content.]
        """
        # The llm decorator will handle filling the template from these returned variables.
        return {
            "user_query": user_query,
            "context_files_str": context_files_str
        }


    def _get_files_content(self, file_paths: List[str]) -> List[Document]:
        """Reads file contents and creates Document objects."""
        sources = []
        for file_path in file_paths:
            full_path = os.path.join(self.project_path, file_path)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 从索引中获取预先计算好的token数
                index_info = self.index_manager.get_index_by_filepath(file_path)
                tokens = index_info.tokens if index_info else -1 # 如果找不到索引，则让Document自己计算
                sources.append(Document(file_path, content, tokens))
            except Exception as e:
                print(f"Warning: Could not read file {file_path}: {e}")
        return sources

    def retrieve(self, query: str, top_k: int = 5) -> Generator[AnyRagStatus, None, List[Document]]:
        """
        Retrieves the most relevant documents using a two-step process.
        """
        yield RagStart(message="🚀 Starting retrieval process...")
        
        # 1. 从所有索引源获取全部索引数据
        all_text_indices = self.index_manager.get_all_indices()
        all_indices = all_text_indices

        if not all_indices:
            print("No indices found to search from.")
            return []

        yield RagIndexLoaded(message=f"🔍 Found {len(all_indices)} total index items.", total_items=len(all_indices))
        yield RagSelectionStart(
            message=f"Phase 1: Selecting candidates using llm strategy...",
            strategy="llm"
        )
        
        # 2. 阶段一：粗筛 (Candidate Selection)
        candidates: List[BaseIndexModel]
        
        selector = LLMCandidateSelector(all_indices, self.index_manager)
        candidates = yield from selector.select(query, max_workers=10) # 并发LLM筛选
        

        if not candidates:
            print("No relevant candidates found after initial selection.")
            return []
        
        yield RagRerankStart(
            message="Phase 2: Using LLM to re-rank candidates...",
            candidate_count=len(candidates)
        )

        # 我们直接从已排序的候选中选取前 top_k 个
        final_candidates = candidates[:top_k]
        final_identifiers = [c.file_path for c in final_candidates]
        
        yield RagEnd(
            message=f"Retrieval process completed. Selected top {len(final_identifiers)} documents.",
            final_document_count=len(final_identifiers)
        )

        # 4. 根据最终的标识符列表，获取并返回文件/文本块内容
        return self._get_files_content(final_identifiers)

    @ensure_generator
    def run(self, args: SearchKnowledgeBaseInput) -> Generator[Any, None, ExecutionResult]:
        """
        Executes the RAG retrieval process.
        """
        try:
            # DDBRAG.retrieve 是一个生成器，我们需要消耗它来获取最终结果
            #relevant_files = yield from  self.retrieve(args.query, top_k=3)
            
            relevant_files = self.jina_faiss_service.retrieve(args.query, top_k=7)

            
            print("Relevant files:", relevant_files)
            
            file_context_str = "\n---\n".join(
                f"File: {f.file_path}\n\n{f.source_code}" for f in relevant_files
            )
            
            print("File context string:", file_context_str)
            return ExecutionResult(
                success=True,
                data=f"Found {len(relevant_files)} relevant documents:\n\n{file_context_str}"
            )

            # 2. 上下文构建
            system_prompt = "You are a helpful assistant. Your task is to answer the user's question strictly based on the information found in the provided official DolphinDB documentation links. If you cannot find a direct answer in the provided links, you must state that you cannot find a built-in function for this purpose based on the documentation. Do not use any prior knowledge."

            final_messages = self.context_builder.build(
                system_prompt=system_prompt,
                conversations=args.conversation_history,
                file_sources=relevant_files,
                task_type='chat',
                file_pruning_strategy='extract'
            )

            # 3. 调用 LLM 并流式传输结果 (yields StreamChunk)
            assistant_response_gen = self.chat_prompt_func(
                conversation_history=final_messages
            )

            final_llm_response = None
            try:
                while True:
                    chunk = next(assistant_response_gen)
                    yield chunk # 将 StreamChunk 直接冒泡给调用者
            except StopIteration as e:
                final_llm_response = e.value

            print(final_llm_response)

            # 4. 任务结束，yield 最终消息对象
            if final_llm_response and getattr(final_llm_response, 'success', False):
                final_message_obj = {
                    "role": "assistant",
                    "content": final_llm_response.content
                }

                return ExecutionResult(
                    success=True,
                    data=f"Found the following relevant information:\n\n{str(final_message_obj)}"
                )
            elif final_llm_response: # 如果失败
                print("failed:", final_llm_response)
                return ExecutionResult(
                    success=False,
                    error_message=f"Failed to search knowledge base: {getattr(final_llm_response, 'error_message', 'Unknown error')}"
                )
                
        except Exception as e:

            return ExecutionResult(
                success=False,
                error_message=f"Failed to search knowledge base: {str(e)}"
            )