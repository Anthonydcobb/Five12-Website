document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ Pending Users JS Loaded");

    document.querySelector(".btn-success").addEventListener("click", approveUsers);
    document.querySelector(".btn-danger").addEventListener("click", denyUsers);
});

function getSelectedUsers() {
    let selectedUsers = Array.from(document.querySelectorAll(".approve-checkbox:checked"))
        .map(cb => cb.value);

    console.log("Selected users:", selectedUsers);  // ✅ Debugging
    return selectedUsers;
}

function approveUsers() {
    let selectedUsers = getSelectedUsers();
    let adminUsers = [];

    selectedUsers.forEach(userId => {
        let adminCheckbox = document.querySelector(`.admin-checkbox[data-id="${userId}"]`);
        if (adminCheckbox && adminCheckbox.checked) {
            adminUsers.push(userId);
        }
    });

    if (selectedUsers.length === 0) {
        alert("❌ No users selected.");
        return;
    }

    fetch("/approve_users", {  // ✅ Make sure this matches your Flask Blueprint
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: selectedUsers, admin_ids: adminUsers })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert("✅ Selected users approved!");
            location.reload();
        } else {
            alert("❌ Error approving users.");
        }
    })
    .catch(error => console.error("Error:", error));
}

function denyUsers() {
    let selectedUsers = getSelectedUsers();
    if (selectedUsers.length === 0) {
        alert("❌ No users selected.");
        return;
    }

    if (!confirm("❌ Are you sure you want to deny these users? This action cannot be undone.")) {
        return;
    }

    fetch("/deny_users", {  // ✅ Matches your Flask Blueprint
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: selectedUsers })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert("❌ Selected users denied and removed.");
            location.reload();
        } else {
            alert("⚠️ Error denying users: " + data.error);
        }
    })
    .catch(error => console.error("Error:", error));
}
