from backend.app.catalog.entities import EntityIndex, normalize

CUSTOMERS = ["華發實業", "華發精密", "鴻遠機械", "台陽科技", "精興金屬股份有限公司", "億達企業"]
SKUS = ["BRG-6205-2RS", "BRG-6205-ZZ", "GEAR-M2-40T"]
loads = []


def idx():
    def cust():
        loads.append(1)
        return CUSTOMERS
    return EntityIndex({"customer": cust, "sku": lambda: SKUS})


def test_normalize():
    assert normalize("　鴻遠 機械股份有限公司 ") == "鴻遠機械"
    assert normalize("ＢＲＧ－6205") == normalize("brg-6205")


def test_exact():
    m = idx().match("customer", "鴻遠機械")
    assert (m.status, m.value) == ("exact", "鴻遠機械")


def test_omit_company_suffix():
    m = idx().match("customer", "精興金屬")
    assert (m.status, m.value) == ("exact", "精興金屬股份有限公司")
    assert idx().match("customer", "鴻遠機械公司").value == "鴻遠機械"


def test_unique_contains():
    m = idx().match("customer", "鴻遠")
    assert (m.status, m.value) == ("fuzzy", "鴻遠機械")


def test_fuzzy_similarity():
    m = idx().match("customer", "台陽科枝")  # 錯字
    assert (m.status, m.value) == ("fuzzy", "台陽科技")


def test_ambiguous():
    m = idx().match("customer", "華發")
    assert m.status == "ambiguous" and set(m.options) == {"華發實業", "華發精密"}


def test_none_with_suggestions():
    m = idx().match("customer", "大同電子")
    assert m.status == "none" and m.value is None
    assert idx().match("customer", "").status == "none"


def test_sku_case_insensitive():
    assert idx().match("sku", "brg-6205-2rs").value == "BRG-6205-2RS"
    m = idx().match("sku", "brg-6205")
    assert m.status == "ambiguous" and len(m.options) == 2


def test_cache_and_refresh():
    loads.clear()
    i = idx()
    i.match("customer", "鴻遠")
    i.match("customer", "台陽")
    assert len(loads) == 1
    i.refresh()
    i.match("customer", "台陽")
    assert len(loads) == 2
