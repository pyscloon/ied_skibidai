from datetime import datetime, timezone, timedelta
import pytz
import gridfs
from flask import Flask, request, session, jsonify, render_template, redirect, flash, url_for
from flask_login import UserMixin, login_user, LoginManager, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, FileField
from wtforms.validators import InputRequired, Length, ValidationError, DataRequired, Email  
from pymongo import MongoClient, errors
from bson import ObjectId
from flask_socketio import SocketIO, emit, join_room, leave_room

# Initialize flask application
app = Flask(__name__)
app.config['SECRET_KEY'] = 'sigmatauphigamma'
CORS(app, supports_credentials=True) 
bcrypt = Bcrypt(app); """Bcrypt for hashing"""
socketio = SocketIO(app, cors_allowed_origins="*"); """socketIO for real-time communication"""
active_users = {}; """Dictionary to track active users"""

# MongoDB setup
MONGO_URI = "mongodb+srv://adminuser:Adminuser@cluster0.l5edo4g.mongodb.net/webwork?retryWrites=true&w=majority&appName=Cluster0"  
client = MongoClient(MONGO_URI)
db = client['webwork']; """main database"""
users_collection = db['users']
users_collection.create_index('username'); """indec fot username queries"""
users_collection.create_index('email'); """index for email queries"""
posts_collection = db['posts']; """store user posts"""
businesses_collection = db['businesses']; """store business profiles"""
# messages collection with multiple indexes for querying
messages_collection = db['messages']
messages_collection.create_index([('participants', 1), ('timestamp', -1)])
messages_collection.create_index([('sender', 1), ('recipient', 1)])
messages_collection.create_index([('recipient', 1), ('sender', 1)])
messages_collection.create_index([('recipient', 1), ('status', 1)])
messages_collection.create_index('timestamp')
messages_collection.create_index('persisted')
conversations_collection = db['conversations']; """stores conversation metadata"""
conversations_collection.create_index('participants'); '''index for participant queries'''
fs = gridfs.GridFS(db); '''GridFS for file storage'''

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"; '''Route for unauthorized access redirect'''

# Helper for file upload
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi', 'pdf', 'docs'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# checks if a filename has an allowed extension
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# custom user class for flask-login that wraps MongoDB user documents
class MongoUser(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data
        self.id = str(user_data['_id'])
        self.username = user_data.get('username')
        self.email = user_data.get('email')
        self.first_name = user_data.get('first_name', '')
        self.last_name = user_data.get('last_name', '')
        self.business_name = user_data.get('business_name', '')

# required by flask-login to get user ID
    def get_id(self):
        return str(self.user_data['_id'])

# flask-login user loader callback to get user from database
@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if user:
        return MongoUser(user)
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

    def validate_email(self, email):
        existing_email = users_collection.find_one({'email': email.data})
        if existing_email:
            raise ValidationError("Email already in use. Please use a different email or login.")

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

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            # Insert new user and get the ID
            result = users_collection.insert_one({
                'email': form.email.data,
                'username': form.username.data,
                'password': hashed_pw,
                'created_at': datetime.utcnow()
            })
            
            # Immediately log in the new user
            new_user = users_collection.find_one({'_id': result.inserted_id})
            user_obj = MongoUser(new_user)
            login_user(user_obj)
            
            # Store in session
            session['user_id'] = str(result.inserted_id)
            session['username'] = form.username.data
            
            flash("Account created. Complete your profile.")
            return redirect(url_for('create_profile'))
            
        except errors.DuplicateKeyError:
            flash("Email or username already exists.")
            return render_template("register.html", form=form)
    return render_template("register.html", form=form)

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    
    # Clear any existing session when arriving at login page
    if request.method == 'GET':
        session.clear()

    if form.validate_on_submit():
        user = users_collection.find_one({'username': form.username.data})
        
        if user and bcrypt.check_password_hash(user['password'], form.password.data):
            user_obj = MongoUser(user)
            login_user(user_obj)
            
            # Set session variables
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            
            if 'first_name' in user and 'last_name' in user:
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('create_profile'))
        else:
            flash("Invalid username or password.")
    
    return render_template("login.html", form=form)

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

