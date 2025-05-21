import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import re, os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# MSSQL database credentials
DB_CONFIG = {
    'server': os.getenv("DB_SERVER"),
    'database': os.getenv("DB_NAME"),
    'username': os.getenv("DB_USERNAME"),
    'password': os.getenv("DB_PASSWORD"),
    'driver': os.getenv("DRIVER")  
}

def get_db_engine():
    conn_str = f"mssql+pyodbc://{DB_CONFIG['username']}:{DB_CONFIG['password']}@{DB_CONFIG['server']}/{DB_CONFIG['database']}?driver={DB_CONFIG['driver']}"
    return create_engine(conn_str)

def to_snake_case(name):
    name = re.sub(r'[\s-]+', '_', name)
    name = re.sub(r'_+', '_', name)
    return name.lower()

def fetch_table_names(engine, department, selected_department=None):
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT table_name 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'dbo'
            """)
            result = conn.execute(query)
            all_tables = sorted([row[0] for row in result])

            if department == "IT" and not selected_department:
                return all_tables

            target_dept = selected_department if department == "IT" and selected_department else department

            mapping_query = text("""
                SELECT tables_mapped 
                FROM [SyngentaNICEProjectBungoma].dbo.user_mapping 
                WHERE category = :dept
            """)
            result = conn.execute(mapping_query, {"dept": target_dept.upper()})
            allowed_tables = [row[0].strip() for row in result]

            filtered_tables = [table for table in all_tables if table in allowed_tables]
            return sorted(filtered_tables) if filtered_tables else []
    except Exception as e:
        st.error(f"Error fetching table names: {e}")
        return []

def fetch_departments(engine):
    try:
        with engine.connect() as conn:
            dept_query = text("SELECT DISTINCT category FROM [SyngentaNICEProjectBungoma].dbo.user_mapping")
            result = conn.execute(dept_query)
            departments = [row[0] for row in result if row[0]]
            return sorted(departments)
    except Exception as e:
        st.error(f"Error fetching departments: {e}")
        return []

def match_columns_to_table(df, selected_table, engine):
    try:
        # Get database column names
        with engine.connect() as conn:
            query = text(f"SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = :table AND TABLE_SCHEMA = 'dbo'")
            result = conn.execute(query, {"table": selected_table})
            db_columns = [row[0] for row in result]
            db_columns_lower = [col.lower() for col in db_columns]

        # Clean DataFrame column names
        original_columns = df.columns
        cleaned_columns = [to_snake_case(col) for col in original_columns]
        df.columns = cleaned_columns

        # Map DataFrame columns to database columns
        column_mapping = {}
        for df_col in df.columns:
            df_col_lower = df_col.lower()
            for db_col in db_columns:
                if df_col_lower == to_snake_case(db_col).lower():
                    column_mapping[df_col] = db_col
                    break

        valid_columns = list(column_mapping.keys())
        missing_cols = [col for col in df.columns if col not in valid_columns]

        # Debug output
        #st.write(f"Database columns: {db_columns}")
        #st.write(f"Cleaned DataFrame columns: {df.columns.tolist()}")
        #st.write(f"Column mapping: {column_mapping}")
        st.write(f"Missing columns: {missing_cols}")

        if missing_cols:
            missing_original = [original_columns[df.columns.get_loc(col)] for col in missing_cols]
            st.error(f"\U0001F6AB These columns in your file do not exist in the table '{selected_table}': {', '.join(missing_original)}")
            st.info("Please download the template from the 'Download Template' tab to ensure correct columns.")
            return None, None

        if not valid_columns:
            st.error(f"\U0001F6AB No columns in your file match the table '{selected_table}'.")
            st.info("Please download the template from the 'Download Template' tab to ensure correct columns.")
            return None, None

        # Select only valid columns and rename to database column names
        df = df[valid_columns]
        df.columns = [column_mapping[col] for col in df.columns]
        return df, db_columns
    except Exception as e:
        st.error(f"Error matching columns: {e}")
        return None, None

def has_department_column(engine, table_name):
    try:
        with engine.connect() as conn:
            query = text(f"SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = :table AND TABLE_SCHEMA = 'dbo' AND COLUMN_NAME = 'department'")
            result = conn.execute(query, {"table": table_name})
            return bool(result.fetchone())
    except Exception as e:
        st.error(f"Error checking for department column: {e}")
        return False

def update_user_mapping(engine, department, new_table):
    try:
        dept_id = department
        category = department.upper()
        with engine.begin() as conn:
            insert_query = text("""
                INSERT INTO [SyngentaNICEProjectBungoma].dbo.user_mapping (department_id, category, tables_mapped)
                VALUES (:dept_id, :category, :tables)
            """)
            conn.execute(insert_query, {
                "dept_id": dept_id,
                "category": category,
                "tables": new_table
            })
    except Exception as e:
        st.error(f"Failed to insert into user_mapping: {str(e)}")
        raise

def data_page():
    if 'logged_in' not in st.session_state or not st.session_state['logged_in'] or 'department' not in st.session_state:
        st.error("Please log in to access this page.")
        st.session_state['logged_in'] = False
        st.rerun()
        return

    st.title("Busia Data Management")
    st.write(f"Welcome, {st.session_state['username']}! (Department: {st.session_state['department']})")

    if st.button("Logout"):
        st.session_state['logged_in'] = False
        st.session_state.pop('department', None)
        st.session_state.pop('username', None)
        st.rerun()

    engine = get_db_engine()
    department = st.session_state['department']
    tabs = st.tabs(["Download Template", "Upload Data", "Create New Table", "Form Uploads"])

    with tabs[0]:
        st.subheader("Preview of the selected table:")
        table_names = fetch_table_names(engine, department)
        # Filter out 'users' and 'user_mapping' tables
        table_names = [table for table in table_names if table.lower() not in ["users", "user_mapping"]]
        selected_table = st.selectbox("Select table:", [""] + table_names, key="download_select")
        if selected_table:
            with engine.connect() as conn:
                has_dept = has_department_column(engine, selected_table)
                if has_dept and department != "IT":
                    query = text(f"SELECT TOP 5 * FROM [dbo].[{selected_table}] WHERE CAST(department AS NVARCHAR(MAX)) = :dept")
                    result = conn.execute(query, {"dept": department})
                else:
                    query = text(f"SELECT TOP 5 * FROM [dbo].[{selected_table}]")
                    result = conn.execute(query)

                df = pd.DataFrame(result.fetchall(), columns=result.keys())
                if df.empty:
                    st.info("No data available in this table.")
                else:
                    st.write(df)

                    df['created_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    df['created_by'] = st.session_state['username']
                    if has_dept:
                        df['department'] = department
                    download_csv = df.to_csv(index=False).encode()
                    st.download_button("Download CSV Template", download_csv, f"{selected_table}_template.csv", "text/csv")
        else:
            st.info("Please select a table to preview.")

    with tabs[1]:
        st.subheader("Upload Data")
        st.text("Please select your file to start the upload process")

        if 'clicked' not in st.session_state:
            st.session_state.clicked = False

        selected_department = None
        if department == "IT":
            departments = fetch_departments(engine)
            if departments:
                selected_department = st.selectbox(
                    "Select department to upload data for:",
                    [""] + departments,
                    key="upload_dept_select"
                )
            else:
                st.warning("No departments found in user_mapping.")
                st.session_state.clicked = False

        if not department == "IT" or (department == "IT" and selected_department):
            if st.button('Upload File'):
                st.session_state.clicked = True

            uploaded_file = st.file_uploader("Choose a file", type=['csv', 'xlsx']) if st.session_state.clicked else None
            if uploaded_file:
                if uploaded_file.type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                    df = pd.read_excel(uploaded_file)
                else:
                    df = pd.read_csv(uploaded_file)

                target_dept = selected_department if department == "IT" else department
                table_names = fetch_table_names(engine, department, selected_department)
                selected_table = st.selectbox("Select table to insert into:", [""] + table_names, key="upload_select")
                if selected_table:
                    df, db_columns = match_columns_to_table(df, selected_table, engine)
                    if df is None:
                        st.stop()

                    df = df.astype(str).fillna(' ')
                    df['created_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    df['created_by'] = st.session_state['username']
                    if has_department_column(engine, selected_table):
                        df['department'] = target_dept
                    st.write(df.head())

                    if st.button("Submit"):
                        connection = engine.raw_connection()
                        cursor = None
                        progress_bar = st.progress(0)
                        try:
                            cursor = connection.cursor()
                            total_rows = len(df)
                            for idx, row in df.iterrows():
                                row = row.apply(lambda x: '' if str(x).lower() == 'nan' else x)
                                columns = ', '.join([f"[{col}]" for col in row.index if col in db_columns])
                                values = ', '.join(['?'] * len(row.index))
                                query = f"INSERT INTO [dbo].[{selected_table}] ({columns}) VALUES ({values})"
                                cursor.execute(query, tuple(row))
                                progress_bar.progress((idx + 1) / total_rows)
                            connection.commit()
                            st.success("\u2705 Records inserted successfully.")
                            st.session_state.clicked = False
                            st.rerun()
                        except Exception as e:
                            connection.rollback()
                            st.error(f"Error inserting records: {e}")
                        finally:
                            if cursor:
                                cursor.close()
                            connection.close()
                            progress_bar.empty()

    with tabs[2]:
        st.subheader("Create a New Table from Data")
        selected_department = None
        if department == "IT":
            departments = fetch_departments(engine)
            if departments:
                selected_department = st.selectbox(
                    "Select department to create table for:",
                    [""] + departments,
                    key="create_dept_select"
                )
            else:
                st.warning("No departments found in user_mapping.")

        if not department == "IT" or (department == "IT" and selected_department):
            uploaded_new_file = st.file_uploader("Choose a file", type=['csv', 'xlsx'], key="new_table_upload")
            if uploaded_new_file:
                if uploaded_new_file.type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                    new_df = pd.read_excel(uploaded_new_file)
                else:
                    new_df = pd.read_csv(uploaded_new_file)

                # Clean column names to snake_case
                original_columns = new_df.columns
                cleaned_columns = [to_snake_case(col) for col in original_columns]
                new_df.columns = cleaned_columns

                new_df = new_df.astype(str).fillna(' ')
                new_df['created_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                new_df['created_by'] = st.session_state['username']
                new_df['department'] = selected_department if department == "IT" else department
                st.write(new_df.head())

                new_table_name = st.text_input("Enter new table name (lowercase, no spaces):", key="new_table_name")
                if new_table_name:
                    mapping_department = selected_department if department == "IT" else department
                    table_names = fetch_table_names(engine, department, selected_department)
                    if new_table_name in table_names:
                        st.error(f"\U0001F6AB There is already an object named '{new_table_name}' in the database.")
                    elif st.button("Create Table and Upload Data"):
                        with st.spinner("Creating table and inserting data..."):
                            progress_bar = st.progress(0)
                            connection = engine.raw_connection()
                            cursor = None
                            try:
                                with engine.begin() as conn:
                                    columns = ", ".join([f"[{col}] TEXT" for col in new_df.columns])
                                    create_sql = text(f"CREATE TABLE [dbo].[{new_table_name}] ({columns})")
                                    conn.execute(create_sql)
                                progress_bar.progress(0.3)

                                total_rows = len(new_df)
                                for idx, (index, row) in enumerate(new_df.iterrows()):
                                    row = row.apply(lambda x: '' if str(x).lower() == 'nan' else x)
                                    columns = ', '.join([f"[{col}]" for col in row.index])
                                    values = ', '.join(['?'] * len(row))
                                    insert_sql = f"INSERT INTO [dbo].[{new_table_name}] ({columns}) VALUES ({values})"
                                    if not cursor:
                                        cursor = connection.cursor()
                                    cursor.execute(insert_sql, tuple(row))
                                    progress_bar.progress(0.3 + 0.7 * (idx + 1) / total_rows)
                                connection.commit()
                                update_user_mapping(engine, mapping_department, new_table_name)
                                if "download_select" in st.session_state:
                                    del st.session_state["download_select"]
                                if "upload_select" in st.session_state:
                                    del st.session_state["upload_select"]
                                st.success(f"\u2705 Table '[dbo].[{new_table_name}]' created, data inserted, and added to user_mapping for {mapping_department}.")
                                st.rerun()
                            except Exception as e:
                                connection.rollback()
                                st.error(f"\u274C Error: {e}")
                            finally:
                                if cursor:
                                    cursor.close()
                                connection.close()
                                progress_bar.empty()

    with tabs[3]:
        st.subheader("Form Uploads")

        # Constants
        topics = ["Food Accessibility", "Overweight", "Stakeholder Food Systems"]
        subcounties = [
            "Bumula", "Kanduyi", "Sirisia", "Kabuchai", "Kimilili",
            "Tongaren", "Webuye West", "Webuye East", "Mt. Elgon"
        ]
        county = "Bungoma"
        county_index = 1

        selected_topic = st.selectbox("Select a topic", topics)

        # -------------------- FOOD ACCESSIBILITY FORM --------------------
        if selected_topic == "Food Accessibility":
            st.subheader("Food Accessibility Input Form")

            st.text_input("County", value=county, disabled=True)
            subcounty = st.selectbox("Subcounty", subcounties)

            num_kiosks = st.number_input("Number of kiosks", min_value=0)
            num_supermarkets = st.number_input("Number of supermarkets", min_value=0)
            num_markets = st.number_input("Number of markets", min_value=0)

            if st.button("Submit Food Accessibility"):
                conn = engine.raw_connection()
                cursor = None
                try:
                    cursor = conn.cursor()
                    insert_query = """
                        INSERT INTO [SyngentaNICEProjectBungoma].dbo.FD_Bungoma_Food_Accessibility 
                        ([County], [Subcounties in Busia], [Number of Kiosks], 
                         [Number of Supermarkets], [Number of Markets], [County Index])
                        VALUES (?, ?, ?, ?, ?, ?)
                    """
                    values = (county, subcounty, num_kiosks, num_supermarkets, num_markets, county_index)
                    cursor.execute(insert_query, values)
                    conn.commit()
                    st.success("✅ Food Accessibility data inserted successfully!")
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ Insert failed: {e}")
                finally:
                    if cursor:
                        cursor.close()
                    conn.close()

        # -------------------- OVERWEIGHT FORM --------------------
        elif selected_topic == "Overweight":
            st.subheader("Overweight Input Form")

            gender_options = {
                "Male": 101,
                "Female": 102
            }

            gender = st.selectbox("Gender", list(gender_options.keys()))
            gender_id = gender_options[gender]

            baseline = st.number_input("Baseline (%)", min_value=0.0, format="%.2f")
            year = st.number_input("Year", min_value=1900, max_value=2100, value=2022)

            if st.button("Submit Overweight"):
                conn = engine.raw_connection()
                cursor = None
                try:
                    cursor = conn.cursor()
                    insert_query = """
                        INSERT INTO [SyngentaNICEProjectBungoma].dbo.Overweight
                        ([GenderID], [baseline], [county_index], [Year])
                        VALUES (?, ?, ?, ?)
                    """
                    values = (gender_id, baseline, county_index, year)
                    cursor.execute(insert_query, values)
                    conn.commit()
                    st.success("✅ Overweight data inserted successfully!")
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ Insert failed: {e}")
                finally:
                    if cursor:
                        cursor.close()
                    conn.close()

        # -------------------- STAKEHOLDER FOOD SYSTEMS FORM --------------------
        elif selected_topic == "Stakeholder Food Systems":
            st.subheader("Stakeholder Food Systems Input Form")

            domain = "Food policies"
            indicator = "Multisectoral platform for food systems - number"

            st.text_input("Domain", value=domain, disabled=True)
            st.text_input("Indicator", value=indicator, disabled=True)
            st.text_input("County", value=county, disabled=True)
            st.text_input("County Index", value=str(county_index), disabled=True)

            groups = ["Women", "Youth", "Civil Society"]
            selected_group = st.selectbox("Group", groups)

            baseline = st.number_input("Baseline", min_value=0.0, format="%.2f", help="Enter the baseline value as a decimal (e.g., 0.34 for 34%)")

            if st.button("Submit Stakeholder Food Systems"):
                conn = engine.raw_connection()
                cursor = None
                try:
                    cursor = conn.cursor()
                    insert_query = """
                        INSERT INTO [SyngentaNICEProjectBungoma].dbo.[bungoma stakeholders food systems]
                        ([Domain], [indicator], [County], [county index], [Groups], [Baseline])
                        VALUES (?, ?, ?, ?, ?, ?)
                    """
                    values = (domain, indicator, county, county_index, selected_group, baseline)
                    cursor.execute(insert_query, values)
                    conn.commit()
                    st.success("✅ Stakeholder Food Systems data inserted successfully!")
                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ Insert failed: {e}")
                finally:
                    if cursor:
                        cursor.close()
                    conn.close()

if __name__ == "__main__":
    data_page()