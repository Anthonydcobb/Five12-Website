document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ show_detail.js loaded!");

    // ✅ Ensure the edit modal elements exist before accessing them
    let editPatchIdField = document.getElementById("editPatchId");
    let editPatchNameField = document.getElementById("editPatchName");
    let editPatchForm = document.getElementById("editPatchForm");
    let editPatchModalElement = document.getElementById("editPatchModal");

    let newPatchForm = document.getElementById("newPatchForm");
    let newPatchNameField = document.getElementById("newPatchName");
    let newPatchModalElement = document.getElementById("newPatchModal");

    /** ✅ Edit Patch Function */
    window.editPatch = function (patchId, patchName) {
        if (!editPatchIdField || !editPatchNameField || !editPatchModalElement) {
            console.error("❌ ERROR: Edit Patch modal elements not found!");
            return;
        }

        editPatchIdField.value = patchId;
        editPatchNameField.value = patchName;

        if (editPatchModalElement) {
            let modal = new bootstrap.Modal(editPatchModalElement);
            modal.show();
        } else {
            console.error("❌ ERROR: Edit Patch Modal not found!");
        }
    };

    // ✅ Ensure form exists before adding event listener for editing
    if (editPatchForm) {
        editPatchForm.addEventListener("submit", function (event) {
            event.preventDefault();

            let patchId = editPatchIdField.value;
            let patchName = editPatchNameField.value.trim();

            if (!patchName) {
                alert("❌ Patch name cannot be empty!");
                return;
            }

            fetch(`/update_patch/${patchId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: patchName })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert(`❌ Error updating patch: ${data.error}`);
                }
            })
            .catch(error => console.error("❌ Error updating patch:", error));
        });
    } else {
        console.error("❌ ERROR: editPatchForm not found in DOM.");
    }

    /** ✅ Delete Patch Function */
    window.deletePatch = function (patchId) {
        if (!confirm("❌ Are you sure you want to delete this patch?")) return;

        fetch(`/delete_patch/${patchId}`, { method: "POST" })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert(`❌ Error deleting patch: ${data.error}`);
                }
            })
            .catch(error => console.error("❌ Error deleting patch:", error));
    };

    /** ✅ Handle "New Patch" Form Submission */
    if (newPatchForm) {
        newPatchForm.addEventListener("submit", function (event) {
            event.preventDefault();

            let showId = newPatchForm.getAttribute("data-show-id");
            let patchName = newPatchNameField.value.trim();

            if (!showId) {
                console.error("❌ ERROR: Missing `showId` in form `data-show-id` attribute.");
                return;
            }

            if (!patchName) {
                alert("❌ Patch name cannot be empty!");
                return;
            }

            fetch(`/add_patch/${showId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: patchName })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert(`❌ Error adding patch: ${data.error}`);
                }
            })
            .catch(error => console.error("❌ Error adding patch:", error));
        });
    } else {
        console.error("❌ ERROR: newPatchForm not found in DOM.");
    }
});
