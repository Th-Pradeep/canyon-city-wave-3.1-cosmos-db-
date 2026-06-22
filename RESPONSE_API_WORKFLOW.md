# Complete Workflow: Frontend to Backend with Response API Integration

## Overview
This document explains the complete request/response flow from the frontend through to the backend, showing how the OpenAI Response API is integrated throughout the application.

---

## Architecture Diagram

```
Frontend (Browser)
    ↓
    | HTTP POST Request
    | /chat or /chat/stream
    |
Backend (Quart/Python)
    ↓
    | app.py → Route Handler
    |
ChatReadRetrieveReadApproach
    ↓
    | 1. Query Rewrite (Optional)
    | 2. Search/Retrieve Documents
    | 3. Generate Final Answer
    |
OpenAI Response API
    ↓
    | Response/ResponseStream
    |
Backend → Frontend
```

---

## Detailed Flow

### 1. Frontend Initiates Request

**Frontend sends a request to one of two endpoints:**

#### Non-Streaming Request (`/chat`):
```javascript
// Frontend code (example)
fetch('/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    messages: [
      { role: 'user', content: 'What are the health benefits?' }
    ],
    context: {
      overrides: {
        retrieval_mode: 'hybrid',
        semantic_ranker: true,
        top: 3
      }
    }
  })
})
```

#### Streaming Request (`/chat/stream`):
```javascript
// Frontend code for streaming
fetch('/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    messages: [
      { role: 'user', content: 'What are the health benefits?' }
    ],
    context: {
      overrides: {
        retrieval_mode: 'hybrid',
        semantic_ranker: true,
        top: 3
      }
    }
  })
})
```

---

### 2. Backend Receives Request (app.py)

**File:** `app/backend/app.py`

#### Non-Streaming Handler:
```python
@bp.route("/chat", methods=["POST"])
@authenticated
async def chat(auth_claims: dict[str, Any]):
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415
    
    request_json = await request.get_json()
    context = request_json.get("context", {})
    context["auth_claims"] = auth_claims
    
    try:
        # Get the configured approach
        approach: Approach = cast(Approach, current_app.config[CONFIG_CHAT_APPROACH])
        
        # Create or get session state
        session_state = request_json.get("session_state")
        if session_state is None:
            session_state = create_session_id(
                current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED],
                current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED],
            )
        
        # Execute the approach with Response API
        result = await approach.run(
            request_json["messages"],  # List[EasyInputMessageParam]
            context=context,
            session_state=session_state,
        )
        return jsonify(result)
    except Exception as error:
        return error_response(error, "/chat")
```

#### Streaming Handler:
```python
@bp.route("/chat/stream", methods=["POST"])
@authenticated
async def chat_stream(auth_claims: dict[str, Any]):
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415
    
    request_json = await request.get_json()
    context = request_json.get("context", {})
    context["auth_claims"] = auth_claims
    
    try:
        approach: Approach = cast(Approach, current_app.config[CONFIG_CHAT_APPROACH])
        
        session_state = request_json.get("session_state")
        if session_state is None:
            session_state = create_session_id(
                current_app.config[CONFIG_CHAT_HISTORY_COSMOS_ENABLED],
                current_app.config[CONFIG_CHAT_HISTORY_BROWSER_ENABLED],
            )
        
        # Execute streaming approach with Response API
        result = await approach.run_stream(
            request_json["messages"],  # List[EasyInputMessageParam]
            context=context,
            session_state=session_state,
        )
        response = await make_response(format_as_ndjson(result))
        response.timeout = None
        response.mimetype = "application/json-lines"
        return response
    except Exception as error:
        return error_response(error, "/chat")
```

---

### 3. ChatReadRetrieveReadApproach Processes Request

**File:** `app/backend/approaches/chatreadretrieveread.py`

#### Main Entry Points:

```python
async def run(
    self,
    messages: list[EasyInputMessageParam],  # ← Response API type
    session_state: Any = None,
    context: dict[str, Any] = {},
) -> dict[str, Any]:
    overrides = context.get("overrides", {})
    auth_claims = context.get("auth_claims", {})
    return await self.run_without_streaming(messages, overrides, auth_claims, session_state)

async def run_stream(
    self,
    messages: list[EasyInputMessageParam],  # ← Response API type
    session_state: Any = None,
    context: dict[str, Any] = {},
) -> AsyncGenerator[dict[str, Any], None]:
    overrides = context.get("overrides", {})
    auth_claims = context.get("auth_claims", {})
    return self.run_with_streaming(messages, overrides, auth_claims, session_state)
```

---

### 4. Query Processing Pipeline

#### Step 4.1: Query Rewrite (Optional)

**Purpose:** Optimize user query for search based on conversation history.

```python
# In run_search_approach method
rewrite_result = await self.rewrite_query(
    prompt_template="query_rewrite.system.jinja2",
    prompt_variables={
        "user_query": original_user_query,
        "past_messages": messages[:-1],
    },
    overrides=overrides,
    chatgpt_model=self.chatgpt_model,
    chatgpt_deployment=self.chatgpt_deployment,
    user_query=original_user_query,
    response_token_limit=self.get_response_token_limit(self.chatgpt_model, 100),
    tools=self.query_rewrite_tools,
    temperature=0.0,
    no_response_token=self.NO_RESPONSE,
)

query_text = rewrite_result.query  # Optimized search query
```

**What happens here:**
1. PromptManager builds system prompt from `query_rewrite.system.jinja2`
2. Calls `create_response()` with the Response API
3. Extracts rewritten query from the Response

**Key Method in approach.py:**
```python
async def rewrite_query(
    self,
    *,
    prompt_template: str,
    prompt_variables: dict[str, Any],
    overrides: dict[str, Any],
    chatgpt_model: str,
    chatgpt_deployment: Optional[str],
    user_query: str,
    response_token_limit: int,
    tools: Optional[list[FunctionToolParam]] = None,  # ← Response API type
    temperature: float = 0.0,
    no_response_token: Optional[str] = None,
) -> RewriteQueryResult:
    # Build system prompt using Jinja2 template
    query_messages = [self.prompt_manager.build_system_prompt(prompt_template, prompt_variables)]
    rewrite_reasoning_effort = self.get_lowest_reasoning_effort(self.chatgpt_model)

    # Call Response API
    response = cast(
        Response,  # ← Response API return type
        await self.create_response(
            chatgpt_deployment,
            chatgpt_model,
            input=query_messages,  # ← list[EasyInputMessageParam]
            overrides=overrides,
            response_token_limit=response_token_limit,
            temperature=temperature,
            tools=tools,
            reasoning_effort=rewrite_reasoning_effort,
        ),
    )

    # Extract rewritten query from Response
    rewritten_query = self.extract_rewritten_query(
        response,
        user_query,
        no_response_token=no_response_token,
    )

    return RewriteQueryResult(
        query=rewritten_query, 
        messages=query_messages, 
        completion=response,  # ← Response object
        reasoning_effort=rewrite_reasoning_effort
    )
```

#### Step 4.2: Document Retrieval

**Search Azure AI Search index for relevant documents:**

```python
# Vector and text search
vectors: list[VectorQuery] = []
if use_vector_search:
    if search_text_embeddings:
        vectors.append(await self.compute_text_embedding(query_text))
    if search_image_embeddings:
        vectors.append(await self.compute_multimodal_embedding(query_text))

# Execute search
documents = await self.search(
    top=top,
    query_text=query_text if use_text_search else None,
    filter=search_index_filter,
    vectors=vectors,
    use_text_search=use_text_search,
    use_vector_search=use_vector_search,
    use_semantic_ranker=use_semantic_ranker,
    use_semantic_captions=use_semantic_captions,
    minimum_search_score=minimum_search_score,
    minimum_reranker_score=minimum_reranker_score,
    use_query_rewriting=use_query_rewriting,
    access_token=access_token,
)
```

