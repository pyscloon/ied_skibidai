// Setup current user object
let currentUser = { id: null };

// Socket.IO initialization
const socket = io();

// Wait for DOM to load
document.addEventListener('DOMContentLoaded', () => {
    // Fetch current user profile
    fetch('/get_user_profile')
        .then(res => res.json())
        .then(data => {
            currentUser.id = data._id || data.user_id;
            if (data.profile_picture) {
                document.getElementById('profile-picture').src = data.profile_picture;
                document.getElementById('contact-profile-img').src = data.profile_picture;
            }
            loadContacts();
        })
        .catch(err => console.error('Error loading user profile:', err));

    // Setup event listeners
    const sendButton = document.querySelector('.send-button');
    const messageInput = document.querySelector('.message-input input');

    sendButton?.addEventListener('click', sendMessage);
    messageInput?.addEventListener('keypress', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            sendMessage();
        }
    });

    messageInput?.addEventListener('input', () => {
        const contactId = document.getElementById('message-container').getAttribute('data-current-contact');
        if (contactId) {
            socket.emit('typing', { recipient: contactId, is_typing: true });
            clearTimeout(typingTimeout);
            typingTimeout = setTimeout(() => {
                socket.emit('typing', { recipient: contactId, is_typing: false });
            }, 2000);
        }
    });
});

// Load contacts from server
function loadContacts() {
    fetch('/get_contacts')
        .then(res => res.json())
        .then(data => {
            const container = document.querySelector('.Contact');
            container.innerHTML = '';

            data.contacts.forEach(contact => {
                const div = document.createElement('div');
                div.className = 'contact-item flex items-center p-3 hover:bg-gray-700 cursor-pointer rounded-lg mb-2';
                div.setAttribute('data-id', contact.user_id);
                div.setAttribute('data-name', contact.username);

                div.innerHTML = `
                    <div class="chat-profile mr-3">
                        <img src="${contact.profile_picture || '/static/default-profile.png'}" class="w-10 h-10 rounded-full">
                    </div>
                    <div class="message-stack flex-1">
                        <div class="name-profile font-semibold">${contact.username}</div>
                        <span class="status text-xs ${contact.online ? 'text-green-500' : 'text-gray-500'}">
                            ${contact.online ? 'Online' : 'Offline'}
                        </span>
                    </div>
                    <button class="star ${contact.is_pinned ? 'pinned' : ''}">★</button>
                `;

                container.appendChild(div);

                div.addEventListener('click', () => {
                    document.getElementById('contact-name').textContent = contact.username;
                    document.getElementById('message-container').setAttribute('data-current-contact', contact.user_id);
                    fetchMessages(contact.user_id);
                });

                div.querySelector('.star').addEventListener('click', e => {
                    e.stopPropagation();
                    handleStarClick.call(div.querySelector('.star'));
                });
            });

            sortContacts();
        })
        .catch(err => console.error('Error loading contacts:', err));
}

// Fetch messages for a contact
function fetchMessages(contactId) {
    fetch(`/get_conversation/${contactId}`)
        .then(res => res.json())
        .then(data => {
            const container = document.getElementById('message-container');
            container.innerHTML = '';
            data.messages.forEach(msg => appendMessage(msg, msg.sender === currentUser.id));
            container.scrollTop = container.scrollHeight;
        })
        .catch(err => console.error('Error fetching messages:', err));
}

// Append a message to the message container
function appendMessage(msg, isOutgoing) {
    const container = document.getElementById('message-container');
    const div = document.createElement('div');
    div.className = isOutgoing ? 'message-outgoing' : 'message-incoming';

    div.innerHTML = `
        <div class="message-content">
            <p class="message-text">${msg.content}</p>
            <span class="message-meta">
                ${new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                ${isOutgoing ? `<span class="status-icon ${msg.status}"></span>` : ''}
            </span>
        </div>
    `;

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// Show or hide typing indicator
function showTypingIndicator(show) {
    const container = document.getElementById('message-container');
    let indicator = container.querySelector('.typing-indicator');

    if (show && !indicator) {
        indicator = document.createElement('div');
        indicator.className = 'typing-indicator';
        indicator.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
        container.appendChild(indicator);
    } else if (!show && indicator) {
        indicator.remove();
    }
}

// Send message
function sendMessage() {
    const input = document.querySelector('.message-input input');
    const message = input.value.trim();
    const recipientId = document.getElementById('message-container').getAttribute('data-current-contact');
    if (!message || !recipientId) return;

    fetch('/send_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, recipient: recipientId })
    })
    .then(res => res.json())
    .then(() => {
        input.value = '';
        fetchMessages(recipientId);
    })
    .catch(err => console.error('Error sending message:', err));
}

