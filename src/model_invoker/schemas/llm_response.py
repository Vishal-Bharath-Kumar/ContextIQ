from pydantic import BaseModel, ConfigDict


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    content: str
    input_tokens: int
    output_tokens: int
    finish_reason: str  # "stop" | "length" | "tool_calls" | "error"
