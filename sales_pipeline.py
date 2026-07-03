import logging
import os
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_USER = os.getenv("DB_USER", "your_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "your_password")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "sales_pipeline")

N_CUSTOMERS = 2000
N_PRODUCTS = 150
N_ORDERS = 60000
SEED = 42


def generate_sample_data():
    Faker.seed(SEED)
    random.seed(SEED)
    np.random.seed(SEED)
    fake = Faker()

    logger.info("Generating customers...")
    customers = pd.DataFrame({
        "customer_id": range(1, N_CUSTOMERS + 1),
        "customer_name": [fake.name() for _ in range(N_CUSTOMERS)],
        "signup_date": [fake.date_between(start_date="-3y", end_date="-1d") for _ in range(N_CUSTOMERS)],
        "region": np.random.choice(["North", "South", "East", "West"], N_CUSTOMERS),
    })

    logger.info("Generating products...")
    categories = ["Electronics", "Home & Kitchen", "Clothing", "Sports", "Books", "Toys", "Beauty", "Groceries"]
    products = pd.DataFrame({
        "product_id": range(1, N_PRODUCTS + 1),
        "product_name": [
            f"{fake.word().capitalize()} {random.choice(['Pro', 'Max', 'Lite', 'Plus', ''])}".strip()
            for _ in range(N_PRODUCTS)
        ],
        "category": np.random.choice(categories, N_PRODUCTS),
        "unit_price": np.round(np.random.uniform(5, 500, N_PRODUCTS), 2),
    })

    logger.info("Generating sales transactions...")
    date_formats = ["%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"]
    start = datetime(2023, 1, 1)
    rows = []
    for i in range(N_ORDERS):
        cust = random.randint(1, N_CUSTOMERS)
        prod = random.randint(1, N_PRODUCTS)
        qty = random.randint(1, 5)
        order_date = start + timedelta(days=random.randint(0, 900))
        price = products.loc[products.product_id == prod, "unit_price"].values[0]
        revenue = round(price * qty * random.uniform(0.9, 1.0), 2)
        rows.append({
            "order_id": i + 1,
            "customer_id": cust,
            "product_id": prod,
            "order_date": order_date.strftime(random.choice(date_formats)),
            "quantity": qty,
            "revenue": revenue,
        })
    sales = pd.DataFrame(rows)

    sales.loc[sales.sample(frac=0.02, random_state=1).index, "revenue"] = np.nan
    sales.loc[sales.sample(frac=0.01, random_state=2).index, "quantity"] = np.nan
    dupes = sales.sample(frac=0.015, random_state=3)
    sales = pd.concat([sales, dupes], ignore_index=True)

    logger.info("Sample data ready: %d customers, %d products, %d sales rows", len(customers), len(products), len(sales))
    return customers, products, sales


def clean_sales(sales: pd.DataFrame) -> pd.DataFrame:
    n_start = len(sales)

    sales["order_date"] = pd.to_datetime(sales["order_date"], errors="coerce", format="mixed")
    sales = sales.dropna(subset=["order_date"])

    sales = sales.drop_duplicates(subset=["order_id"])

    sales["quantity"] = sales["quantity"].fillna(sales["quantity"].median())
    sales["revenue"] = sales.groupby("product_id")["revenue"].transform(lambda s: s.fillna(s.median()))
    sales = sales.dropna(subset=["revenue"])

    sales["quantity"] = sales["quantity"].astype(int)
    sales["order_date"] = sales["order_date"].dt.date

    logger.info("Cleaned sales data: %d rows -> %d rows", n_start, len(sales))
    return sales


def get_engine():
    url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            logger.info("Connected to MySQL %s", version)
    except SQLAlchemyError:
        logger.exception("Could not connect to MySQL. Check your DB settings at the top of this file.")
        raise
    return engine


def load_to_mysql(customers, products, sales_clean, engine):
    customers.to_sql("customers", engine, if_exists="replace", index=False, chunksize=5000)
    products.to_sql("products", engine, if_exists="replace", index=False, chunksize=5000)
    sales_clean.to_sql("sales", engine, if_exists="replace", index=False, chunksize=5000)
    logger.info("Loaded customers, products, and sales tables into MySQL")


QUERIES = {
    "monthly_revenue": """
        SELECT DATE_FORMAT(order_date, '%Y-%m') AS month,
               ROUND(SUM(revenue), 2) AS total_revenue,
               COUNT(DISTINCT order_id) AS num_orders
        FROM sales
        GROUP BY month
        ORDER BY month;
    """,
    "top_products": """
        SELECT p.product_name, p.category,
               ROUND(SUM(s.revenue), 2) AS total_revenue,
               SUM(s.quantity) AS units_sold
        FROM sales s
        JOIN products p ON s.product_id = p.product_id
        GROUP BY p.product_id, p.product_name, p.category
        ORDER BY total_revenue DESC
        LIMIT 10;
    """,
    "customer_ltv": """
        SELECT c.customer_id, c.customer_name,
               COUNT(DISTINCT s.order_id) AS num_orders,
               ROUND(SUM(s.revenue), 2) AS lifetime_value,
               ROUND(AVG(s.revenue), 2) AS avg_order_value
        FROM sales s
        JOIN customers c ON s.customer_id = c.customer_id
        GROUP BY c.customer_id, c.customer_name
        ORDER BY lifetime_value DESC
        LIMIT 20;
    """,
    "cohort_retention": """
        WITH first_purchase AS (
            SELECT customer_id, MIN(DATE_FORMAT(order_date, '%Y-%m-01')) AS cohort_month
            FROM sales
            GROUP BY customer_id
        ),
        orders_with_cohort AS (
            SELECT s.customer_id, fp.cohort_month,
                   DATE_FORMAT(s.order_date, '%Y-%m-01') AS order_month,
                   TIMESTAMPDIFF(MONTH, fp.cohort_month, DATE_FORMAT(s.order_date, '%Y-%m-01')) AS month_number
            FROM sales s
            JOIN first_purchase fp ON s.customer_id = fp.customer_id
        )
        SELECT cohort_month, month_number, COUNT(DISTINCT customer_id) AS active_customers
        FROM orders_with_cohort
        GROUP BY cohort_month, month_number
        ORDER BY cohort_month, month_number;
    """,
}


def run_analysis(engine):
    for name, query in QUERIES.items():
        logger.info("Running query: %s", name)
        df = pd.read_sql(query, engine)
        print(f"\n=== {name} ===")
        print(df.to_string(index=False))


def main():
    customers, products, sales_raw = generate_sample_data()
    sales_clean = clean_sales(sales_raw)

    engine = get_engine()
    load_to_mysql(customers, products, sales_clean, engine)
    run_analysis(engine)


if __name__ == "__main__":
    main()
