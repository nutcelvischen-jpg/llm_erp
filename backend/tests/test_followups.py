from backend.app.agent.followups import MAX_FOLLOWUPS, doc_names, suggest

DOCS = frozenset({"銷售合約_鴻遠機械", "銷售合約_台陽科技", "採購合約_精密熱處理", "規格書_GEAR-M2-40T", "SOP_客訴處理作業程序"})


def s(question="q", route="sql", mode="template", template_id=None, binds=None, columns=(), rows=(),
      params_readable=(), sources=(), error=None):
    return suggest(question, route=route, mode=mode, template_id=template_id, binds=binds or {}, columns=list(columns),
                   rows=[list(r) for r in rows], params_readable=list(params_readable), sources=list(sources),
                   error=error, docs=DOCS)


def test_customer_trend_suggests_contract_only_when_pdf_exists():
    qs = s(template_id="sales_trend", binds={"customer": "鴻遠機械"}, columns=["月份", "營收"], rows=[["2026-01", 1]])
    assert "鴻遠機械的合約，年度採購多少可以拿到折讓？" in qs
    qs = s(template_id="sales_trend", binds={"customer": "大興企業"}, columns=["月份", "營收"], rows=[["2026-01", 1]])
    assert qs and not any("合約" in q for q in qs)


def test_compare_by_customer_uses_first_real_row():
    qs = s(template_id="sales_compare", columns=["對象", "增減"], rows=[["（全公司）", 1], ["鴻遠機械", -2]],
           params_readable=["比較對象：客戶"])
    assert qs[0] == "鴻遠機械最近 12 個月每個月的營收"
    qs = s(template_id="sales_compare", columns=["對象", "增減"], rows=[["（全公司）", 1], ["陳怡君", -2]],
           params_readable=["比較對象：業務"])
    assert not any("陳怡君" in q for q in qs)


def test_ar_invoices_suggests_stop_shipment_clause():
    qs = s(template_id="ar_invoices", binds={"customer": "台陽科技"}, columns=["發票號碼"], rows=[["INV1"]])
    assert qs[0].startswith("依合約，台陽科技逾期多久")


def test_shortage_picks_supplier_with_contract():
    qs = s(template_id="stock_shortage", columns=["料號", "供應商"],
           rows=[["FST", "順發五金"], ["GEAR-M2-40T", "精密熱處理"]])
    assert qs[0] == "精密熱處理依合約延遲交貨，我們可以怎麼扣款？"


def test_docs_answer_links_back_to_erp():
    qs = s(route="docs", mode=None, sources=[{"file_name": "銷售合約_台陽科技.pdf"}, {"file_name": "規格書_GEAR-M2-40T.pdf"}])
    assert qs == ["台陽科技今年營收多少？", "台陽科技有哪些發票逾期？", "GEAR-M2-40T目前庫存多少？"]
    assert s(route="docs", mode=None, sources=[{"file_name": "SOP_客訴處理作業程序.pdf"}]) == []


def test_no_followups_for_non_answers_and_dedupes_question():
    for mode in ("clarify", "confirm", "no_match", "error"):
        assert s(template_id="ar_aging", mode=mode, columns=["帳齡"], rows=[["未到期"]]) == []
    assert s(route="chat", mode=None) == []
    assert s(template_id="ar_aging", columns=["帳齡"], rows=[["未到期"]], error="x") == []
    assert s(template_id="stock_shortage", columns=["料號"], rows=[]) == []
    qs = s("應收帳款的帳齡分佈", template_id="ar_by_customer", columns=["客戶名稱"], rows=[["精興金屬"]])
    assert "應收帳款的帳齡分佈" not in qs and len(qs) <= MAX_FOLLOWUPS


def test_every_template_gives_at_most_three():
    from backend.app.catalog.registry import TEMPLATES
    for tid in TEMPLATES:
        qs = s(template_id=tid, binds={"customer": "鴻遠機械", "sku": "GEAR-M2-40T"},
               columns=["客戶名稱", "料號", "供應商"], rows=[["鴻遠機械", "GEAR-M2-40T", "精密熱處理"]])
        assert len(qs) <= MAX_FOLLOWUPS and len(set(qs)) == len(qs), tid


def test_real_doc_folder_is_found():
    assert "銷售合約_鴻遠機械" in doc_names()