# initialize job collection
jobs_collection = db['jobs']

# display jobs_projects_posting
@app.route('/jobs-projects-posting')  # URL path 
def jobs_projects_posting(): 
        # Get jobs from MongoDB and convert to list
        jobs = list(jobs_collection.find({}, {'_id': 0}))  # Exclude MongoDB _id field
        
        # Debug output
        print(f"Found {len(jobs)} jobs to display")
        
        # Render the template with the correct filename
        return render_template('jobs_projects_posting.html', jobs=jobs)
    # except Exception as e:
    #     print(f"Error loading jobs: {str(e)}")
    #     return render_template('error.html', message="Could not load jobs"), 500
    
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
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'User ID is required.'}), 400

    try:
        # Find the user by ID
        target_user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not target_user:
            return jsonify({'success': False, 'message': 'User not found.'}), 404

        if str(target_user['_id']) == current_user.id:
            return jsonify({'success': False, 'message': "You can't add yourself."}), 400

        # Check if already added
        current_user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
        if 'contacts' in current_user_doc:
            if any(str(contact['contact_id']) == user_id for contact in current_user_doc['contacts']):
                # Return the existing contact data
                existing_contact = next(c for c in current_user_doc['contacts'] if str(c['contact_id']) == user_id)
                return jsonify({
                    'success': False,
                    'message': 'User already in contacts.',
                    'contact': {
                        'user_id': user_id,
                        'name': existing_contact.get('name', ''),
                        'profile_picture': existing_contact.get('profile_picture', '')
                    }
                }), 400

        # Prepare contact data
        contact_data = {
            'contact_id': user_id,
            'is_pinned': False,
            'name': f"{target_user.get('first_name', '')} {target_user.get('last_name', '')}".strip(),
            'profile_picture': target_user.get('profile_picture', ''),
            'username': target_user.get('username', ''),
            'first_name': target_user.get('first_name', ''),
            'last_name': target_user.get('last_name', ''),
            'added_at': datetime.utcnow()
        }

        # Add the user to contacts
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$addToSet': {'contacts': contact_data}}
        )

        return jsonify({
            'success': True,
            'contact': {
                'user_id': user_id,
                'name': contact_data['name'],
                'profile_picture': contact_data['profile_picture'],
                'username': contact_data['username'],
                'first_name': contact_data['first_name'],
                'last_name': contact_data['last_name'],
                'added_at': contact_data['added_at'].isoformat()
            }
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    
# get list fo user not in current user's contacts.
@app.route('/get_available_users')
@login_required
def get_available_users():
    current_user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
    added_contact_ids = {c['contact_id'] for c in current_user_doc.get('contacts', [])}

    available_users = users_collection.find({
        '_id': {'$ne': ObjectId(current_user.id)}
    })

    user_list = []
    for user in available_users:
        if str(user['_id']) not in added_contact_ids:
            user_list.append({
                'user_id': str(user['_id']),
                'username': user['username'],
                'email': user['email'],  # used to add via email
                'profile_picture': user.get('profile_picture')
            })

    return jsonify({'users': user_list}), 200

# Removed duplicate get_contacts route definition
    
# route to messagereq
@app.route('/messagereq')
@login_required
def messagereq():
    # Get current user's contact IDs
    current_user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
    contact_ids = {str(contact['contact_id']) for contact in current_user_doc.get('contacts', [])}

    # Get all distinct users who have sent messages to the current user
    message_senders = messages_collection.distinct('sender', {'recipient': current_user.id})

    pending_users = []
    for sender_id in message_senders:
        sender_id_str = str(sender_id)
        if sender_id_str not in contact_ids and sender_id_str != current_user.id:
            sender = users_collection.find_one({'_id': ObjectId(sender_id)})
            if sender:
                # Find the latest message from this sender
                last_message_doc = messages_collection.find_one(
                    {'sender': sender_id, 'recipient': current_user.id},
                    sort=[('timestamp', -1)]
                )
                pending_users.append({
                    'sender_id': sender_id_str,
                    'name': f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip(),
                    'last_message': last_message_doc.get('content', '') if last_message_doc else '',
                    'profile_picture': sender.get('profile_picture', '/static/default-profile.png')
                })

    # Get contacts list for sidebar
    contacts = []
    for contact in current_user_doc.get('contacts', []):
        contact_user = users_collection.find_one({'_id': ObjectId(contact['contact_id'])})
        if contact_user:
            contacts.append({
                'name': f"{contact_user.get('first_name', '')} {contact_user.get('last_name', '')}".strip(),
                'profile_picture': contact_user.get('profile_picture', '/static/default-profile.png')
            })

    return render_template('messagereq.html', pending_users=pending_users, contacts=contacts)

@app.route('/accept_request', methods=['POST'])
@login_required
def accept_request():
    try:
        data = request.get_json()
        sender_id = data.get('sender_id')

        if not sender_id:
            return jsonify({'success': False, 'message': 'Missing sender ID.'}), 400

        receiver_id = ObjectId(current_user.id)
        sender_id_obj = ObjectId(sender_id)

        sender_doc = users_collection.find_one({'_id': sender_id_obj})
        if not sender_doc:
            return jsonify({'success': False, 'message': 'Sender not found.'}), 404

        # Add sender to current user's (receiver's) contacts
        contact_data = {
            'contact_id': sender_id_obj,
            'name': f"{sender_doc.get('first_name', '')} {sender_doc.get('last_name', '')}".strip(),
            'profile_picture': sender_doc.get('profile_picture', '/static/default-profile.png'),
            'username': sender_doc.get('username', ''),
            'added_at': datetime.utcnow(),
            'is_pinned': False
        }

        users_collection.update_one(
            {'_id': receiver_id},
            {'$addToSet': {'contacts': contact_data}}
        )

        # Optionally delete the request message if you’re storing that separately
        db.message_requests.delete_one({
            'sender_id': sender_id,
            'receiver_id': str(current_user.id)
        })

        return jsonify({'success': True, 'message': 'Request accepted.'})
    except Exception as e:
        print("Error in accept_request:", e)
        return jsonify({'success': False, 'message': 'Internal server error.'}), 500


    
@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    data = request.get_json()
    recipient_id = data.get('recipient')
    content = data.get('message')
    temp_message_id = data.get('temp_message_id')  # Add this line
    
    if not recipient_id or not content:
        return jsonify({"error": "Missing required fields"}), 400

    # Create single message document
    message = {
        "sender": current_user.id,
        "recipient": recipient_id,
        "content": content,
        "timestamp": datetime.utcnow(),
        "status": "sent",
        "participants": sorted([current_user.id, recipient_id]),
        "temp_message_id": temp_message_id  # Store the temp ID for reference
    }
    
    # Insert message
    result = messages_collection.insert_one(message)
    
    # Update conversation metadata
    conversations_collection.update_one(
        {"participants": sorted([current_user.id, recipient_id])},
        {"$set": {
            "last_message": result.inserted_id,
            "updated_at": datetime.utcnow(),
            "unread_count": {
                recipient_id: 0,  # Reset for sender
                current_user.id: 0
            }
        }},
        upsert=True
    )
    
    # Increment unread count for recipient
    conversations_collection.update_one(
        {"participants": sorted([current_user.id, recipient_id])},
        {"$inc": {f"unread_count.{recipient_id}": 1}}
    )
    
    return jsonify({
        "status": "success",
        "message_id": str(result.inserted_id),
        "temp_message_id": temp_message_id  # Return the temp ID
    })

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

@app.route('/check_message_health/<message_id>')
@login_required
def check_message_health(message_id):
    try:
        message = messages_collection.find_one({'_id': ObjectId(message_id)})
        if not message:
            return jsonify({'exists': False}), 404
            
        return jsonify({
            'exists': True,
            'persisted': message.get('persisted', True),
            'timestamp': message['timestamp'].isoformat(),
            'content': message['content']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(current_user.id)
        active_users[current_user.id] = True
        emit('status', {
            'user_id': current_user.id,
            'status': 'online',
            'timestamp': datetime.utcnow().isoformat()
        }, broadcast=True)
        
        # Update last seen status in database
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'last_seen': 'online'}}
        )

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        leave_room(current_user.id)
        active_users.pop(current_user.id, None)
        emit('status', {
            'user_id': current_user.id,
            'status': 'offline',
            'timestamp': datetime.utcnow().isoformat()
        }, broadcast=True)
        
        # Update last seen status in database
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {
                'last_seen': datetime.utcnow(),
                'status': 'offline'
            }}
        )
        