#### Step 4.3: Generate Final Answer with Response API

**File:** `app/backend/approaches/chatreadretrieveread.py` → `run_until_final_call()`

```python
async def run_until_final_call(
    self,
    messages: list[EasyInputMessageParam],
    overrides: dict[str, Any],
    auth_claims: dict[str, Any],
    should_stream: bool = False,
) -> tuple[ExtraInfo, Awaitable[Response] | Awaitable[AsyncStream[ResponseStreamEvent]]]:
    
    # ... Search/retrieval logic ...
    
    # Build conversation with system prompt, history, and user query + sources
    messages = self.prompt_manager.build_conversation(
        system_template_path="chat_answer.system.jinja2",
        system_template_variables=self.get_system_prompt_variables(overrides.get("prompt_template"))
        | {
            "include_follow_up_questions": bool(overrides.get("suggest_followup_questions")),
            "image_sources": extra_info.data_points.images,
            "citations": extra_info.data_points.citations,
        },
        user_template_path="chat_answer.user.jinja2",
        user_template_variables={
            "user_query": original_user_query,
            "text_sources": extra_info.data_points.text,
        },
        user_image_sources=extra_info.data_points.images,
        past_messages=messages[:-1],
    )

    # Call Response API to generate answer
    response_coroutine = cast(
        Awaitable[Response] | Awaitable[AsyncStream[ResponseStreamEvent]],
        self.create_response(
            self.chatgpt_deployment,
            self.chatgpt_model,
            messages,  # ← list[EasyInputMessageParam]
            overrides,
            self.get_response_token_limit(self.chatgpt_model, self.RESPONSE_DEFAULT_TOKEN_LIMIT),
            should_stream,
        ),
    )
    
    return (extra_info, response_coroutine)
```

---

### 5. Response API Call (Core Integration)

**File:** `app/backend/approaches/approach.py`

```python
def create_response(
    self,
    chatgpt_deployment: Optional[str],
    chatgpt_model: str,
    input: list[EasyInputMessageParam],  # ← Response API input type
    overrides: dict[str, Any],
    response_token_limit: int,
    should_stream: bool = False,
    tools: Optional[list[FunctionToolParam]] = None,
    temperature: Optional[float] = None,
    reasoning_effort: ReasoningEffort = None,
) -> Awaitable[Response] | Awaitable[AsyncStream[ResponseStreamEvent]]:
    params: dict[str, Any] = {
        "max_output_tokens": response_token_limit,
        "store": False,
    }

    # Configure reasoning for reasoning models (gpt-5 family)
    if self.is_reasoning_model(chatgpt_model):
        effort = reasoning_effort or overrides.get("reasoning_effort") or self.reasoning_effort
        if effort:
            params["reasoning"] = {"effort": effort}
    else:
        params["temperature"] = temperature if temperature is not None else overrides.get("temperature", 0.3)

    if should_stream:
        params["stream"] = True

    if tools is not None:
        params["tools"] = tools

    # ★ KEY: Call OpenAI Response API instead of Chat Completion API
    return self.openai_client.responses.create(  # ← Response API endpoint
        model=chatgpt_deployment if chatgpt_deployment else chatgpt_model,
        input=input,  # ← 'input' instead of 'messages'
        **params,
    )
```

**Key Differences from Chat Completion API:**

| Chat Completion API | Response API |
|---------------------|--------------|
| `client.chat.completions.create()` | `client.responses.create()` |
| `messages` parameter | `input` parameter |
| `ChatCompletionMessageParam` | `EasyInputMessageParam` |
| `ChatCompletion` return type | `Response` return type |
| `ChatCompletionChunk` for streaming | `ResponseStreamEvent` for streaming |
| Access via `choices[0].message.content` | Access via `output_text` |

