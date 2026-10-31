from backend.app.numcheck import extract_numbers, unsupported_numbers


def test_extract():
    got = extract_numbers("營收 1,234.5 元、毛利率 12.3%、約 1,198 萬、3 億，共五家")
    assert [(v, d) for v, d, _ in got] == [(1234.5, 1), (12.3, 1), (11980000.0, 0), (300000000.0, 0)]


def test_supported_exact_rounding_and_units():
    rows = [["鴻遠機械", 11983456.0, 25.64]]
    assert unsupported_numbers("鴻遠機械營收 11,983,456 元，毛利率 25.6%", rows=rows) == []
    assert unsupported_numbers("約 1,198 萬元", rows=rows) == []
    assert unsupported_numbers("約 1,199 萬元", rows=rows) == ["1,199 萬"]
    assert unsupported_numbers("毛利率 30.1%", rows=rows) == ["30.1"]


def test_years_small_ints_and_texts_allowed():
    assert unsupported_numbers("2025 年第 3 名，12 月", rows=[]) == []
    assert unsupported_numbers("違約金 0.3%，上限 10%", texts=["每逾一日 0.3%，上限 10%"]) == []
    assert unsupported_numbers("違約金 0.5%", texts=["每逾一日 0.3%"]) == ["0.5"]
    assert unsupported_numbers("共 45 筆", rows=[]) == ["45"]


def test_numbers_glued_to_chinese():
    got = extract_numbers("建議採購8,565、合計345.3萬元")
    assert [(v, d) for v, d, _ in got] == [(8565.0, 0), (3453000.0, 1)]
    assert unsupported_numbers("建議採購8,565", rows=[[8565]]) == []


def test_codes_are_not_numbers():
    assert [v for v, _, _ in extract_numbers("FST-M8x30-HEX、BRG-6205-2RS")] == [6205.0, 2.0]


def test_negative_results_matched_by_absolute_value():
    assert unsupported_numbers("毛利比去年同期減少 284,485 元", rows=[[-284485]]) == []
