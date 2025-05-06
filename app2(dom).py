import os
from datetime import datetime
import gridfs
from flask import Flask, request, session, jsonify, render_template, redirect, flash, url_for
from flask_login import UserMixin, login_user, LoginManager, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, FileField
from wtforms.validators import InputRequired, Length, ValidationError, DataRequired, Email
from pymongo import MongoClient
from bson import ObjectId
from flask_socketio import SocketIO, send, emit, join_room, leave_room 
  
app = Flask(__name__)
app.config['SECRET_KEY'] = 'sigmatauphigamma'
CORS(app, supports_credentials=True)
bcrypt = Bcrypt(app)

# MongoDB setup
MONGO_URI = "mongodb+srv://adminuser:Adminuser@cluster0.l5edo4g.mongodb.net/webwork?retryWrites=true&w=majority&appName=Cluster0"  
client = MongoClient(MONGO_URI)
db = client['webwork']  #
users_collection = db['users']
posts_collection = db['posts']
messages_collection = db['messages']  # Added messages collection
businesses_collection = db['businesses']
fs = gridfs.GridFS(db)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Helper for file upload
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class MongoUser(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if user:
        return MongoUser(id=str(user['_id']), username=user['username'])
    return None

# Register form and Login form
class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()], render_kw={"placeholder": "Email"})
    username = StringField(validators=[InputRequired(), Length(min=4, max=20)], render_kw={"placeholder": "Username"})
    password = PasswordField(validators=[InputRequired(), Length(min=8, max=20)], render_kw={"placeholder": "Password"})
    submit = SubmitField("Register")

    def validate_username(self, username):
        existing_user = users_collection.find_one({'username': username.data})
        if existing_user:
            raise ValidationError("Username already exists. Please choose a different one.")

class LoginForm(FlaskForm):
    username = StringField(validators=[InputRequired(), Length(min=4, max=20)], render_kw={"placeholder": "Username"})
    password = PasswordField(validators=[DataRequired(), InputRequired(), Length(min=8, max=20)], render_kw={"placeholder": "Password"})
    submit = SubmitField("Login")

# Profile Creation Form
class CreateProfileForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    gender = SelectField('Gender', choices=[
        ('Male', 'Male'), 
        ('Female', 'Female'), 
        ('Other', 'Other')
    ], validators=[DataRequired()])
    country = StringField('Country', validators=[DataRequired()])
    business = SelectField('Business', choices=[
        ('Student', 'Student'),
        ('Freelancer', 'Freelancer'),
        ('Business Owner', 'Business Owner'),
        ('Employee', 'Employee'),
        ('Other', 'Other')
    ], validators=[DataRequired()])
    time_zone = SelectField('Time Zone', choices=[
        ('UTC+8', 'UTC+8 (Philippines)'), 
        ('UTC-5', 'UTC-5 (US Eastern)'), 
        ('Other', 'Other')
    ], validators=[DataRequired()])
    submit = SubmitField('Next')

# Business Setup Form
class BusinessSetupForm(FlaskForm):
    business_name = StringField('Business Name', validators=[DataRequired()])
    business_type = SelectField('Type of Business', choices=[
        ('Construction', 'Construction'),
        ('Beauty', 'Beauty'),
        ('Food', 'Food'),
        ('Education', 'Education'),
        ('Healthcare', 'Healthcare'),
        ('Technology', 'Technology'),
        ('Other', 'Other')
    ], validators=[DataRequired()])
    country = StringField('Country of Origin', validators=[DataRequired()])
    location = StringField('Location', validators=[DataRequired()])
    submit = SubmitField('Next')

class BusinessProfileForm(FlaskForm):
    profile_picture = FileField('Business Profile Picture', validators=[DataRequired()])
    bio = StringField('Business Bio', validators=[DataRequired()])
    submit = SubmitField('Finish Setup')


