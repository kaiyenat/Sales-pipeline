# Sales Data Pipeline

A simple sales data pipeline built with Python (pandas) and MySQL.

## What it does

1. Generates sample sales data (customers, products, and transactions)
2. Cleans the data with pandas — fixes missing values, removes duplicates, parses dates
3. Loads the cleaned data into MySQL
4. Runs SQL queries to answer business questions:
   - Monthly revenue trend
   - Top 10 products by revenue
   - Customer lifetime value
   - Cohort retention (do customers keep buying after their first purchase?)
5. Prints the results

## Setup

Install the required packages:

pip install pandas numpy sqlalchemy pymysql faker

Create a MySQL database:

CREATE DATABASE sales_pipeline;

Open sales_pipeline.py and edit these lines near the top with your MySQL details:

DB_USER = "your_user"
DB_PASSWORD = "your_password"
DB_HOST = "127.0.0.1"
DB_PORT = "3306"
DB_NAME = "sales_pipeline"

## Run it

python sales_pipeline.py

This will generate the sample data, clean it, load it into MySQL, and print the query results to the screen.
