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
    provider: str = "openai"  # "openai" or "gemini"
    api_base_url: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.7
    timeout: int = 30
    max_retries: int = 3


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
        
        if config.provider == "gemini":
            # Initialize Gemini
            genai = _get_genai()
            genai.configure(api_key=config.api_key)
            self.client = genai.GenerativeModel(config.model)
            logger.info(f"LLMService initialized with Gemini model: {config.model}")
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
    
    def create_system_prompt(self, available_tools: List[Dict[str, Any]]) -> str:
        """
        Create a system prompt that describes available tools
        
        Args:
            available_tools: List of available MCP tools
            
        Returns:
            System prompt string
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
  Use for searching uploaded reference documents."""
        
        if available_tools:
            tool_descriptions = "\n".join([
                f"- {tool['name']}: {tool.get('description', 'No description')}"
                for tool in available_tools
            ])
            base_prompt += f"\n\nAvailable tools:\n{tool_descriptions}"
        
        return base_prompt


def create_llm_service_from_env() -> LLMService:
    """
    Create LLM service from environment variables
    
    Returns:
        Configured LLMService instance
        
    Raises:
        ValueError: If required environment variables are missing
    """
    api_key = os.getenv('LLM_API_KEY')
    if not api_key:
        raise ValueError("LLM_API_KEY environment variable is required")
    
    provider = os.getenv('LLM_PROVIDER', 'openai').lower()
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
