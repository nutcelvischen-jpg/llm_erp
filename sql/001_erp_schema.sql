CREATE SCHEMA IF NOT EXISTS erp;
SET search_path TO erp;

CREATE TABLE customers (
  customer_id   SERIAL PRIMARY KEY,
  customer_code VARCHAR(20) UNIQUE NOT NULL,
  name          VARCHAR(100) NOT NULL,
  industry      VARCHAR(50),
  region        VARCHAR(20),          -- 北部/中部/南部/海外
  sales_rep     VARCHAR(50),          -- 負責業務
  credit_limit  NUMERIC(14,2) DEFAULT 0,
  created_at    DATE NOT NULL
);

CREATE TABLE suppliers (
  supplier_id   SERIAL PRIMARY KEY,
  supplier_code VARCHAR(20) UNIQUE NOT NULL,
  name          VARCHAR(100) NOT NULL,
  lead_time_days INT DEFAULT 14
);

CREATE TABLE products (
  product_id    SERIAL PRIMARY KEY,
  sku           VARCHAR(30) UNIQUE NOT NULL,
  name          VARCHAR(100) NOT NULL,
  category      VARCHAR(50),          -- 軸承/齒輪/墊片/扣件/客製件
  unit          VARCHAR(10) DEFAULT 'PCS',
  std_cost      NUMERIC(12,2) NOT NULL,
  list_price    NUMERIC(12,2) NOT NULL,
  safety_stock  INT DEFAULT 0,
  supplier_id   INT REFERENCES suppliers(supplier_id),
  is_active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE sales_orders (
  so_id         SERIAL PRIMARY KEY,
  so_no         VARCHAR(20) UNIQUE NOT NULL,
  customer_id   INT NOT NULL REFERENCES customers(customer_id),
  order_date    DATE NOT NULL,
  ship_date     DATE,
  status        VARCHAR(20) NOT NULL  -- 待出貨/已出貨/已結案/取消
);

CREATE TABLE sales_order_lines (
  line_id       SERIAL PRIMARY KEY,
  so_id         INT NOT NULL REFERENCES sales_orders(so_id),
  product_id    INT NOT NULL REFERENCES products(product_id),
  qty           INT NOT NULL,
  unit_price    NUMERIC(12,2) NOT NULL,
  unit_cost     NUMERIC(12,2) NOT NULL
);

CREATE TABLE purchase_orders (
  po_id         SERIAL PRIMARY KEY,
  po_no         VARCHAR(20) UNIQUE NOT NULL,
  supplier_id   INT NOT NULL REFERENCES suppliers(supplier_id),
  order_date    DATE NOT NULL,
  expected_date DATE,
  received_date DATE,
  status        VARCHAR(20) NOT NULL  -- 待交貨/已收貨/取消
);

CREATE TABLE purchase_order_lines (
  line_id       SERIAL PRIMARY KEY,
  po_id         INT NOT NULL REFERENCES purchase_orders(po_id),
  product_id    INT NOT NULL REFERENCES products(product_id),
  qty           INT NOT NULL,
  unit_cost     NUMERIC(12,2) NOT NULL
);

CREATE TABLE inventory (
  product_id    INT PRIMARY KEY REFERENCES products(product_id),
  on_hand       INT NOT NULL DEFAULT 0,
  last_movement DATE
);

CREATE TABLE invoices (
  invoice_id    SERIAL PRIMARY KEY,
  invoice_no    VARCHAR(20) UNIQUE NOT NULL,
  so_id         INT REFERENCES sales_orders(so_id),
  customer_id   INT NOT NULL REFERENCES customers(customer_id),
  invoice_date  DATE NOT NULL,
  due_date      DATE NOT NULL,
  amount        NUMERIC(14,2) NOT NULL,
  paid_amount   NUMERIC(14,2) NOT NULL DEFAULT 0,
  paid_date     DATE
);

CREATE INDEX ON sales_orders(order_date);
CREATE INDEX ON sales_order_lines(so_id);
CREATE INDEX ON invoices(customer_id, due_date);
