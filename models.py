from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class PertanyaanRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pertanyaan: str = Field(min_length=3, max_length=2000)
    divisi: str | None = Field(default=None, max_length=100)
    tahun: int | None = Field(default=None, ge=2000, le=2100)
    document_id: int | None = Field(default=None, ge=1)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    top_k: int = Field(default=8, ge=1, le=12)

    @field_validator("history", mode="before")
    @classmethod
    def optional_history(cls, value):
        return value or []
