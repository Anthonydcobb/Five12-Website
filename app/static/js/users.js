document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ Users JS Loaded");

    document.querySelectorAll(".toggle-admin").forEach(button => {
        button.addEventListener("click", function () {
            let userId = this.dataset.id;
            toggleAdmin(userId);
        });
    });
});

function toggleAdmin(userId) {
    fetch(`/toggle_admin/${userId}`, {  // ✅ Ensure this matches your Flask route
        method: "POST",
        headers: { "Content-Type": "application/json" }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert("✅ Admin status updated!");
            location.reload();
        } else {
            alert("❌ Error updating admin status.");
        }
    })
    .catch(error => console.error("Error:", error));
}
