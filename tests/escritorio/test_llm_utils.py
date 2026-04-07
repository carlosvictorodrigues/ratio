"""Tests for the shared LLM JSON parsing utilities."""

import json

import pytest

from backend.escritorio._llm_utils import (
    coerce_to_long_text,
    coerce_to_string,
    extract_first_json_array,
    extract_first_json_object,
    make_json_response_config,
    parse_json_payload,
    unwrap_envelope,
)


# --- extract_first_json_object ---

def test_extract_first_json_object_basic():
    assert extract_first_json_object('{"a":1}') == '{"a":1}'


def test_extract_first_json_object_with_noise():
    text = 'Here is the result: {"key":"val"} and some trailing text.'
    assert json.loads(extract_first_json_object(text)) == {"key": "val"}


def test_extract_first_json_object_nested():
    text = '{"outer":{"inner":42}}'
    assert json.loads(extract_first_json_object(text)) == {"outer": {"inner": 42}}


def test_extract_first_json_object_with_strings_containing_braces():
    text = '{"msg":"hello { world }"}'
    assert json.loads(extract_first_json_object(text)) == {"msg": "hello { world }"}


def test_extract_first_json_object_returns_none_on_garbage():
    assert extract_first_json_object("no json here") is None


# --- extract_first_json_array ---

def test_extract_first_json_array_basic():
    assert extract_first_json_array("[1,2,3]") == "[1,2,3]"


def test_extract_first_json_array_with_noise():
    text = "Result: [1, 2] extra"
    assert json.loads(extract_first_json_array(text)) == [1, 2]


# --- parse_json_payload ---

def test_parse_json_payload_object_clean():
    data = parse_json_payload('{"a":1}', expect="object")
    assert data == {"a": 1}


def test_parse_json_payload_object_with_fences():
    data = parse_json_payload('```json\n{"a":1}\n```', expect="object")
    assert data == {"a": 1}


def test_parse_json_payload_object_with_trailing_text():
    data = parse_json_payload('{"a":1}\nExtra commentary here.', expect="object")
    assert data == {"a": 1}


def test_parse_json_payload_array_clean():
    data = parse_json_payload('[1, 2]', expect="array")
    assert data == [1, 2]


def test_parse_json_payload_array_with_fences():
    data = parse_json_payload('```json\n[1, 2]\n```', expect="array")
    assert data == [1, 2]


def test_parse_json_payload_object_from_preamble():
    text = "Here is the JSON:\n\n{\"key\": \"value\"}"
    data = parse_json_payload(text, expect="object")
    assert data == {"key": "value"}


def test_parse_json_payload_rejects_wrong_type():
    with pytest.raises(ValueError, match="Esperado objeto"):
        parse_json_payload('"just a string"', expect="object")


def test_make_json_response_config_sets_json_mime_and_http_timeout():
    config = make_json_response_config()

    assert config is not None
    assert getattr(config, "response_mime_type", None) == "application/json"
    http_options = getattr(config, "http_options", None)
    assert http_options is not None
    assert getattr(http_options, "timeout", None) == 45000


# --- unwrap_envelope ---

def test_unwrap_envelope_bare_list():
    data = [1, 2, 3]
    assert unwrap_envelope(data) is data


def test_unwrap_envelope_dict_with_teses_key():
    data = {"teses": [{"id": "t1"}]}
    assert unwrap_envelope(data) == [{"id": "t1"}]


def test_unwrap_envelope_nested():
    data = {"data": {"items": [1, 2]}}
    assert unwrap_envelope(data) == [1, 2]


def test_unwrap_envelope_no_match():
    data = {"unrelated_key": "value", "other": 42}
    assert unwrap_envelope(data) is data


# --- coerce_to_string ---

def test_coerce_to_string_plain_string():
    assert coerce_to_string("hello") == "hello"


def test_coerce_to_string_dict_with_descricao():
    assert coerce_to_string({"descricao": "fato principal", "extra": 1}) == "fato principal"


def test_coerce_to_string_dict_with_date_prefix():
    result = coerce_to_string({"evento": "Inscrição", "data": "21/09/2025"})
    assert "21/09/2025" in result
    assert "Inscrição" in result


def test_coerce_to_string_dict_fallback_joins_values():
    result = coerce_to_string({"a": "foo", "b": "bar"})
    assert "foo" in result
    assert "bar" in result


def test_coerce_to_string_none():
    assert coerce_to_string(None) == ""


def test_coerce_to_string_number():
    assert coerce_to_string(42) == "42"


# --- coerce_to_long_text ---

def test_coerce_to_long_text_string():
    assert coerce_to_long_text("texto simples") == "texto simples"


def test_coerce_to_long_text_list_of_strings():
    result = coerce_to_long_text(["P1", "P2"])
    assert "P1" in result
    assert "P2" in result
    assert "\n\n" in result


def test_coerce_to_long_text_dict_with_conteudo():
    result = coerce_to_long_text({"titulo": "Dos Fatos", "conteudo": "O autor compareceu..."})
    assert result == "O autor compareceu..."


def test_coerce_to_long_text_dict_fallback_preserves_all():
    result = coerce_to_long_text({"fundamento": "art. 186 CC", "argumento": "nexo"})
    assert "art. 186 CC" in result
    assert "nexo" in result