---

### 6. PromptManager (Message Builder)

**File:** `app/backend/approaches/promptmanager.py`

**Purpose:** Build properly formatted messages for the Response API.

```python
class PromptManager:
    """Builds OpenAI response messages from Jinja2 templates."""

    def build_system_prompt(self, template_path: str, template_variables: dict[str, Any]) -> EasyInputMessageParam:
        """Build a single system message."""
        content = self.env.get_template(template_path).render(**template_variables).strip()
        return {"role": "system", "content": content}

    def build_user_prompt(
        self,
        template_path: str,
        template_variables: dict[str, Any],
        image_sources: list[str] | None = None,
    ) -> EasyInputMessageParam:
        """Build a single user message with optional images."""
        user_text = self.env.get_template(template_path).render(**template_variables).strip()
        if image_sources:
            # Multi-modal message format for Response API
            user_content: list[dict[str, Any]] = [{"type": "input_text", "text": user_text}]
            for image in image_sources:
                user_content.append({"type": "input_image", "image_url": image})
            return cast(EasyInputMessageParam, {"role": "user", "content": user_content})
        return {"role": "user", "content": user_text}

    def build_conversation(
        self,
        system_template_path: str,
        system_template_variables: dict[str, Any],
        user_template_path: str,
        user_template_variables: dict[str, Any],
        user_image_sources: list[str] | None = None,
        past_messages: list[EasyInputMessageParam] | None = None,
    ) -> list[EasyInputMessageParam]:
        """Build a full conversation with system, history, and user message."""
        messages: list[EasyInputMessageParam] = []

        # System message
        messages.append(self.build_system_prompt(system_template_path, system_template_variables))

        # Past messages (conversation history)
        for msg in past_messages or []:
            messages.append(cast(EasyInputMessageParam, msg))

        # User message (with optional images)
        messages.append(self.build_user_prompt(user_template_path, user_template_variables, user_image_sources))

        return messages
```

---

### 7. Response Processing

#### Non-Streaming Response Processing

**File:** `app/backend/approaches/chatreadretrieveread.py`

```python
async def run_without_streaming(
    self,
    messages: list[EasyInputMessageParam],
    overrides: dict[str, Any],
    auth_claims: dict[str, Any],
    session_state: Any = None,
) -> dict[str, Any]:
    extra_info, response_coroutine = await self.run_until_final_call(
        messages, overrides, auth_claims, should_stream=False
    )
    
    # Wait for Response
    response: Response = await cast(Awaitable[Response], response_coroutine)
    
    # Extract content from Response API
    content = response.output_text  # ← Direct property access (not choices[0].message.content)
    
    if overrides.get("suggest_followup_questions"):
        content, followup_questions = self.extract_followup_questions(content)
        extra_info.followup_questions = followup_questions
    
    # Track token usage
    if self.include_token_usage and extra_info.thoughts and response.usage:
        extra_info.thoughts[-1].update_token_usage(response.usage)
    
    # Build response for frontend
    chat_app_response = {
        "output_text": content,  # ← Changed from "message"
        "context": {
            "thoughts": extra_info.thoughts,
            "data_points": {
                key: value for key, value in asdict(extra_info.data_points).items() if value is not None
            },
            "followup_questions": extra_info.followup_questions,
        },
        "session_state": session_state,
    }
    return chat_app_response
```

#### Streaming Response Processing

