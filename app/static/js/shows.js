document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ shows.js loaded!");

    // ✅ Open Edit Show Modal
    window.editShow = function (showId, showName) {
        console.log(`Editing show: ${showId}, Current Name: ${showName}`); // Debugging log

        document.getElementById("editShowId").value = showId;
        document.getElementById("editShowName").value = showName;

        let modalElement = document.getElementById("editShowModal");
        let modal = new bootstrap.Modal(modalElement);
        modal.show();
    };

    // ✅ Handle Edit Show Form Submission
    let editShowForm = document.getElementById("editShowForm");
    if (editShowForm) {
        editShowForm.addEventListener("submit", function (event) {
            event.preventDefault();
            
            let showId = document.getElementById("editShowId").value;
            let showName = document.getElementById("editShowName").value;

            console.log(`Submitting edit request: ID=${showId}, New Name=${showName}`); // Debugging

            fetch(`/edit_show/${showId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: showName })
            })
            .then(response => {
                console.log("Response received:", response);
                return response.json().catch(() => null);
            })
            .then(data => {
                console.log("Parsed response data:", data); // Debugging
                if (data && data.success) {
                    console.log("✅ Show updated successfully!");
                    document.getElementById("editShowModal").querySelector(".btn-close").click(); // Close modal
                    setTimeout(() => location.reload(), 500); // Reload page after modal closes
                } else {
                    alert(`❌ Error updating show: ${data?.error || "Unknown error"}`);
                }
            })
            .catch(error => console.error("❌ Error updating show:", error));
        });
    }

    // ✅ Delete Show Function
    window.deleteShow = function (showId) {
        if (!confirm("❌ Are you sure you want to delete this show? This action cannot be undone.")) return;

        fetch(`/delete_show/${showId}`, { method: "POST" })
            .then(response => response.json().catch(() => null)) // ✅ Handle invalid JSON
            .then(data => {
                if (data && data.success) {
                    console.log("✅ Show deleted successfully!");
                    location.reload();
                } else {
                    alert(`❌ Error deleting show: ${data?.error || "Unknown error"}`);
                }
            })
            .catch(error => console.error("❌ Error deleting show:", error));
    };
});