# Profile Creation Route
@app.route('/create_profile', methods=['GET', 'POST'])
@login_required
def create_profile():
    form = CreateProfileForm()

    if form.validate_on_submit():
        first_name = form.first_name.data
        last_name = form.last_name.data
        gender = form.gender.data
        country = form.country.data
        business = form.business.data
        time_zone = form.time_zone.data

        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {
                'first_name': first_name,
                'last_name': last_name,
                'gender': gender,
                'country': country,
                'business': business,
                'time_zone': time_zone,
            }}
        )
        return redirect(url_for('upload_profile_picture'))

    return render_template('create_profile.html', form=form)

@app.route('/upload_profile_picture', methods=['GET', 'POST'])
@login_required
def upload_profile_picture():
    if request.method == 'POST':
        biography = request.form['biography']
        profile_picture_file = request.files['profile_picture']
        cover_photo_file = request.files.get('cover_photo')  # Use .get() because cover_photo is optional

        updates = {'biography': biography}

        # Handle profile picture upload
        if profile_picture_file and allowed_file(profile_picture_file.filename):
            profile_filename = secure_filename(profile_picture_file.filename)
            profile_file_id = fs.put(profile_picture_file, filename=profile_filename, content_type=profile_picture_file.content_type)
            profile_file_url = f"/file/{profile_file_id}"
            updates['profile_picture'] = profile_file_url
        else:
            return "Invalid profile picture file type.", 400

        # Handle cover photo upload (optional)
        if cover_photo_file and allowed_file(cover_photo_file.filename):
            cover_filename = secure_filename(cover_photo_file.filename)
            cover_file_id = fs.put(cover_photo_file, filename=cover_filename, content_type=cover_photo_file.content_type)
            cover_file_url = f"/file/{cover_file_id}"
            updates['cover_photo'] = cover_file_url

        # Update the user's profile
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': updates}
        )

        return redirect(url_for('dashboard'))

    return render_template('upload_profile_picture.html')

# Route to serve files from GridFS
@app.route('/file/<file_id>')
def get_file(file_id):
    # Retrieve the file from GridFS
    file = fs.get(ObjectId(file_id))
    return file.read(), 200, {'Content-Type': file.content_type}

# Business setup step 1
@app.route('/add_business', methods=['GET', 'POST'])
@login_required
def add_business():
    form = BusinessSetupForm()
    if form.validate_on_submit():
        business_data = {
            'business_name': form.business_name.data,
            'business_type': form.business_type.data,
            'country': form.country.data,
            'location': form.location.data,
        }
        for key, value in business_data.items():
            session[key] = value
        return redirect(url_for('upload_business_profile'))
    return render_template('add_business.html', form=form)

# Business setup step 2
@app.route('/upload_business_profile', methods=['GET', 'POST'])
@login_required
def upload_business_profile():
    if request.method == 'POST':
        profile_picture_file = request.files.get('business_logo')  
        bio = request.form.get('business_bio')  

        if profile_picture_file and allowed_file(profile_picture_file.filename):
            filename = secure_filename(profile_picture_file.filename)
            file_id = fs.put(profile_picture_file, filename=filename, content_type=profile_picture_file.content_type)
            profile_picture_url = f"/file/{file_id}"

            businesses_collection.insert_one({
                'owner_id': current_user.id,
                'business_name': session.get('business_name'),
                'business_type': session.get('business_type'),
                'country': session.get('country'),
                'location': session.get('location'),
                'profile_picture': profile_picture_url,
                'bio': bio
            })

            session.pop('business_name', None)
            session.pop('business_type', None)
            session.pop('country', None)
            session.pop('location', None)

            session.modified = True

            return redirect(url_for('business_dashboard'))

        else:
            flash('Invalid file uploaded.', 'danger')

    return render_template('upload_business_profile.html')

