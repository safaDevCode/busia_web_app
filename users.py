import hashlib
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# DB config from .env
DB_CONFIG = {
    'server': os.getenv("DB_SERVER"),
    'database': os.getenv("DB_NAME"),
    'username': os.getenv("DB_USERNAME"),
    'password': os.getenv("DB_PASSWORD"),
    'driver': os.getenv("DRIVER")
}

# Create DB engine
def get_db_engine():
    connection_string = (
        f"mssql+pyodbc://{DB_CONFIG['username']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['server']}/{DB_CONFIG['database']}?driver={DB_CONFIG['driver']}"
    )
    return create_engine(connection_string)

# Fetch user credentials and department
def fetch_users(engine):
    try:
        with engine.connect() as conn:
            query = text("SELECT username, password, department FROM [SyngentaNICEProjectBusia].dbo.[users]")
            result = conn.execute(query)
            users = {}
            for username, password, department in result:
                hashed_password = hashlib.sha256(password.encode()).hexdigest()
                users[username] = {'password': hashed_password, 'department': department}
            return users
    except Exception as e:
        print(f"Error fetching users: {e}")
        return {}

# Authenticate a user and return department
def authenticate_user(username, password, users):
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()
    user_data = users.get(username)
    if user_data and user_data['password'] == hashed_pw:
        return user_data['department']
    return None

# Initialize
engine = get_db_engine()
USERS = fetch_users(engine)