from app import app, db  # Replace "trial" with your main file's name

with app.app_context():
    db.create_all()
    print("✅ Database and tables created successfully.")
