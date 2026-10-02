from unittest.mock import Mock

import pytest

from epub_translator.llm.context import LLMContext
from epub_translator.llm.increasable import Increasable


@pytest.mark.parametrize("first_limit, second_limit", [(8, 32), (32, 8), (None, 32)])
def test_changed_output_limit_does_not_reuse_cached_response(tmp_path, first_limit, second_limit):
    executor = Mock()
    executor.request.side_effect = [
        "First response with a different output budget",
        "New response generated with the requested budget",
        AssertionError("Previously used budgets should be served from cache"),
    ]

    def request(limit):
        with LLMContext(executor, tmp_path, None, Increasable(None), Increasable(None)) as context:
            return context.request("Translate this paragraph", max_tokens=limit)

    first_response = request(first_limit)
    second_response = request(second_limit)
    assert first_response != second_response
    assert request(first_limit) == first_response
    assert request(second_limit) == second_response