@socketio.on('join_conversation')
def handle_join_conversation(data):
    if current_user.is_authenticated:
        contact_id = data.get('contact_id')  # Changed from conversation_id to contact_id
        if contact_id:
            # Join conversation room (sorted participant IDs)
            room_name = f'conv_{sorted([current_user.id, contact_id])}'
            join_room(room_name)
            
            # Mark messages as read when joining
            messages_collection.update_many(
                {
                    'sender': contact_id,
                    'recipient': current_user.id,
                    'status': 'sent'
                },
                {'$set': {'status': 'read'}}
            )
            
            emit('conversation_joined', {
                'contact_id': contact_id,
                'user_id': current_user.id
            }, room=room_name)


@socketio.on('typing')
def handle_typing(data):
    recipient_id = data.get('recipient')
    is_typing = data.get('is_typing', False)
    
    if recipient_id and current_user.is_authenticated:
        # Set a timeout to automatically turn off typing after 5 seconds
        if is_typing:
            # Store typing state in the user's document
            users_collection.update_one(
                {'_id': ObjectId(current_user.id)},
                {'$set': {'typing': {
                    'recipient': recipient_id,
                    'until': datetime.utcnow() + timedelta(seconds=5)
                }}}
            )
            
            # Schedule automatic turn-off
            def stop_typing():
                current_typing = users_collection.find_one(
                    {'_id': ObjectId(current_user.id)},
                    {'typing': 1}
                )
                if current_typing and current_typing.get('typing', {}).get('recipient') == recipient_id:
                    emit('user_typing', {
                        'sender': current_user.id,
                        'is_typing': False
                    }, room=recipient_id)
                    users_collection.update_one(
                        {'_id': ObjectId(current_user.id)},
                        {'$unset': {'typing': ''}}
                    )
            
            socketio.sleep(5)
            stop_typing()
        
        emit('user_typing', {
            'sender': current_user.id,
            'is_typing': is_typing
        }, room=recipient_id)

