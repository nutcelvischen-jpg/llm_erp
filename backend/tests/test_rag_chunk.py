from backend.app.rag.chunk import OVERLAP, TABLE_MAX, TEXT_TARGET, chunk_blocks, doc_type_of, split_table, split_text
from backend.app.rag.parse import Block


def B(text, kind="text", page=1, path=("第一條",), fn="銷售合約_甲.pdf"):
    return Block("d1", fn, page, list(path), kind, text)


def sents(n):
    return "".join(f"這是第{i:03d}句，內容用來測試切塊與重疊。" for i in range(n))


def test_short_block_single_chunk_with_prefix():
    c = chunk_blocks([B("交期為 30 日。")])
    assert len(c) == 1
    assert c[0].text == "【銷售合約_甲.pdf › 第一條】\n交期為 30 日。"
    assert (c[0].chunk_id, c[0].doc_type, c[0].page, c[0].kind) == ("d1-000", "合約", 1, "text")


def test_long_text_split_with_overlap_and_no_loss():
    t = sents(120)  # 約 2400+ 字
    parts = split_text(t)
    assert len(parts) >= 4
    assert all(len(p) <= TEXT_TARGET + OVERLAP + 40 for p in parts)
    for a, b in zip(parts, parts[1:]):
        assert a[-OVERLAP:][-30:] in b[: OVERLAP + 40]  # 後一塊開頭含前一塊結尾
    for i in range(120):  # 每一句都出現在某一塊
        assert f"第{i:03d}句" in "".join(parts)


def test_no_punctuation_hard_split():
    parts = split_text("甲" * 2000)
    assert len(parts) >= 3 and "".join(parts).count("甲") >= 2000


def test_table_kept_whole():
    md = "| a | b |\n|---|---|\n" + "\n".join(f"| {i} | x |" for i in range(20))
    c = chunk_blocks([B(md, kind="table", page=5)])
    assert len(c) == 1 and c[0].kind == "table" and c[0].page == 5 and md in c[0].text


def test_big_table_split_by_rows_repeat_header():
    head = "| 料號 | 品名 |\n|---|---|"
    rows = [f"| SKU-{i:04d} | {'品名' * 20} |" for i in range(80)]
    parts = split_table(head + "\n" + "\n".join(rows))
    assert len(parts) >= 2 and all(len(p) <= TABLE_MAX + 100 for p in parts)
    assert all(p.startswith(head) for p in parts)
    joined = "\n".join(parts)
    assert all(r in joined for r in rows)


def test_ids_sequential_per_doc_and_doc_types():
    bl = [B("甲" * 10), B("乙" * 10, page=2), Block("d2", "SOP_請假.pdf", 1, [], "text", "內文")]
    c = chunk_blocks(bl)
    assert [x.chunk_id for x in c] == ["d1-000", "d1-001", "d2-000"]
    assert c[2].text.startswith("【SOP_請假.pdf】\n")
    assert [doc_type_of(n) for n in ("採購合約_a", "規格書_b", "人資_c", "SOP_d", "其他.pdf")] == ["合約", "規格", "人資", "SOP", "其他"]


def test_empty_block_ignored():
    assert chunk_blocks([B("  \n ")]) == []