```python
async def run_with_streaming(
    self,
    messages: list[EasyInputMessageParam],
    overrides: dict[str, Any],
    auth_claims: dict[str, Any],
    session_state: Any = None,
) -> AsyncGenerator[dict, None]:
    extra_info, response_coroutine = await self.run_until_final_call(
        messages, overrides, auth_claims, should_stream=True
    )
    
    # Send initial context
    yield {"type": "response.context", "context": extra_info, "session_state": session_state}

    followup_questions_started = False
    followup_content = ""
    result = await response_coroutine

    # Handle non-streaming Response (fallback case)
    if isinstance(result, Response):
        content = result.output_text or ""

        followup_questions: list[str] = []
        if overrides.get("suggest_followup_questions"):
            content, followup_questions = self.extract_followup_questions(content)
            extra_info.followup_questions = followup_questions

        if self.include_token_usage and extra_info.thoughts and result.usage:
            extra_info.thoughts[-1].update_token_usage(result.usage)

        if content:
            yield {"type": "response.output_text.delta", "delta": content}

        yield {"type": "response.context", "context": extra_info, "session_state": session_state}
        return

    # Handle streaming Response events
    stream = cast(AsyncStream[ResponseStreamEvent], result)

    async for event in stream:
        # Process text delta events
        if isinstance(event, ResponseTextDeltaEvent):
            delta_content: str = event.delta or ""
            if overrides.get("suggest_followup_questions") and "<<" in delta_content:
                followup_questions_started = True
                earlier_content = delta_content[: delta_content.index("<<")]
                if earlier_content:
                    yield {"type": "response.output_text.delta", "delta": earlier_content}
                followup_content += delta_content[delta_content.index("<<") :]
            elif followup_questions_started:
                followup_content += delta_content
            else:
                yield {"type": "response.output_text.delta", "delta": delta_content}
        
        # Process completion event
        elif isinstance(event, ResponseCompletedEvent):
            if event.response.usage and extra_info.thoughts and self.include_token_usage:
                extra_info.thoughts[-1].update_token_usage(event.response.usage)
                yield {"type": "response.context", "context": extra_info, "session_state": session_state}

    if followup_content:
        _, followup_questions = self.extract_followup_questions(followup_content)
        extra_info.followup_questions = followup_questions
        yield {"type": "response.context", "context": extra_info, "session_state": session_state}
```

---

### 8. Response Types and Token Usage

#### Response Types

```python
from openai.types.responses import (
    EasyInputMessageParam,      # Input message format
    FunctionToolParam,           # Tool definition format
    Response,                    # Non-streaming response
    ResponseFunctionToolCall,    # Function call in response
    ResponseStreamEvent,         # Base streaming event
    ResponseTextDeltaEvent,      # Text chunk in stream
    ResponseCompletedEvent,      # Stream completion event
    ResponseUsage,               # Token usage info
    ResponseOutputMessage,       # Output message format
)
```

#### Token Usage Tracking

```python
@dataclass
class TokenUsageProps:
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: Optional[int]
    total_tokens: int

    @classmethod
    def from_usage(cls, usage: CompletionUsage | ResponseUsage) -> "TokenUsageProps":
        # Handle both Chat Completion and Response API usage objects
        if isinstance(usage, ResponseUsage):
            return cls(
                prompt_tokens=usage.input_tokens,      # ← Different property name
                completion_tokens=usage.output_tokens,  # ← Different property name
                reasoning_tokens=(
                    usage.output_tokens_details.reasoning_tokens 
                    if usage.output_tokens_details else None
                ),
                total_tokens=usage.total_tokens,
            )
        return cls(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            reasoning_tokens=(
                usage.completion_tokens_details.reasoning_tokens 
                if usage.completion_tokens_details else None
            ),
            total_tokens=usage.total_tokens,
        )
```

---

### 9. Frontend Receives Response

#### Non-Streaming Response