@socketio.on('mark_read')
def handle_mark_read(data):
    message_id = data.get('message_id')
    if message_id and current_user.is_authenticated:
        messages_collection.update_one(
            {'_id': ObjectId(message_id), 'recipient': current_user.id},
            {'$set': {'status': 'read'}}
        )
        emit('message_read', {
            'message_id': message_id,
            'read_by': current_user.id,
            'timestamp': datetime.utcnow().isoformat()
        }, broadcast=True)

@app.route('/mark_messages_read', methods=['POST'])
@login_required
def mark_messages_read():
    data = request.get_json()
    contact_id = data.get('contact_id')
    
    if not contact_id:
        return jsonify({'success': False, 'message': 'Contact ID is required'}), 400
    
    # Mark all messages from this contact as read
    messages_collection.update_many(
        {
            'sender': contact_id,
            'recipient': current_user.id,
            'status': 'delivered'
        },
        {'$set': {'status': 'read'}}
    )
    
    # Update unread count in conversation
    conversations_collection.update_one(
        {'participants': sorted([current_user.id, contact_id])},
        {'$set': {f'unread_count.{current_user.id}': 0}}
    )
    
    return jsonify({'success': True})

@app.route('/get_contacts', methods=['GET'])
@login_required
def get_contacts():
    try:
        print(f"\n[DEBUG] Starting get_contacts for user: {current_user.id}")

        # fetch all valid contacts of current user
        user = users_collection.find_one({'_id': ObjectId(current_user.id)})
        if not user or 'contacts' not in user:
            print("[DEBUG] No user or contacts found")
            return jsonify({'contacts': []})

        # Filter out deleted contacts
        contacts = [contact for contact in user['contacts'] if not contact.get('is_deleted', False)]

        contact_ids = [ObjectId(contact['contact_id']) for contact in contacts]
        contact_users = list(users_collection.find(
            {'_id': {'$in': contact_ids}},
            {'username': 1, 'first_name': 1, 'last_name': 1, 'profile_picture': 1, 'last_seen': 1}
        ))

        user_map = {str(u['_id']): u for u in contact_users}
        print(f"[DEBUG] Found {len(contact_users)} contact users")

        contacts_result = []

        for contact in contacts:
            contact_id = str(contact['contact_id'])
            contact_user = user_map.get(contact_id)
            if not contact_user:
                continue

            # Always get the latest message between current_user and contact_id
            last_msg = messages_collection.find_one({
                '$or': [
                    {'sender': current_user.id, 'recipient': contact_id},
                    {'sender': contact_id, 'recipient': current_user.id}
                ]
            }, sort=[('timestamp', -1)])

            last_message = last_msg['content'] if last_msg else 'No messages yet'
            updated_at = last_msg['timestamp'] if last_msg else datetime.utcnow()

            # Get unread count by counting messages from contact_id to current_user not marked as read
            unread_count = messages_collection.count_documents({
                'sender': contact_id,
                'recipient': current_user.id,
                'read': False
            })

            contacts_result.append({
                'user_id': contact_id,
                'name': f"{contact_user.get('first_name', '')} {contact_user.get('last_name', '')}".strip(),
                'profile_picture': contact_user.get('profile_picture'),
                'last_message': last_message,
                'unread_count': unread_count,
                'updated_at': updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
                'status': 'online' if contact_user.get('last_seen') == 'online' else 'offline',
                'is_pinned': contact.get('is_pinned', False)
            })

        # Sort by pinned first, then recent updates
        contacts_result.sort(key=lambda x: (not x['is_pinned'], x['updated_at']), reverse=True)

        print(f"[DEBUG] Returning {len(contacts_result)} contacts")
        return jsonify({'contacts': contacts_result})

    except Exception as e:
        print(f"[ERROR] get_contacts failed: {e}")
        return jsonify({'error': 'Failed to fetch contacts'}), 500

