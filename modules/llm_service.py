"""
LLM Service Module
Handles integration with LLM API for natural language processing
Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

import os
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from modules.error_handler import (
    LLMAPIError, TimeoutError, handle_llm_errors,
    log_error_with_context, ErrorRecoveryStrategy
)
from modules.serverless_optimizer import optimize_cold_start

# Lazy import of LLM libraries to reduce cold start time
_openai = None
_genai = None

def _get_openai():
    """Lazy load openai module"""
    global _openai
    if _openai is None:
        import openai as openai_module
        _openai = openai_module
    return _openai

def _get_genai():
    """Lazy load google.generativeai module"""
    global _genai
    if _genai is None:
        import google.generativeai as genai_module
        _genai = genai_module
    return _genai

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """Configuration for LLM service"""
    api_key: str
    model: str
    provider: str = "openai"  # "openai", "gemini", or "watsonx"
    api_base_url: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.7
    timeout: int = 30
    max_retries: int = 3
    # watsonx-specific (ignored by other providers)
    watsonx_project_id: Optional[str] = None


@dataclass
class ToolCallRequest:
    """Represents a tool call request from the LLM"""
    id: str
    tool_name: str
    parameters: Dict[str, Any]


class LLMService:
    """
    Service for interacting with LLM API
    Handles message formatting, tool calling, and response parsing
    """
    
    @optimize_cold_start
    def __init__(self, config: LLMConfig):
        """
        Initialize LLM service with lazy loading optimization
        
        Args:
            config: LLM configuration
            
        Requirements: 2.4
        """
        self.config = config
        self.client = None
        self._watsonx = None

        if config.provider == "gemini":
            # Initialize Gemini
            genai = _get_genai()
            genai.configure(api_key=config.api_key)
            self.client = genai.GenerativeModel(config.model)
            logger.info(f"LLMService initialized with Gemini model: {config.model}")
        elif config.provider == "watsonx":
            # Initialize watsonx adapter (fail-soft: log but do not crash)
            try:
                from modules.watsonx_provider import WatsonxProvider
                self._watsonx = WatsonxProvider(
                    api_key=config.api_key,
                    project_id=config.watsonx_project_id or "",
                    model_id=config.model,
                    base_url=config.api_base_url or "https://us-south.ml.cloud.ibm.com",
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                    timeout=config.timeout,
                )
                logger.info(f"LLMService initialized with watsonx model: {config.model}")
            except Exception as exc:
                logger.error(f"watsonx provider init failed: {exc}")
                # _watsonx stays None; send_message will surface a clear error
        else:
            # Initialize OpenAI
            openai = _get_openai()
            self.client = openai.OpenAI(
                api_key=config.api_key,
                base_url=config.api_base_url,
                timeout=config.timeout
            )
            logger.info(f"LLMService initialized with OpenAI model: {config.model}")
        logger.info(f"LLMService initialized with model: {config.model}")
    
    def format_messages(
        self,
        conversation_history: List[Dict[str, str]],
        system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Format conversation history for LLM API
        
        Args:
            conversation_history: List of message dictionaries with 'role' and 'content'
            system_prompt: Optional system prompt to prepend
            
        Returns:
            Formatted messages list
        """
        messages = []
        
        # Add system prompt if provided
        if system_prompt:
            messages.append({
                'role': 'system',
                'content': system_prompt
            })
        
        # Add conversation history
        for msg in conversation_history:
            messages.append({
                'role': msg['role'],
                'content': msg['content']
            })
        
        return messages
    
    def format_tools_for_llm(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format MCP tools for LLM function calling
        
        Args:
            tools: List of tool definitions from MCP client
            
        Returns:
            List of tools in OpenAI function calling format
        """
        formatted_tools = []
        
        for tool in tools:
            formatted_tool = {
                'type': 'function',
                'function': {
                    'name': tool['name'],
                    'description': tool.get('description', ''),
                    'parameters': tool.get('parameters', {
                        'type': 'object',
                        'properties': {},
                        'required': []
                    })
                }
            }
            formatted_tools.append(formatted_tool)
        
        logger.debug(f"Formatted {len(formatted_tools)} tools for LLM")
        return formatted_tools

    def send_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = 'auto'
    ) -> Dict[str, Any]:
        """
        Send message to LLM with optional tools and comprehensive error handling
        
        Args:
            messages: Formatted messages list
            tools: Optional list of available tools
            tool_choice: Tool choice strategy ('auto', 'none', or specific tool)
            
        Returns:
            LLM response dictionary
            
        Raises:
            LLMAPIError: On API failure after retries
            TimeoutError: On timeout
        """
        if self.config.provider == "gemini":
            return self._send_message_gemini(messages, tools)
        elif self.config.provider == "watsonx":
            return self._send_message_watsonx(messages, tools, tool_choice)
        else:
            return self._send_message_openai(messages, tools, tool_choice)
    
    def _send_message_gemini(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Send message using Gemini API"""
        try:
            # Build conversation context from all messages
            conversation_parts = []
            for msg in messages:
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                
                if role == 'system':
                    # Prepend system message as context
                    conversation_parts.insert(0, f"Instructions: {content}\n\n")
                elif role == 'user':
                    conversation_parts.append(f"User: {content}")
                elif role == 'assistant':
                    conversation_parts.append(f"Assistant: {content}")
            
            # Combine into single prompt
            full_prompt = "\n\n".join(conversation_parts)
            
            # Generate response
            response = self.client.generate_content(full_prompt)
            
            # Convert to standard format
            return {
                'content': response.text,
                'role': 'assistant',
                'tool_calls': []
            }
        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}")
            raise LLMAPIError(
                f"Gemini error: {str(e)}",
                model=self.config.model,
                details={}
            )
    
    def _send_message_watsonx(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = 'auto'
    ) -> Dict[str, Any]:
        """Send message using watsonx.ai native text/chat endpoint."""
        if self._watsonx is None:
            raise LLMAPIError(
                "watsonx provider is not initialised (check WATSONX_* env vars and startup logs)",
                model=self.config.model,
                details={}
            )
        try:
            return self._watsonx.send_message(messages, tools, tool_choice)
        except Exception as exc:
            raise LLMAPIError(
                f"watsonx error: {exc}",
                model=self.config.model,
                details={}
            ) from exc

    def _send_message_openai(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = 'auto'
    ) -> Dict[str, Any]:
        """Send message using OpenAI API with retries"""
        # Prepare API call parameters
        api_params = {
            'model': self.config.model,
            'messages': messages,
            'max_tokens': self.config.max_tokens,
            'temperature': self.config.temperature
        }
        
        # Add tools if provided
        if tools:
            api_params['tools'] = tools
            api_params['tool_choice'] = tool_choice
        
        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                logger.debug(f"Sending message to LLM (attempt {attempt + 1}/{self.config.max_retries})")
                
                response = self.client.chat.completions.create(**api_params)
                
                logger.info(f"LLM response received successfully")
                return self._response_to_dict(response)
                
            except _get_openai().RateLimitError as e:
                last_error = e
                logger.warning(f"Rate limit error (attempt {attempt + 1}/{self.config.max_retries}): {str(e)}")
                
                # Exponential backoff for rate limits
                if attempt < self.config.max_retries - 1:
                    backoff_time = (2 ** attempt) * 2  # 2s, 4s, 8s
                    logger.debug(f"Waiting {backoff_time}s before retry")
                    time.sleep(backoff_time)
                else:
                    raise LLMAPIError(
                        "Rate limit exceeded after retries",
                        model=self.config.model,
                        details={"retries": self.config.max_retries}
                    )
                    
            except _get_openai().APITimeoutError as e:
                last_error = e
                logger.warning(f"API timeout (attempt {attempt + 1}/{self.config.max_retries}): {str(e)}")
                
                if attempt < self.config.max_retries - 1:
                    backoff_time = 2 ** attempt
                    time.sleep(backoff_time)
                else:
                    raise TimeoutError(
                        "llm_api_call",
                        self.config.timeout,
                        {"model": self.config.model, "retries": self.config.max_retries}
                    )
                    
            except _get_openai().APIError as e:
                last_error = e
                logger.error(f"API error (attempt {attempt + 1}/{self.config.max_retries}): {str(e)}")
                
                # Don't retry on client errors (4xx)
                if hasattr(e, 'status_code') and 400 <= e.status_code < 500:
                    raise LLMAPIError(
                        f"Client error: {str(e)}",
                        model=self.config.model,
                        details={"status_code": e.status_code}
                    )
                
                if attempt < self.config.max_retries - 1:
                    backoff_time = 2 ** attempt
                    time.sleep(backoff_time)
                    
            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error (attempt {attempt + 1}/{self.config.max_retries}): {str(e)}")
                
                if attempt < self.config.max_retries - 1:
                    backoff_time = 2 ** attempt
                    time.sleep(backoff_time)
        
        # All retries failed
        error_msg = f"LLM API call failed after {self.config.max_retries} attempts"
        log_error_with_context(
            last_error,
            {
                "model": self.config.model,
                "retries": self.config.max_retries,
                "message_count": len(messages),
                "tools_count": len(tools) if tools else 0
            }
        )
        raise LLMAPIError(error_msg, model=self.config.model, details={"last_error": str(last_error)})
    
    def _response_to_dict(self, response) -> Dict[str, Any]:
        """
        Convert OpenAI response object to dictionary
        
        Args:
            response: OpenAI API response object
            
        Returns:
            Dictionary representation of response
        """
        choice = response.choices[0]
        message = choice.message
        
        result = {
            'content': message.content,
            'role': message.role,
            'finish_reason': choice.finish_reason,
            'tool_calls': []
        }
        
        # Extract tool calls if present
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tool_call in message.tool_calls:
                result['tool_calls'].append({
                    'id': tool_call.id,
                    'type': tool_call.type,
                    'function': {
                        'name': tool_call.function.name,
                        'arguments': tool_call.function.arguments
                    }
                })
        
        return result
    
    def parse_response(self, response: Dict[str, Any]) -> Tuple[Optional[str], List[ToolCallRequest]]:
        """
        Parse LLM response to extract text and tool calls
        
        Args:
            response: LLM response dictionary
            
        Returns:
            Tuple of (response_text, list of tool call requests)
        """
        content = response.get('content')
        tool_calls = response.get('tool_calls', [])
        
        # Parse tool calls
        tool_call_requests = []
        for tool_call in tool_calls:
            if tool_call.get('type') == 'function':
                function = tool_call.get('function', {})
                
                # Parse arguments JSON string
                import json
                try:
                    arguments = json.loads(function.get('arguments', '{}'))
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse tool call arguments: {str(e)}")
                    arguments = {}
                
                tool_call_requests.append(ToolCallRequest(
                    id=tool_call.get('id', ''),
                    tool_name=function.get('name', ''),
                    parameters=arguments
                ))
        
        logger.debug(f"Parsed response: content={'present' if content else 'none'}, tool_calls={len(tool_call_requests)}")
        return content, tool_call_requests
    
    def process_conversation(
        self,
        conversation_history: List[Dict[str, str]],
        available_tools: List[Dict[str, Any]],
        tool_executor: Any,
        system_prompt: Optional[str] = None,
        max_iterations: int = 10
    ) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Process a conversation with tool execution loop and comprehensive error handling.

        Args:
            conversation_history: List of previous messages
            available_tools: List of available MCP tools
            tool_executor: Callable that executes tools (typically mcp_client.execute_tool)
            system_prompt: Optional system prompt
            max_iterations: Maximum number of tool execution iterations

        Returns:
            Tuple of (final_response_text, tool_calls_made, queries, result)

            ``queries`` is a deduplicated list of dicts
            {table, sql, parameters, row_count} harvested from every
            successful yb_query_table tool result during this conversation.
            It is empty when no data query ran. The SQL strings come
            verbatim from the server result and are never generated by the LLM.

            ``result`` is the raw result dict {table_name, columns, rows, row_count}
            from the *last* successful yb_query_table call, or None if no data
            query ran. Rows are the verbatim server-side values (already JSON-safe
            from query_table). This is the source of truth for chart rendering.
        """
        # Format messages
        messages = self.format_messages(conversation_history, system_prompt)
        
        # Format tools for LLM
        formatted_tools = self.format_tools_for_llm(available_tools) if available_tools else None
        
        tool_calls_made = []
        # Ordered list of query-transparency records, deduplicated by (sql, parameters).
        queries: List[Dict[str, Any]] = []
        _seen_queries: set = set()
        # Last successful yb_query_table result (for chart rendering).
        _last_result: Optional[Dict[str, Any]] = None
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Conversation iteration {iteration}/{max_iterations}")
            
            # Send message to LLM with error handling
            try:
                response = self.send_message(
                    messages=messages,
                    tools=formatted_tools,
                    tool_choice='auto'
                )
            except LLMAPIError as e:
                logger.error(f"LLM API error: {e.message}")
                return "I apologize, but the AI service is temporarily unavailable. Please try again in a moment.", tool_calls_made, queries, _last_result
            except TimeoutError as e:
                logger.error(f"LLM timeout: {e.message}")
                return "The request took too long to process. Please try a simpler query.", tool_calls_made, queries, _last_result
            except Exception as e:
                logger.error(f"Unexpected LLM error: {str(e)}", exc_info=True)
                return "I apologize, but I'm having trouble processing your request right now. Please try again later.", tool_calls_made, queries, _last_result
            
            # Parse response
            try:
                content, tool_requests = self.parse_response(response)
            except Exception as e:
                logger.error(f"Failed to parse LLM response: {str(e)}", exc_info=True)
                return "I received a response but couldn't process it properly. Please try again.", tool_calls_made, queries, _last_result
            
            # If no tool calls, return the response
            if not tool_requests:
                if content:
                    logger.info("Conversation complete with response")
                    return content, tool_calls_made, queries, _last_result
                else:
                    logger.warning("No content or tool calls in response")
                    return "I'm not sure how to respond to that.", tool_calls_made, queries, _last_result
            
            # Execute tool calls
            logger.info(f"Executing {len(tool_requests)} tool call(s)")
            
            # Add assistant message with tool calls to conversation
            messages.append({
                'role': 'assistant',
                'content': content or '',
                'tool_calls': response.get('tool_calls', [])
            })
            
            # Execute each tool and add results
            for tool_request in tool_requests:
                logger.debug(f"Executing tool: {tool_request.tool_name}")
                
                try:
                    # Execute tool via MCP client
                    tool_result = tool_executor(
                        tool_name=tool_request.tool_name,
                        parameters=tool_request.parameters
                    )
                    
                    # Record tool call
                    tool_calls_made.append({
                        'tool_name': tool_request.tool_name,
                        'parameters': tool_request.parameters,
                        'result': tool_result.result if hasattr(tool_result, 'result') else tool_result,
                        'error': tool_result.error if hasattr(tool_result, 'error') else None
                    })

                    # Harvest query-transparency data from yb_query_table results
                    _raw_result = tool_result.result if hasattr(tool_result, 'result') else tool_result
                    if (
                        tool_request.tool_name == "yb_query_table"
                        and isinstance(_raw_result, dict)
                        and _raw_result.get("success")
                        and "executed_sql" in _raw_result
                    ):
                        _sql = _raw_result["executed_sql"]
                        _params = _raw_result.get("parameters", [])
                        _dedup_key = (_sql, tuple(_params))
                        if _dedup_key not in _seen_queries:
                            _seen_queries.add(_dedup_key)
                            queries.append({
                                "table": _raw_result.get("table_name", ""),
                                "sql": _sql,
                                "parameters": _params,
                                "row_count": _raw_result.get("row_count", 0),
                            })
                        # Always update _last_result to the most recent data query
                        _last_result = _raw_result
                    
                    # Format result for LLM
                    if hasattr(tool_result, 'error') and tool_result.error:
                        result_content = f"Error: {tool_result.error}"
                        logger.warning(f"Tool {tool_request.tool_name} returned error: {tool_result.error}")
                    elif hasattr(tool_result, 'result'):
                        import json
                        try:
                            result_content = json.dumps(tool_result.result)
                        except (TypeError, ValueError) as e:
                            logger.error(f"Failed to serialize tool result: {str(e)}")
                            result_content = str(tool_result.result)
                    else:
                        import json
                        try:
                            result_content = json.dumps(tool_result)
                        except (TypeError, ValueError) as e:
                            logger.error(f"Failed to serialize tool result: {str(e)}")
                            result_content = str(tool_result)
                    
                    # Add tool result to messages
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_request.id,
                        'content': result_content
                    })
                    
                except Exception as e:
                    error_msg = f"Tool execution failed: {str(e)}"
                    logger.error(f"{error_msg} for {tool_request.tool_name}", exc_info=True)
                    
                    # Add error result to messages
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_request.id,
                        'content': error_msg
                    })
                    
                    tool_calls_made.append({
                        'tool_name': tool_request.tool_name,
                        'parameters': tool_request.parameters,
                        'result': None,
                        'error': error_msg
                    })
            
            # Continue loop to get LLM's response with tool results
        
        # Max iterations reached
        logger.warning(f"Max iterations ({max_iterations}) reached in conversation")
        return "I've gathered some information but need more time to process it. Please try rephrasing your question.", tool_calls_made, queries, _last_result
    
    def create_system_prompt(
        self,
        available_tools: List[Dict[str, Any]],
        grounding_values: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a system prompt that describes available tools.

        Args:
            available_tools:  List of available MCP tools.
            grounding_values: Optional dict {table: {column: [value, ...]}} of
                              distinct filter values fetched from the database.
                              When supplied, they are injected into the prompt so
                              the LLM never invents filter literals.

        Returns:
            System prompt string.
        """
        # Simple prompt for Gemini (no tool support)
        if self.config.provider == "gemini":
            return """You are a helpful AI assistant. Answer questions clearly and concisely based on your knowledge.
If you don't know something, just say so - don't make up information."""
        
        # Full prompt with tools for OpenAI
        base_prompt = """You are a helpful AI assistant with access to various data sources and tools.
You can help users query databases, search documents, and retrieve information.

When users ask questions:
1. Analyze what information is needed
2. Use the appropriate tools to gather data
3. Provide clear, concise answers based on the retrieved information
4. If you cannot find the information, explain what you tried and suggest alternatives

Always cite your sources when providing information from tools.

DATA SOURCES — route questions to the right backend:

Oracle APEX (tools: query_view, list_views, describe_view)
  Use for organisational or administrative data exposed as Oracle APEX views.
  Call describe_view to inspect columns before querying an unfamiliar view.

YugabyteDB shelter database (tools: yb_query_table, yb_list_tables, yb_describe_table)
  Use for animal shelter population data from California county shelters
  (LA County, Orange County, Riverside, San Bernardino, etc.).
  Tables are in the "awdc" schema, e.g. awdc.laas_population_data.
  IMPORTANT: call yb_describe_table once per table per conversation before
  your first yb_query_table for that table — the schema stays in conversation
  history so subsequent questions on the same table go straight to querying.
  Use the aggregates and group_by parameters of yb_query_table for COUNT,
  AVG, SUM, date-grouped trends, and filtered aggregates; do not fetch raw
  rows and aggregate in your response.
  For month-by-month trend questions, prefer a single yb_query_table call
  using a date_trunc month group_by together with date_relative filters
  using the max_date anchor (anchor="max_date") rather than querying
  multiple tables or years separately.

PDF documents (tools: search_pdfs, get_document, list_documents)
  Use for searching uploaded reference documents.

QUERY DISCIPLINE — awdc.laas_population_data
Follow these rules on every query. Violations cause zero-row results or
oversized payloads and must be avoided.

  1. DATASET SCOPE: awdc.laas_population_data contains ONLY Los Angeles
     County (LAAS) shelters. When a question refers to "LA County" or
     "Los Angeles County" it is describing the scope of the entire dataset
     — it is NOT a filter value. NEVER add a shelter or shelter_code
     filter for a county-level question. NEVER use "LA County", "Los
     Angeles County", or any county name as a filter value for any column.

  2. SHELTER FILTER — ONLY when explicitly named: add a shelter filter
     only when the user explicitly names a specific shelter (e.g. "East
     LA shelter"). Use the shelter column with a grounded value from the
     list below. Shelter names are NOT shelter_code values — never use
     a shelter name as a shelter_code filter value or vice versa.

  3. AGGREGATE FIRST — no raw-row dumps: for any counting, trend, or
     average question write a single GROUP BY aggregate query using the
     aggregates and group_by parameters of yb_query_table. NEVER issue
     SELECT * or any query that returns individual rows as an exploration
     step. A raw-row query will overflow the context window.

  4. ONE COLUMN, ONE CONDITION: never AND the same column against
     multiple different values in separate conditions — that always
     returns zero rows. Use the IN operator for multiple values of the
     same column, e.g. animal_type IN ('CAT', 'DOG').

  5. GROUNDED VALUES ONLY: filter values must be copied exactly from the
     grounded distinct values listed below for that column. If the user's
     wording does not match any grounded value, omit the filter rather
     than guessing.

  6. ZERO MEANS WRONG FORMULATION — not "no data": a zero-row result or
     a COUNT of 0 is never an answer to report as a finding. It means the
     query is formulated incorrectly. When reformulating: first DROP all
     shelter and shelter_code filters, then retry the aggregate without
     any geographic filter. Only add non-geographic filters back if the
     unfiltered query also returns zero rows.

  7. INTAKES MEANS ALL INTAKE EVENTS: a question about intakes, intake
     trends, or intake volume counts every row in the table, grouped by
     intake_date. NEVER add an outcome_type filter (such as ADOPTION) to
     an intake question, and never substitute adoptions or any other
     outcome subset for intakes. Use an outcome filter only when the
     question explicitly asks about that outcome."""

        # ---------------------------------------------------------------
        # Grounding block — injected when distinct values are available.
        # ---------------------------------------------------------------
        if grounding_values:
            grounding_lines = [
                "",
                "FILTER VALUE GROUNDING — awdc.laas_population_data",
                "The only valid filter literals for the columns below are listed here.",
                "Rules that MUST be followed:",
                "  1. Never invent a filter value. Map the user's wording to the closest",
                "     stored value (e.g. 'euthanasia' -> 'Euthanized', 'dogs' -> 'DOG').",
                "  2. Text equality filters on these columns use UPPER(col) = UPPER(value)",
                "     (operator '=') or operator 'IN' automatically — do NOT add UPPER()",
                "     yourself; the server handles case-folding.",
                "  3. If the user refers to a value that cannot be mapped to any stored",
                "     value, omit that filter entirely rather than guessing.",
                "  4. 'LA County' or 'Los Angeles' questions: the entire dataset is LAAS",
                "     (Los Angeles Animal Services). Do NOT add a shelter filter unless",
                "     the user is explicitly comparing shelters by name.",
                "  5. ZERO-ROW GUARDRAIL: if a yb_query_table call returns row_count=0",
                "     and the query had text filters, re-examine the filter values against",
                "     the grounded values below and retry ONCE with corrected values.",
                "     If the retry also returns 0 rows, state plainly: 'The query returned",
                "     no rows with the filters used: <list filters>' — never say 'no data",
                "     available' or invent a data-limitation explanation.",
            ]
            for table, col_map in grounding_values.items():
                for col, values in col_map.items():
                    if values:
                        values_str = ", ".join(f"'{v}'" for v in values)
                        grounding_lines.append(
                            f"  {table}.{col}: [{values_str}]"
                        )
                    else:
                        grounding_lines.append(
                            f"  {table}.{col}: (grounding unavailable — omit filter or use ILIKE)"
                        )
            base_prompt += "\n" + "\n".join(grounding_lines)
        else:
            # No grounding data — still inject the zero-row rule and case rule.
            base_prompt += (
                "\n\nFILTER VALUE RULES (awdc.laas_population_data):"
                "\n  1. Use UPPER(col) = UPPER(value) semantics (operator '=') for text"
                "\n     columns animal_type, outcome_type, shelter — the server case-folds"
                "\n     automatically."
                "\n  2. ZERO-ROW GUARDRAIL: if a query returns 0 rows and had text filters,"
                "\n     retry once with corrected filter values. If still 0 rows, say so"
                "\n     plainly naming the filters — never invent a data-limitation excuse."
            )

        if available_tools:
            tool_descriptions = "\n".join([
                f"- {tool['name']}: {tool.get('description', 'No description')}"
                for tool in available_tools
            ])
            base_prompt += f"\n\nAvailable tools:\n{tool_descriptions}"
        
        return base_prompt