// Handle star (pin) button
function handleStarClick() {
    const contactItem = this.closest('.contact-item');
    const contactId = contactItem.dataset.id;
    const isPinned = this.classList.contains('pinned');
    this.classList.toggle('pinned', !isPinned);

    fetch('/pin_contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contact_id: contactId, is_pinned: !isPinned })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) sortContacts();
    })
    .catch(err => console.error('Error updating pin:', err));
}

// Sort contacts so pinned ones appear first
function sortContacts() {
    const container = document.querySelector('.Contact');
    const contacts = Array.from(container.querySelectorAll('.contact-item'));

    contacts.sort((a, b) => {
        const aPinned = a.querySelector('.star').classList.contains('pinned');
        const bPinned = b.querySelector('.star').classList.contains('pinned');
        return bPinned - aPinned;
    });

    contacts.forEach(contact => container.appendChild(contact));
}

// Add a new contact
function addContact() {
    const username = prompt("Enter the username or email of the user to add:");
    if (!username) return;

    fetch('/add_contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            alert("Contact added!");

            const contactDiv = document.createElement('div');
            contactDiv.className = 'contact-item';
            contactDiv.setAttribute('data-name', `${data.first_name} ${data.last_name}`);
            contactDiv.setAttribute('data-id', data.id);

            contactDiv.innerHTML = `
                <div class="chat-profile">
                    <img src="${data.profile_picture || 'imgs/default-profile.png'}" alt=""> 
                </div>
                <div class="message-stack">
                    <div class="name-profile"><h3>${data.first_name} ${data.last_name}</h3></div>
                </div>
                <button class="delete-button" data-id="${data.id}">
                    <img src="imgs/trash.png" alt="delete contact" class="delete-image">
                    <span class="star">☆</span>
                </button>
            `;

            document.querySelector('.Contact').appendChild(contactDiv);

            // Add click handler for contact and pin star
            contactDiv.addEventListener('click', () => {
                const contactId = contactDiv.getAttribute('data-id');
                document.getElementById('contact-name').textContent = contactDiv.getAttribute('data-name');
                fetchMessages(contactId);
                document.getElementById('message-container').setAttribute('data-current-contact', contactId);
            });

            contactDiv.querySelector('.star').addEventListener('click', handleStarClick);
            sortContacts();

        } else {
            alert(data.message || "Failed to add contact.");
        }
    })
    .catch(err => console.error("Error adding contact:", err));
}

function closeUserModal() {
    document.getElementById('user-modal').classList.add('hidden');
}

// Real-time events
socket.on('new_message', (data) => {
    const currentContact = document.getElementById('message-container').getAttribute('data-current-contact');
    if (currentContact === data.sender) appendMessage(data, false);
});

socket.on('message_sent', (data) => {
    appendMessage(data, true);
});

socket.on('user_typing', (data) => {
    const currentContact = document.getElementById('message-container').getAttribute('data-current-contact');
    if (data.sender === currentContact) {
        showTypingIndicator(data.is_typing);
    }
});

socket.on('status', (data) => {
    const contactItems = document.querySelectorAll('.contact-item');
    contactItems.forEach(item => {
        if (item.getAttribute('data-id') === data.user_id) {
            const statusElem = item.querySelector('.status');
            if (statusElem) {
                statusElem.textContent = data.status === 'online' ? 'Online' : 'Offline';
                statusElem.className = 'status text-xs ' + (data.status === 'online' ? 'text-green-500' : 'text-gray-500');
            }
        }
    });
});

// Typing debounce
let typingTimeout;