@app.route('/get_conversation/<contact_id>')
@login_required
def get_conversation(contact_id):
    try:
        # Validate contact exists
        if not users_collection.find_one({'_id': ObjectId(contact_id)}):
            return jsonify({'error': 'Contact not found'}), 404

        # Get conversation messages with proper sender/recipient info
        messages = messages_collection.find({
            '$or': [
                {'sender': current_user.id, 'recipient': contact_id},
                {'sender': contact_id, 'recipient': current_user.id}
            ]
        }).sort('timestamp', 1)

        messages_list = []
        for msg in messages:
            messages_list.append({
                'id': str(msg['_id']),
                'sender': str(msg['sender']),  # Ensure string type
                'recipient': str(msg['recipient']),  # Ensure string type
                'content': msg['content'],
                'timestamp': msg['timestamp'].isoformat(),
                'status': msg.get('status', 'sent'),
                'is_current_user': str(msg['sender']) == current_user.id  # Add explicit flag
            })

        return jsonify({'messages': messages_list, 'current_user_id': current_user.id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@socketio.on_error_default
def default_error_handler(e):
    print(f"Socket.IO error: {str(e)}")
    emit('error', {'message': 'An error occurred'})

# Profile Creation Route
@app.route('/create_profile', methods=['GET', 'POST'])
def create_profile():
    if 'user_id' not in session:
        return redirect(url_for('register'))
    
    form = CreateProfileForm()
    if form.validate_on_submit():
        # Update the specific user document using the stored ID
        users_collection.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$set': {
                'first_name': form.first_name.data,
                'last_name': form.last_name.data,
                'gender': form.gender.data,
                'business': form.business.data,
                'country': form.country.data,
                'time_zone': form.time_zone.data
            }}
        )
        return redirect(url_for('upload_profile_picture'))
    
    return render_template("create_profile.html", form=form)