def create_llm_service_from_env() -> LLMService:
    """
    Create LLM service from environment variables.

    Provider selection:
      LLM_PROVIDER=watsonx  → IBM watsonx.ai Granite adapter.
        Required: WATSONX_API_KEY, WATSONX_PROJECT_ID.
        Optional: WATSONX_URL   (default https://us-south.ml.cloud.ibm.com)
                  WATSONX_MODEL_ID (default ibm/granite-4-h-small)
      LLM_PROVIDER=gemini   → Google Gemini.  LLM_API_KEY required.
      LLM_PROVIDER=openai   → OpenAI (default). LLM_API_KEY required.

    Returns:
        Configured LLMService instance

    Raises:
        ValueError: If required environment variables are missing
    """
    provider = os.getenv('LLM_PROVIDER', 'openai').lower()

    if provider == 'watsonx':
        api_key = os.getenv('WATSONX_API_KEY')
        if not api_key:
            raise ValueError("WATSONX_API_KEY environment variable is required for LLM_PROVIDER=watsonx")
        project_id = os.getenv('WATSONX_PROJECT_ID')
        if not project_id:
            raise ValueError("WATSONX_PROJECT_ID environment variable is required for LLM_PROVIDER=watsonx")
        model = os.getenv('WATSONX_MODEL_ID', 'ibm/granite-4-h-small')
        base_url = os.getenv('WATSONX_URL', 'https://us-south.ml.cloud.ibm.com')
        config = LLMConfig(
            api_key=api_key,
            model=model,
            provider='watsonx',
            api_base_url=base_url,
            max_tokens=int(os.getenv('LLM_MAX_TOKENS', 1000)),
            temperature=float(os.getenv('LLM_TEMPERATURE', 0.7)),
            timeout=int(os.getenv('LLM_TIMEOUT', 60)),
            max_retries=int(os.getenv('LLM_MAX_RETRIES', 3)),
            watsonx_project_id=project_id,
        )
        logger.info(f"LLM service configuration loaded: provider=watsonx, model={model}, project={project_id}")
        return LLMService(config)

    # --- openai / gemini paths (unchanged) ---
    api_key = os.getenv('LLM_API_KEY')
    if not api_key:
        raise ValueError("LLM_API_KEY environment variable is required")

    model = os.getenv('LLM_MODEL', 'gemini-pro' if provider == 'gemini' else 'gpt-4')

    config = LLMConfig(
        api_key=api_key,
        model=model,
        provider=provider,
        api_base_url=os.getenv('LLM_API_BASE_URL'),
        max_tokens=int(os.getenv('LLM_MAX_TOKENS', 1000)),
        temperature=float(os.getenv('LLM_TEMPERATURE', 0.7)),
        timeout=int(os.getenv('LLM_TIMEOUT', 30)),
        max_retries=int(os.getenv('LLM_MAX_RETRIES', 3))
    )

    logger.info(f"LLM service configuration loaded: provider={provider}, model={model}")
    return LLMService(config)
