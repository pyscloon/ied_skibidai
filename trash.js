window.addEventListener("DOMContentLoaded", () => {
    const trashList = document.getElementById("trash-list");

    // If no trash container, return early
    if (!trashList) return;

    // Fetch the trash data from localStorage
    const trash = JSON.parse(localStorage.getItem("trash")) || [];

    // If there's no trash data, display a message
    if (trash.length === 0) {
        trashList.innerHTML = "<p>No deleted conversations found.</p>";
        return;
    }

    // Loop through the trash data and create the deleted contact items
    trash.forEach(item => {
        const div = document.createElement("div");
        div.className = "contact-item trashed";
        div.innerHTML = `
            <div class="chat-profile">
                <img src="imgs/kawhi.jpg" alt="Deleted" class="trash-avatar"> 
            </div>
            <div class="trash-info">
                <h3>${item.name}</h3>
                <p>${item.message || "This conversation has been deleted."}</p>
            </div>
            <button class="undo-button" data-id="${item.id}">Undo</button>
        `;

        // Append the contact item to the trash list
        trashList.appendChild(div);

        // Add the undo functionality
        div.querySelector(".undo-button").addEventListener("click", () => {
            undoDelete(item.id);
            div.remove(); // Remove the item from the trash
        });
    });
});

// Function to handle undo delete (restore contact)
function undoDelete(contactId) {
    // Retrieve the trash data from localStorage
    let trash = JSON.parse(localStorage.getItem("trash")) || [];

    // Find the deleted contact and remove it from the trash
    trash = trash.filter(item => item.id !== contactId);

    // Update localStorage with the updated trash list
    localStorage.setItem("trash", JSON.stringify(trash));

    // Optionally, restore the contact back to the main list or another page
    // (this would require logic on the main page to add the contact back)
    console.log(`Contact ${contactId} restored`);
}