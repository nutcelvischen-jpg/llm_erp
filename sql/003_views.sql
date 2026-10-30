SET search_path TO erp;

CREATE OR REPLACE VIEW v_銷售明細 AS
SELECT so.so_no AS 訂單編號, so.order_date AS 訂單日期, so.ship_date AS 出貨日期, so.status AS 訂單狀態,
       c.customer_code AS 客戶代號, c.name AS 客戶名稱, c.region AS 客戶區域, c.sales_rep AS 負責業務,
       p.sku AS 料號, p.name AS 品名, p.category AS 產品類別,
       l.qty AS 數量, l.unit_price AS 單價, l.unit_cost AS 單位成本,
       l.qty * l.unit_price AS 銷售金額,
       l.qty * (l.unit_price - l.unit_cost) AS 毛利
FROM sales_order_lines l
JOIN sales_orders so ON so.so_id = l.so_id
JOIN customers c ON c.customer_id = so.customer_id
JOIN products p ON p.product_id = l.product_id
WHERE so.status <> '取消';

CREATE OR REPLACE VIEW v_應收帳款 AS
SELECT i.invoice_no AS 發票號碼, c.customer_code AS 客戶代號, c.name AS 客戶名稱, c.sales_rep AS 負責業務,
       i.invoice_date AS 發票日期, i.due_date AS 到期日, i.amount AS 發票金額, i.paid_amount AS 已收金額,
       i.amount - i.paid_amount AS 未收金額,
       CASE WHEN i.amount - i.paid_amount > 0 AND i.due_date < CURRENT_DATE
            THEN CURRENT_DATE - i.due_date ELSE 0 END AS 逾期天數
FROM invoices i JOIN customers c ON c.customer_id = i.customer_id;

CREATE OR REPLACE VIEW v_庫存狀況 AS
SELECT p.sku AS 料號, p.name AS 品名, p.category AS 產品類別, p.unit AS 單位,
       inv.on_hand AS 現有庫存, p.safety_stock AS 安全庫存, p.std_cost AS 標準成本,
       inv.on_hand * p.std_cost AS 庫存金額,
       inv.last_movement AS 最後異動日, CURRENT_DATE - inv.last_movement AS 未異動天數,
       s.name AS 供應商, s.lead_time_days AS 供應商交期天數,
       COALESCE((SELECT SUM(l.qty) FROM sales_order_lines l JOIN sales_orders so ON so.so_id = l.so_id
                 WHERE l.product_id = p.product_id AND so.status = '待出貨'), 0) AS 待出貨數量,
       COALESCE((SELECT SUM(l.qty) FROM purchase_order_lines l JOIN purchase_orders po ON po.po_id = l.po_id
                 WHERE l.product_id = p.product_id AND po.status = '待交貨'), 0) AS 在途數量
FROM products p
JOIN inventory inv ON inv.product_id = p.product_id
LEFT JOIN suppliers s ON s.supplier_id = p.supplier_id
WHERE p.is_active;

CREATE OR REPLACE VIEW v_採購明細 AS
SELECT po.po_no AS 採購單號, po.order_date AS 採購日期, po.expected_date AS 預計到貨日, po.received_date AS 實際到貨日,
       po.status AS 採購狀態, s.name AS 供應商, p.sku AS 料號, p.name AS 品名, l.qty AS 數量, l.unit_cost AS 單位成本,
       l.qty * l.unit_cost AS 採購金額
FROM purchase_order_lines l
JOIN purchase_orders po ON po.po_id = l.po_id
JOIN suppliers s ON s.supplier_id = po.supplier_id
JOIN products p ON p.product_id = l.product_id;

-- 唯讀角色給 LLM 查詢用：只能 SELECT 這四個 View，不能碰原始表
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'llm_reader') THEN
    CREATE ROLE llm_reader LOGIN PASSWORD 'llm_reader';
  END IF;
END $$;
ALTER ROLE llm_reader SET default_transaction_read_only = on;  -- 多一層保險：連線預設唯讀
ALTER ROLE llm_reader SET statement_timeout = '10s';
ALTER ROLE llm_reader SET search_path = erp;  -- 不帶 erp. 前綴也能找到 View（schema_doc.md 的寫法）
GRANT USAGE ON SCHEMA erp TO llm_reader;
GRANT SELECT ON v_銷售明細, v_應收帳款, v_庫存狀況, v_採購明細 TO llm_reader;
