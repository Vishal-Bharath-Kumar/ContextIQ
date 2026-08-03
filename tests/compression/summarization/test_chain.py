"""Unit tests for SummarizationChain and SummarizationOutput (TASK-US017-03)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.compression.summarization.chain import SummarizationChain, SummarizationOutput

# ---------------------------------------------------------------------------
# SummarizationOutput model
# ---------------------------------------------------------------------------


class TestSummarizationOutput:
    def test_valid_with_entities(self) -> None:
        result = SummarizationOutput.model_validate(
            {"summary": "Service calls HTTP 401 on auth failure.", "retained_entities": ["HTTP 401"]}
        )
        assert result.summary == "Service calls HTTP 401 on auth failure."
        assert result.retained_entities == ["HTTP 401"]

    def test_valid_empty_entities_default(self) -> None:
        result = SummarizationOutput.model_validate({"summary": "Some summary.", "retained_entities": []})
        assert result.summary == "Some summary."
        assert result.retained_entities == []

    def test_entities_default_factory(self) -> None:
        result = SummarizationOutput(summary="Summary text.")
        assert result.retained_entities == []

    def test_missing_summary_raises(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationOutput.model_validate({"retained_entities": []})

    def test_summary_must_be_string(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationOutput.model_validate({"summary": 123})


# ---------------------------------------------------------------------------
# SummarizationChain construction
# ---------------------------------------------------------------------------


class TestSummarizationChainInit:
    @patch("src.compression.summarization.chain.LiteLLMChain")
    @patch("src.compression.summarization.chain.get_summarization_settings")
    def test_chain_constructed_once(self, mock_get_settings: MagicMock, mock_chain: MagicMock) -> None:
        mock_settings = MagicMock()
        mock_settings.model_name = "ollama/llama3.2"
        mock_settings.max_output_tokens = 400
        mock_settings.target_ratio = 0.40
        mock_settings.timeout_s = 30.0
        mock_get_settings.return_value = mock_settings

        chain = SummarizationChain()

        mock_chain.assert_called_once_with(
            chain._prompt,
            pytest.ANY,
            model_id="ollama/llama3.2",
            temperature=0.0,
            max_tokens=400,
            timeout_s=30.0,
        )
        assert chain._chain is not None

    @patch("src.compression.summarization.chain.LiteLLMChain")
    @patch("src.compression.summarization.chain.get_summarization_settings")
    def test_llm_temperature_is_zero(self, mock_get_settings: MagicMock, mock_chain: MagicMock) -> None:
        mock_settings = MagicMock()
        mock_settings.model_name = "ollama/llama3.2"
        mock_settings.max_output_tokens = 400
        mock_settings.target_ratio = 0.40
        mock_settings.timeout_s = 30.0
        mock_get_settings.return_value = mock_settings

        SummarizationChain()

        _, kwargs = mock_chain.call_args
        assert kwargs["temperature"] == 0.0


# ---------------------------------------------------------------------------
# SummarizationChain.summarise()
# ---------------------------------------------------------------------------


VALID_LLM_RESPONSE = {
    "summary": "The authenticate function returns HTTP 401 when credentials are invalid.",
    "retained_entities": ["authenticate", "HTTP 401"],
}


class TestSummarizationChainSummarise:
    @pytest.fixture()
    def chain_with_mock_llm(self) -> SummarizationChain:
        with (
            patch("src.compression.summarization.chain.LiteLLMChain"),
            patch("src.compression.summarization.chain.get_summarization_settings") as mock_settings_fn,
        ):
            mock_settings = MagicMock()
            mock_settings.model_name = "ollama/llama3.2"
            mock_settings.max_output_tokens = 400
            mock_settings.target_ratio = 0.40
            mock_settings.timeout_s = 30.0
            mock_settings_fn.return_value = mock_settings

            chain = SummarizationChain()
            chain._chain = MagicMock()
            chain._chain.ainvoke = AsyncMock(return_value=VALID_LLM_RESPONSE)
            return chain

    @pytest.mark.asyncio
    async def test_returns_summarization_output(self, chain_with_mock_llm: SummarizationChain) -> None:
        result = await chain_with_mock_llm.summarise(
            content="def authenticate(): ...", input_tokens=10
        )
        assert isinstance(result, SummarizationOutput)

    @pytest.mark.asyncio
    async def test_summary_is_non_empty(self, chain_with_mock_llm: SummarizationChain) -> None:
        result = await chain_with_mock_llm.summarise(
            content="def authenticate(): ...", input_tokens=10
        )
        assert result.summary != ""

    @pytest.mark.asyncio
    async def test_http_401_preserved_in_summary(self, chain_with_mock_llm: SummarizationChain) -> None:
        result = await chain_with_mock_llm.summarise(
            content="The endpoint returns HTTP 401 when the token is expired.", input_tokens=15
        )
        assert "HTTP 401" in result.summary

    @pytest.mark.asyncio
    async def test_authenticate_in_summary_or_entities(self, chain_with_mock_llm: SummarizationChain) -> None:
        result = await chain_with_mock_llm.summarise(
            content="def authenticate(): validates credentials and returns a JWT.", input_tokens=12
        )
        present = "authenticate" in result.summary or "authenticate" in result.retained_entities
        assert present

    @pytest.mark.asyncio
    async def test_retained_entities_extracted(self, chain_with_mock_llm: SummarizationChain) -> None:
        result = await chain_with_mock_llm.summarise(
            content="def authenticate(): ...", input_tokens=10
        )
        assert isinstance(result.retained_entities, list)
        assert "authenticate" in result.retained_entities

    @pytest.mark.asyncio
    async def test_callbacks_forwarded(self, chain_with_mock_llm: SummarizationChain) -> None:
        mock_callback = MagicMock()
        await chain_with_mock_llm.summarise(
            content="some content", input_tokens=5, callbacks=[mock_callback]
        )
        _, kwargs = chain_with_mock_llm._chain.ainvoke.call_args
        assert kwargs["config"]["callbacks"] == [mock_callback]

    @pytest.mark.asyncio
    async def test_callbacks_defaults_to_empty_list(self, chain_with_mock_llm: SummarizationChain) -> None:
        await chain_with_mock_llm.summarise(content="some content", input_tokens=5)
        _, kwargs = chain_with_mock_llm._chain.ainvoke.call_args
        assert kwargs["config"]["callbacks"] == []

    @pytest.mark.asyncio
    async def test_target_pct_passed_to_chain(self, chain_with_mock_llm: SummarizationChain) -> None:
        await chain_with_mock_llm.summarise(content="text", input_tokens=20)
        call_args, _ = chain_with_mock_llm._chain.ainvoke.call_args
        payload = call_args[0]
        assert payload["target_pct"] == 40

    @pytest.mark.asyncio
    async def test_input_tokens_passed_to_chain(self, chain_with_mock_llm: SummarizationChain) -> None:
        await chain_with_mock_llm.summarise(content="text", input_tokens=123)
        call_args, _ = chain_with_mock_llm._chain.ainvoke.call_args
        payload = call_args[0]
        assert payload["input_tokens"] == 123
