from novelforge.core.utils import extract_json


def test_extract_json_recovers_first_valid_object_before_model_commentary() -> None:
    response = '{"content":"usable prose"}\nModel note: completed.\n{"extra":true}'

    assert extract_json(response) == {"content": "usable prose"}


def test_extract_json_recovers_a_valid_array_from_surrounding_text() -> None:
    response = 'Here is the payload: [{"id": 1}, {"id": 2}] trailing explanation'

    assert extract_json(response) == [{"id": 1}, {"id": 2}]