# business profile setup form
@app.route('/business-setup', methods=['GET', 'POST'])
@login_required
def business_setup():
    form = BusinessSetupForm()
    if form.validate_on_submit():
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {
                'business_name': form.business_name.data,
                'business_type': form.business_type.data,
                'business_country': form.country.data,
                'business_location': form.location.data
            }}
        )
        flash('Business information saved!', 'success')
        return redirect(url_for('business_profile'))
    return render_template('business_setup.html', form=form)

@app.route('/upload_profile_picture', methods=['GET', 'POST'])
def upload_profile_picture():
    if 'user_id' not in session:
        return redirect(url_for('register'))
    
    if request.method == 'POST':
        user_id = ObjectId(session['user_id'])
        
        # Handle profile picture
        if 'profile_picture' in request.files:
            profile_pic = request.files['profile_picture']
            if profile_pic.filename != '':
                profile_pic_id = fs.put(profile_pic, filename=profile_pic.filename)
                users_collection.update_one(
                    {'_id': user_id},
                    {'$set': {'profile_picture_id': profile_pic_id}}
                )
        
        # Handle cover photo
        if 'cover_photo' in request.files:
            cover_photo = request.files['cover_photo']
            if cover_photo.filename != '':
                cover_photo_id = fs.put(cover_photo, filename=cover_photo.filename)
                users_collection.update_one(
                    {'_id': user_id},
                    {'$set': {'cover_photo_id': cover_photo_id}}
                )
        
        # Handle biography
        biography = request.form.get('biography', '')
        users_collection.update_one(
            {'_id': user_id},
            {'$set': {'biography': biography}}
        )
        
        return redirect(url_for('dashboard'))
    
    return render_template("upload_profile_picture.html")