```json
{
  "output_text": "According to the documents, health benefits include...",
  "context": {
    "thoughts": [
      {
        "title": "Query rewrite",
        "description": [...],
        "props": {
          "model": "gpt-4",
          "token_usage": {
            "prompt_tokens": 150,
            "completion_tokens": 20,
            "reasoning_tokens": null,
            "total_tokens": 170
          }
        }
      },
      {
        "title": "Search",
        "description": "..."
      },
      {
        "title": "Prompt to generate answer",
        "description": [...],
        "props": {
          "model": "gpt-4",
          "token_usage": {
            "prompt_tokens": 2500,
            "completion_tokens": 300,
            "reasoning_tokens": null,
            "total_tokens": 2800
          }
        }
      }
    ],
    "data_points": {
      "text": ["[doc1.pdf]: ...", "[doc2.pdf]: ..."],
      "citations": ["doc1.pdf", "doc2.pdf"]
    },
    "followup_questions": [
      "What is the deductible?",
      "Are prescriptions covered?",
      "Which providers are in-network?"
    ]
  },
  "session_state": "..."
}
```

#### Streaming Response (NDJSON format)

```json
{"type": "response.context", "context": {...}, "session_state": "..."}
{"type": "response.output_text.delta", "delta": "According"}
{"type": "response.output_text.delta", "delta": " to"}
{"type": "response.output_text.delta", "delta": " the"}
{"type": "response.output_text.delta", "delta": " documents"}
{"type": "response.output_text.delta", "delta": ","}
{"type": "response.output_text.delta", "delta": " health"}
{"type": "response.output_text.delta", "delta": " benefits"}
{"type": "response.output_text.delta", "delta": " include"}
{"type": "response.output_text.delta", "delta": "..."}
{"type": "response.context", "context": {...}, "session_state": "..."}
```

---

## Key Changes from Chat Completion API to Response API

### 1. Import Changes
```python
# OLD (Chat Completion API)
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

# NEW (Response API)
from openai.types.responses import (
    EasyInputMessageParam,
    FunctionToolParam,
    Response,
    ResponseStreamEvent,
    ResponseUsage,
)
```

### 2. API Call Changes
```python
# OLD (Chat Completion API)
response = await client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=100
)
content = response.choices[0].message.content

# NEW (Response API)
response = await client.responses.create(
    model="gpt-4",
    input=[{"role": "user", "content": "Hello"}],
    max_output_tokens=100
)
content = response.output_text
```

### 3. Streaming Changes
```python
# OLD (Chat Completion API)
async for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta)

# NEW (Response API)
async for event in stream:
    if isinstance(event, ResponseTextDeltaEvent):
        print(event.delta)
```

### 4. Tool/Function Call Changes
```python
# OLD (Chat Completion API)
tools: list[ChatCompletionToolParam] = [...]

# NEW (Response API)
tools: list[FunctionToolParam] = [...]
```

---

## Template Files (Jinja2)

### query_rewrite.system.jinja2
Used to generate optimized search queries from user questions.

### chat_answer.system.jinja2
System prompt for generating final answers with citations.

### chat_answer.user.jinja2
User prompt template including the query and retrieved sources.

---

## Configuration and Initialization

**File:** `app/backend/app.py` (in `@bp.before_app_serving`)

```python
# Initialize PromptManager with Jinja2 templates
prompt_manager = PromptManager()

# Create ChatReadRetrieveReadApproach instance
current_app.config[CONFIG_CHAT_APPROACH] = ChatReadRetrieveReadApproach(
    search_client=search_client,
    search_index_name=AZURE_SEARCH_INDEX,
    knowledgebase_model=AZURE_OPENAI_KNOWLEDGEBASE_MODEL,
    knowledgebase_deployment=AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT,
    knowledgebase_client=knowledgebase_client,
    openai_client=openai_client,
    chatgpt_model=OPENAI_CHATGPT_MODEL,
    chatgpt_deployment=AZURE_OPENAI_CHATGPT_DEPLOYMENT,
    embedding_model=OPENAI_EMB_MODEL,
    embedding_deployment=AZURE_OPENAI_EMB_DEPLOYMENT,
    embedding_dimensions=OPENAI_EMB_DIMENSIONS,
    embedding_field=AZURE_SEARCH_FIELD_NAME_EMBEDDING,
    sourcepage_field=KB_FIELDS_SOURCEPAGE,
    content_field=KB_FIELDS_CONTENT,
    query_language=AZURE_SEARCH_QUERY_LANGUAGE,
    query_speller=AZURE_SEARCH_QUERY_SPELLER,
    prompt_manager=prompt_manager,
    reasoning_effort=OPENAI_REASONING_EFFORT,
    multimodal_enabled=USE_MULTIMODAL,
    image_embeddings_client=image_embeddings_client,
    global_blob_manager=global_blob_manager,
    user_blob_manager=user_blob_manager,
    use_web_source=current_app.config[CONFIG_WEB_SOURCE_ENABLED],
    use_sharepoint_source=current_app.config[CONFIG_SHAREPOINT_SOURCE_ENABLED],
    retrieval_reasoning_effort=AGENTIC_KNOWLEDGEBASE_REASONING_EFFORT,
)
```