# Create post route
@app.route('/create-post', methods=['POST'])
@login_required
def create_post():
    content = request.form.get('content')
    files = request.files.getlist('image')

    media_urls = []
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_id = fs.put(file, filename=filename, content_type=file.content_type)
            media_urls.append(f"/file/{file_id}")  # GridFS URL

    post = {
        'content': content,
        'media': media_urls,
        'user_id': current_user.id,
        'username': current_user.username,
        'created_at': datetime.utcnow()
    }
    posts_collection.insert_one(post)

    return jsonify({'message': 'Post created successfully!'}), 201


# Get posts route
@app.route('/posts', methods=['GET'])
def get_posts():
    posts_cursor = posts_collection.find().sort('created_at', -1)

    result = []
    for post in posts_cursor:
        result.append({
            'id': str(post['_id']),
            'content': post.get('content'),
            'media': post.get('media', []),
            'username': post.get('username'),
            'created_at': post.get('created_at')
        })

    return jsonify(result)

# Dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    
    # Get user's posts
    posts_cursor = posts_collection.find({'user_id': current_user.id})
    posts = list(posts_cursor)

    # Get user's businesses
    businesses_cursor = businesses_collection.find({'owner_id': current_user.id})
    businesses = list(businesses_cursor)

    return render_template('dashboard.html', user=user, posts=posts, businesses=businesses)


# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        users_collection.insert_one({
            'email': form.email.data,
            'username': form.username.data,
            'password': hashed_pw
        })
        flash("Account created. Complete your profile.")
        return redirect(url_for('create_profile'))  # Direct to profile creation

    return render_template("register.html", form=form)

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        user = users_collection.find_one({'username': form.username.data})

        if user and bcrypt.check_password_hash(user['password'], form.password.data):
            user_obj = MongoUser(id=str(user['_id']), username=user['username'])
            login_user(user_obj)

            if 'first_name' in user and 'last_name' in user:
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('create_profile'))

        else:
            flash("Invalid username or password.")

    return render_template("login.html", form=form)

# Logout route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Home route
@app.route('/')
def home():
    return render_template("home.html")

# edit profile
@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})

    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        gender = request.form.get('gender')
        country = request.form.get('country')
        business = request.form.get('business')
        time_zone = request.form.get('time_zone')

        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {
                'first_name': first_name,
                'last_name': last_name,
                'gender': gender,
                'country': country,
                'business': business,
                'time_zone': time_zone
            }}
        )
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('edit_profile.html', user=user)

# business dashboard route
@app.route('/business_dashboard')
@login_required
def business_dashboard():
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    business = businesses_collection.find_one({'owner_id': current_user.id})
    
    return render_template('business_dashboard.html', user=user, business=business)

# start of messaging website also imput new import for socketio
@app.route('/messaging')
def messaging():
    return render_template('messaging.html')


# messaging website route gives profile on the sidebar
@app.route('/get_user_profile', methods=['GET'])
@login_required
def get_user_profile():
    user_data = users_collection.find_one({"_id": ObjectId(current_user.id)})
    
    if user_data:
        user_profile = {
            "profile_picture": user_data.get("profile_picture", "/static/default-profile.png"),
        }
        return jsonify(user_profile)
    else:
        return jsonify({"error": "User not found"}), 404

# handles adding the contact in messaging page
@app.route('/add_contact', methods=['POST'])
@login_required
def add_contact():
    data = request.get_json()
    username = data.get('username')

    if not username:
        return jsonify({'success': False, 'message': 'Username is required.'}), 400

    # Find the user to add
    target_user = users_collection.find_one({'email': username})  # or 'username': username
    if not target_user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    if str(target_user['_id']) == current_user.id:
        return jsonify({'success': False, 'message': "You can't add yourself."}), 400

    # Check if already added
    current_user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
    if 'contacts' in current_user_doc and str(target_user['_id']) in current_user_doc['contacts']:
        return jsonify({'success': False, 'message': 'User already in contacts.'}), 400

    # Add the user ID to current user's contacts
    users_collection.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$addToSet': {'contacts': str(target_user['_id'])}}  # prevents duplicates
    )

    return jsonify({'success': True}), 200