# Route to serve files from GridFS
@app.route('/file/<file_id>')
def get_file(file_id):
    # Retrieve the file from GridFS by their ID
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
    try:
        content = request.form.get('content')
        files = request.files.getlist('image')
        is_business_post = request.form.get('is_business_post', 'false') == 'true'

        media_urls = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_id = fs.put(file, filename=filename, content_type=file.content_type)
                media_urls.append(f"/file/{file_id}")

        business_id = None
        if is_business_post:
            business = businesses_collection.find_one({'owner_id': ObjectId(current_user.id)})

        # Get Philippines timezone
        ph_tz = pytz.timezone('UTC')
        utc_now = datetime.now(timezone.utc)  
        ph_time = utc_now.astimezone(ph_tz)

        # Safely get display name
        display_name = current_user.username  # Default to username
        if is_business_post and business:
            display_name = business.get('business_name', display_name)
        elif hasattr(current_user, 'first_name') and hasattr(current_user, 'last_name'):
            display_name = f"{current_user.first_name} {current_user.last_name}".strip()

        post = {
            'content': content,
            'media': media_urls,
            'user_id': current_user.id,
            'username': current_user.username,
            'business_id': business_id,
            'display_name': display_name,
            'is_business_post': is_business_post,
            'created_at_utc': utc_now,
            'created_at_local': ph_time,
            'timezone': 'UTC',
            'created_at_str': ph_time.strftime('%b %d, %Y %I:%M %p')  
        }
        
        posts_collection.insert_one(post)

        return jsonify({
            'message': 'Post created successfully!',
            'timestamp': ph_time.strftime('%b %d, %Y %I:%M %p')
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Get posts route. get all posts sorted by creation time
@app.route('/posts', methods=['GET'])
def get_posts():
    posts_cursor = posts_collection.find().sort('created_at_utc', -1)

    result = []
    for post in posts_cursor:
                if 'created_at_str' in post:
                    display_time = post['created_at_str']
                else:
                    # Fallback to local time formatting
                    ph_tz = pytz.timezone('UTC')
                    if 'created_at_local' in post:
                        local_time = post['created_at_local']
                    else:
                        local_time = post['created_at_utc'].astimezone(ph_tz)
                    display_time = local_time.strftime('%b %d, %Y %I:%M %p')
        
                result.append({
                    'id': str(post['_id']),
                    'content': post.get('content'),
                    'media': post.get('media', []),
                    'username': post.get('username'),
                    'display_name': post.get('display_name'),
                    'created_at_display': display_time,
                    'is_business_post': post.get('is_business_post', False),
                    'created_at': post.get('created_at_local', post.get('created_at_utc')),
                    'created_at_utc': post.get('created_at_utc'),
                    'timezone': post.get('timezone', 'UTC')
                })

    return jsonify(result)

# fixe post timestamps
@app.route('/fix-post-times')
@login_required
def fix_post_times():
    ph_tz = pytz.timezone('UTC')
    updated_count = 0
    
    for post in posts_collection.find():
        if 'created_at_local' in post and isinstance(post['created_at_local'], datetime):
            # Already has proper local time
            continue
            
        if 'created_at_utc' in post:
            utc_time = post['created_at_utc']
            if isinstance(utc_time, str):
                utc_time = datetime.strptime(utc_time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            ph_time = utc_time.astimezone(ph_tz)
        else:
            # If no timestamp exists at all, use current time
            utc_now = datetime.now(timezone.utc)
            ph_time = utc_now.astimezone(ph_tz)
            posts_collection.update_one(
                {'_id': post['_id']},
                {'$set': {'created_at_utc': utc_now}}
            )
        
        posts_collection.update_one(
            {'_id': post['_id']},
            {'$set': {
                'created_at_local': ph_time,
                'timezone': 'UTC',
                'created_at_str': ph_time.strftime('%b %d, %Y %I:%M %p')
            }}
        )
        updated_count += 1
    
    return f"Updated {updated_count} posts with proper timestamps"

# search for users by name
@app.route('/search-users')
@login_required
def search_users():
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify([])
    
    # Search by first name, last name, or combination
    users = users_collection.find({
        '$or': [
            {'first_name': {'$regex': query, '$options': 'i'}},
            {'last_name': {'$regex': query, '$options': 'i'}},
            {'$expr': {'$regexMatch': {
                'input': {'$concat': ['$first_name', ' ', '$last_name']},
                'regex': query,
                'options': 'i'
            }}}
        ],
        '_id': {'$ne': ObjectId(current_user.id)}  # Exclude current user
    }).limit(10)
    
    result = []
    for user in users:
        result.append({
            '_id': str(user['_id']),
            'first_name': user.get('first_name', ''),
            'last_name': user.get('last_name', ''),
            'username': user.get('username', ''),
            'profile_picture': user.get('profile_picture', ''),
            'full_name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        })
    
    return jsonify(result)

# to view another user's profile
@app.route('/profile/<user_id>')
@login_required
def view_profile(user_id):
    try:
        user_obj_id = ObjectId(user_id)
    except:
        flash('Invalid user ID format.', 'error')
        return redirect(url_for('dashboard'))

    user = users_collection.find_one({'_id': user_obj_id})
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('dashboard'))

    posts = list(posts_collection.find({'user_id': user_id}).sort('created_at_utc', -1))

    businesses = list(businesses_collection.find({'owner_id': user_id}))

    return render_template('profile.html',
                           user=user,
                           posts=posts,
                           businesses=businesses,
                           now=datetime.now(pytz.timezone('UTC')))


@app.route('/profile_business/<business_id>', methods=['GET'])
@login_required
def profile_business(business_id):
    try:
        # Get the business being viewed
        business = businesses_collection.find_one({'_id': ObjectId(business_id)})
        if not business:
            flash("Business not found", "error")
            return redirect(url_for('dashboard'))
        
        # Get the owner's user info
        owner = users_collection.find_one({'_id': ObjectId(business['owner_id'])})
        
        # Get posts for this business
        posts = list(posts_collection.find({
            '$or': [
                {'business_id': business_id},
                {'user_id': str(business['owner_id']), 'is_business_post': True}
            ]
        }).sort('created_at_utc', -1))
        
        # Check if current user is the owner (for UI differences)
        is_owner = str(business['owner_id']) == current_user.id
        
        return render_template(
            'profile_business.html',
            business=business,
            user=owner,  # Show business owner's info, not current user
            posts=posts,
            is_owner=is_owner  # Pass this to template for conditional rendering
        )
    except Exception as e:
        flash("Error loading business profile", "error")
        return redirect(url_for('dashboard'))

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

        update_result = users_collection.update_one(
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
        
        if update_result.modified_count > 0:
            flash('Profile updated successfully!', 'success')
        else:
            flash('No changes were made', 'info')
            
        return redirect(url_for('dashboard'))

    return render_template('edit_profile.html', user=user)

# Dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    posts = list(posts_collection.find({'user_id': current_user.id}).sort('created_at_utc', -1))
    businesses = list(businesses_collection.find({'owner_id': current_user.id}))
    
    return render_template('dashboard.html',
                         user=user,
                         posts=posts,
                         businesses=businesses,
                         now=datetime.now(pytz.timezone('UTC')))

# business dashboard route
@app.route('/business_dashboard')
@login_required
def business_dashboard():
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    business = businesses_collection.find_one({'owner_id': current_user.id})
    
    if not business:
        return redirect(url_for('dashboard'))
    
    # Get posts for this business
    posts = list(posts_collection.find({
        '$or': [
            {'business_id': str(business['_id'])},  # Posts directly associated with business
            {'user_id': current_user.id, 'is_business_post': True}  # Business posts by owner
        ]
    }).sort('created_at_utc', -1))
    
    return render_template('business_dashboard.html', 
                         user=user, 
                         business=business,
                         posts=posts)

@app.route('/business/<business_id>', methods=['GET'])
@login_required
def view_business_dashboard(business_id):
    try:
        business = businesses_collection.find_one({'_id': ObjectId(business_id)})
        if not business:
            flash("Business not found", "error")
            return redirect(url_for('dashboard'))
        
        # Get owner info (not current user)
        owner = users_collection.find_one({'_id': ObjectId(business['owner_id'])})
        
        # Get posts for this business (both direct business posts and owner's business posts)
        posts = list(posts_collection.find({
            '$or': [
                {'business_id': business_id},
                {'user_id': business['owner_id'], 'is_business_post': True}
            ]
        }).sort('created_at_utc', -1))
        
        return render_template(
            'business_dashboard.html',
            business=business,
            user=owner,  # Pass owner info as user
            posts=posts
        )
    except Exception as e:
        flash("Error loading business", "error")
        return redirect(url_for('dashboard'))

# Logout route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Home route
@app.route("/")
def index():
    return render_template("index.html", now=datetime.now())

if __name__ == '__main__':
    socketio.run(app, debug=True)