document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ edit_fixtures.js loaded!");

    let toggleDeleteBtn = document.getElementById("toggleDeleteBtn");
    let removeFixtureBtn = document.getElementById("removeFixtureBtn");
    let fixtureTable = document.getElementById("fixtureTable");
    let addFixtureForm = document.getElementById("addFixtureForm");

    /** ✅ Handle Adding Fixture (Submit Form) */
    if (addFixtureForm) {
        addFixtureForm.addEventListener("submit", function (event) {
            event.preventDefault();

            let formData = new FormData(addFixtureForm);
            let fixtureData = Object.fromEntries(formData.entries());

            // ✅ Convert empty strings to null for numeric fields
            fixtureData.channel_count = fixtureData.channel_count ? parseInt(fixtureData.channel_count) : null;
            fixtureData.wattage = fixtureData.wattage ? parseInt(fixtureData.wattage) : null;
            fixtureData.weight = fixtureData.weight ? parseFloat(fixtureData.weight) : null;

            fetch("/add_fixture", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(fixtureData)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert("✅ Fixture added successfully!");
                    addFixtureForm.reset();
                    addFixtureToTable(data.fixture);
                } else {
                    alert(`❌ Error adding fixture: ${data.error}`);
                }
            })
            .catch(error => console.error("❌ Error adding fixture:", error));
        });
    }

    /** ✅ Function to Add Fixture to Table */
    function addFixtureToTable(fixtureData) {
        let tbody = fixtureTable.querySelector("tbody");
        let newRow = document.createElement("tr");
        newRow.setAttribute("data-id", fixtureData.id);

        newRow.innerHTML = `
            <td class="delete-col" style="display: none;">
                <input type="checkbox" class="delete-checkbox" value="${fixtureData.id}">
            </td>
            <td class="editable">${fixtureData.manufacturer}</td>
            <td class="editable">${fixtureData.fixture_type}</td>
            <td class="editable">${fixtureData.mode}</td>
            <td class="editable">${fixtureData.channel_count || ''}</td>
            <td class="editable">${fixtureData.wattage || ''}</td>
            <td class="editable">${fixtureData.weight || ''}</td>
            <td class="editable">${fixtureData.firmware || ''}</td>
            <td class="editable">${fixtureData.notes || ''}</td>
        `;
        tbody.appendChild(newRow);
    }

    /** ✅ Toggle Delete Mode */
    let deleteMode = false;
    toggleDeleteBtn.addEventListener("click", function () {
        deleteMode = !deleteMode;
        let deleteCols = document.querySelectorAll(".delete-col");
        let checkboxes = document.querySelectorAll(".delete-checkbox");

        console.log(`🟢 Toggle Delete Mode: ${deleteMode}`);

        deleteCols.forEach(col => col.style.display = deleteMode ? "table-cell" : "none");
        removeFixtureBtn.style.display = deleteMode ? "inline-block" : "none";
        toggleDeleteBtn.textContent = deleteMode ? "❌ Cancel" : "🗑 Remove Fixture";

        if (!deleteMode) {
            checkboxes.forEach(cb => cb.checked = false);
        }
    });

    /** ✅ Delete Selected Fixtures from SQL & Remove from DOM */
    removeFixtureBtn.addEventListener("click", function () {
        if (!deleteMode) return; // Ensure delete mode is active

        let selectedIds = [];
        document.querySelectorAll(".delete-checkbox:checked").forEach(cb => {
            selectedIds.push(cb.value);
        });

        console.log("🟢 Selected Fixtures for Deletion:", selectedIds);

        if (selectedIds.length === 0) {
            alert("❌ No fixtures selected!");
            return;
        }

        if (!confirm(`❌ Are you sure you want to delete ${selectedIds.length} fixture(s)?`)) return;

        fetch("/delete_fixtures", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fixture_ids: selectedIds })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert("✅ Selected fixtures deleted.");
                selectedIds.forEach(id => {
                    let row = document.querySelector(`tr[data-id='${id}']`);
                    if (row) row.remove();
                });

                // ✅ Reset Delete Mode
                deleteMode = false;
                toggleDeleteBtn.textContent = "🗑 Remove Fixture";
                removeFixtureBtn.style.display = "none";
                document.querySelectorAll(".delete-col").forEach(col => col.style.display = "none");
            } else {
                alert(`❌ Error deleting fixtures: ${data.error}`);
            }
        })
        .catch(error => console.error("❌ Error:", error));
    });
});