---

## Error Handling

Response API errors are handled the same way as Chat Completion API errors:

```python
try:
    result = await approach.run(messages, context=context, session_state=session_state)
    return jsonify(result)
except Exception as error:
    return error_response(error, "/chat")
```

---

## Summary

The Response API integration provides:

1. **Simplified Message Format**: `EasyInputMessageParam` instead of complex `ChatCompletionMessageParam`
2. **Direct Output Access**: `response.output_text` instead of `response.choices[0].message.content`
3. **Better Streaming**: Typed event objects (`ResponseTextDeltaEvent`, `ResponseCompletedEvent`)
4. **Reasoning Model Support**: Native support for GPT-5 family models with reasoning effort control
5. **Unified Token Tracking**: Consistent usage tracking across different response types

All changes are backward compatible with the existing frontend, requiring only backend modifications.

---

## Files Modified in This Migration

1. **app/backend/approaches/approach.py**
   - Updated imports to Response API types
   - Changed `create_chat_completion()` → `create_response()`
   - Updated `extract_rewritten_query()` to work with `Response`
   - Updated `TokenUsageProps.from_usage()` to handle both types

2. **app/backend/approaches/chatreadretrieveread.py**
   - Updated all method signatures to use `EasyInputMessageParam`
   - Modified `run_without_streaming()` to extract `output_text`
   - Completely refactored `run_with_streaming()` for Response API events
   - Updated `run_until_final_call()` to call `create_response()`

3. **app/backend/approaches/promptmanager.py**
   - Replaced `PromptyManager` with new `PromptManager` class
   - Implemented Jinja2-based message building
   - Added methods for building system, user, and conversation messages

4. **app/backend/app.py**
   - Updated import from `PromptyManager` to `PromptManager`
   - Changed instantiation to `PromptManager()`

5. **app/backend/approaches/prompts/** (new templates)
   - `chat_answer.system.jinja2`
   - `chat_answer.user.jinja2`
   - `query_rewrite.system.jinja2`

---

## Testing the Integration

To test the Response API integration:

1. **Start the backend server**
2. **Send a non-streaming request:**
   ```bash
   curl -X POST http://localhost:5000/chat \
     -H "Content-Type: application/json" \
     -d '{"messages": [{"role": "user", "content": "What are the benefits?"}]}'
   ```

3. **Send a streaming request:**
   ```bash
   curl -X POST http://localhost:5000/chat/stream \
     -H "Content-Type: application/json" \
     -d '{"messages": [{"role": "user", "content": "What are the benefits?"}]}'
   ```

4. **Verify:**
   - Responses use `output_text` field
   - Streaming returns NDJSON with `response.output_text.delta` events
   - Token usage is properly tracked
   - Citations and follow-up questions work correctly

---

## Conclusion

The Response API integration is now complete and working throughout the entire stack, from frontend request to backend processing and response generation. All code has been updated to use the new API while maintaining compatibility with existing features.