@app.route('/get_contacts', methods=['GET'])
@login_required
def get_contacts():
    # Fetch the user's document from the database
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    
    # If user doesn't exist or doesn't have contacts, return an empty list
    if not user or 'contacts' not in user:
        return jsonify({'contacts': []})

    # Fetch the list of contact IDs from the user's document
    contact_ids = user.get('contacts', [])
    contacts = []

    # Iterate over each contact ID to get detailed information
    for contact_data in contact_ids:
        # Fetch the contact document for each contact
        contact = users_collection.find_one({'_id': ObjectId(contact_data)})

        if contact:
            # Append contact details to the contacts list
            contacts.append({
                'contact_id': str(contact['_id']),  # Ensure the ID is a string for easy use in the frontend
                'username': contact.get('username'),
                'email': contact.get('email'),
                'profile_picture': contact.get('profile_picture', '/static/default-profile.png'),
                'is_pinned': contact_data.get('is_pinned', False)  # Include pin status
            })

    # Sort contacts: pinned contacts should appear first
    sorted_contacts = sorted(contacts, key=lambda x: x['is_pinned'], reverse=True)

    # Return the sorted list of contacts
    return jsonify({'contacts': sorted_contacts})

@app.route('/pin_contact', methods=['POST'])
@login_required
def pin_contact():
    data = request.get_json()  # Get the contact data
    contact_id = data.get('contact_id')  # The ID of the contact to be pinned
    is_pinned = data.get('is_pinned')  # The new pin status

    if not contact_id:
        return jsonify({'success': False, 'message': 'Contact ID is required.'}), 400

    # Find the user's contact list
    current_user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})

    if 'contacts' not in current_user_doc:
        return jsonify({'success': False, 'message': 'No contacts found.'}), 404

    # Update the pin status of the contact in the user's contact list
    updated = users_collection.update_one(
        {'_id': ObjectId(current_user.id), 'contacts.contact_id': ObjectId(contact_id)},
        {'$set': {'contacts.$.is_pinned': is_pinned}}  # Update the is_pinned status
    )

    if updated.matched_count > 0:
        return jsonify({'success': True, 'message': 'Pin status updated successfully.'}), 200
    else:
        return jsonify({'success': False, 'message': 'Contact not found.'}), 404

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    # Get data from the request
    data = request.get_json()
    sender_id = current_user.id
    recipient_id = data.get('recipient')
    message_content = data.get('message')

    if not message_content or not recipient_id:
        return jsonify({"error": "Invalid input"}), 400

    # Get current timestamp
    timestamp = datetime.utcnow()

    # Save the message to the database for both sender and recipient
    message = {
        "sender": sender_id,
        "recipient": recipient_id,
        "message": message_content,
        "timestamp": timestamp
    }

    # Save to sender's and recipient's message collection
    messages_collection.insert_one(message)

    # Also save a duplicate for the recipient to ensure both can view the conversation
    message_for_recipient = {
        "sender": sender_id,
        "recipient": recipient_id,
        "message": message_content,
        "timestamp": timestamp
    }
    messages_collection.insert_one(message_for_recipient)

    # Optionally, return the message details in the response
    return jsonify({
        "sender": sender_id,
        "recipient": recipient_id,
        "message": message_content,
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S")
    }), 200

@app.route('/get_messages', methods=['GET'])
@login_required
def get_messages():
    user_id = current_user.id
    # Get messages for the logged-in user
    messages_cursor = messages_collection.find(
        {"$or": [{"sender": user_id}, {"recipient": user_id}]}
    ).sort('timestamp', 1)  # Sort by timestamp ascending

    messages = []
    for message in messages_cursor:
        messages.append({
            "sender": message["sender"],
            "recipient": message["recipient"],
            "message": message["message"],
            "timestamp": message["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        })

    return jsonify({"messages": messages})

if __name__ == '__main__':
    app.run(debug=True)
