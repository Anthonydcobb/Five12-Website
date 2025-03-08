document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ patch.js loaded!");

    let patchTable = document.getElementById("patchTable");
    let addFixtureBtn = document.getElementById("addFixtureBtn");
    let fixtureList = document.getElementById("fixtureList");
    let fixtureModalElement = document.getElementById("fixtureModal");
    let fixtureSearch = document.getElementById("fixtureSearch");
    let addFixtureConfirmBtn = document.getElementById("addFixtureConfirm");
    let patchId = patchTable ? patchTable.getAttribute("data-patch-id") : null;
    let fixtureModal = fixtureModalElement ? new bootstrap.Modal(fixtureModalElement) : null;

    let editableColumns = ["Set", "Fix #", "Uni", "Add", "Location", "Notes"];
    let isEditing = false;

    // 🔹 Create inline edit modal
    let editModal = document.createElement("div");
    editModal.id = "editModal";
    editModal.style.display = "none";
    editModal.style.position = "absolute";
    editModal.style.padding = "6px";
    editModal.style.backgroundColor = "white";
    editModal.style.border = "3px solid blue";
    editModal.style.boxShadow = "2px 2px 10px rgba(0,0,0,0.3)";
    editModal.innerHTML = `<input type="text" id="editInput" style="width: 100px; padding: 4px;">`;
    document.body.appendChild(editModal);

    let editInput = document.getElementById("editInput");
    let currentEditingCell = null;

    if (patchTable) {
        console.log("✅ patchTable found!");

        // ✅ Click event for highlighting cells
        patchTable.addEventListener("click", function (event) {
            if (isEditing) return;

            let cell = event.target.closest("td");
            if (!cell) return;

            document.querySelectorAll(".focused-cell").forEach(c => {
                c.classList.remove("focused-cell");
                c.style.border = "";
                c.style.backgroundColor = "";
            });

            cell.classList.add("focused-cell");
            cell.style.border = "3px solid blue";
            cell.style.backgroundColor = "rgba(0, 123, 255, 0.3)";

            console.log("✅ Cell clicked:", cell.textContent.trim());
        });

        // ✅ Listen for "I" key to open inline editing modal
        document.addEventListener("keydown", function (event) {
            if (event.key.toLowerCase() === "i" && document.querySelector(".focused-cell") && !isEditing) {
                event.preventDefault();

                let cell = document.querySelector(".focused-cell");
                let columnIndex = cell.cellIndex;
                let header = patchTable.querySelector("thead tr").children[columnIndex].textContent.trim();

                if (!editableColumns.includes(header)) {
                    console.log("❌ Cannot edit this column!");
                    return;
                }

                console.log(`✅ Editing cell at column: ${header}`);

                let rect = cell.getBoundingClientRect();
                editModal.style.top = `${rect.top + window.scrollY + 5}px`;
                editModal.style.left = `${rect.left + window.scrollX + 5}px`;
                editModal.style.display = "block";

                editInput.value = cell.textContent.trim();
                editInput.focus();
                isEditing = true;
                currentEditingCell = cell;
            }
        });

        // ✅ Save changes when pressing "Enter" in modal
        editInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && currentEditingCell) {
                currentEditingCell.textContent = this.value;
                editModal.style.display = "none";
                currentEditingCell = null;
                isEditing = false;
            }
        });

        // ✅ Hide modal when clicking outside
        document.addEventListener("click", function (event) {
            if (!editModal.contains(event.target) && !patchTable.contains(event.target)) {
                editModal.style.display = "none";
                isEditing = false;
                document.querySelectorAll(".focused-cell").forEach(c => {
                    c.classList.remove("focused-cell");
                    c.style.border = "";
                    c.style.backgroundColor = "";
                });
            }
        });

    } else {
        console.log("❌ patchTable NOT FOUND! Check if #patchTable exists in HTML.");
    }

    // ✅ Function to add a fixture row to the patch sheet
    function addFixtureToPatch(id, name, mode, dmx, wattage, weight, firmware, notes) {
        let patchTableBody = document.querySelector("#patchTable tbody");

        let row = document.createElement("tr");

        row.innerHTML = `
            <td></td>  <!-- Set -->
            <td></td>  <!-- Fix # -->
            <td></td>  <!-- Uni -->
            <td></td>  <!-- Add -->
            <td>${name}</td>  <!-- Fix Type -->
            <td>${dmx}</td>  <!-- Ch. Count -->
            <td></td>  <!-- Location -->
            <td>${notes || ''}</td>  <!-- Notes -->
            <td>${wattage}</td>  <!-- Wattage -->
            <td>${weight}</td>  <!-- Weight -->
            <td>${firmware}</td>  <!-- Firmware -->
        `;

        patchTableBody.appendChild(row);
    }

    // ✅ Load saved fixtures when page loads
    if (patchId) {
        fetch(`/get_patch_fixtures/${patchId}`)
            .then(response => response.json())
            .then(data => {
                console.log("✅ Loaded saved fixtures:", data);
                data.forEach(fixture => {
                    addFixtureToPatch(
                        fixture.id, fixture.name, fixture.mode, fixture.dmx,
                        fixture.wattage, fixture.weight, fixture.firmware, fixture.notes
                    );
                });
            })
            .catch(error => console.error("❌ Error loading patch fixtures:", error));
    }

    // ✅ Ensure "Add Fixture" button works
    if (addFixtureBtn) {
        addFixtureBtn.addEventListener("click", function () {
            console.log("✅ 'Add Fixture' button clicked!");
            fixtureModal.show();
            loadFixtures();
        });
    }

    // ✅ Function to load fixtures in modal
    function loadFixtures() {
        if (!fixtureList) {
            console.log("❌ ERROR: Fixture list not found! Skipping load.");
            return;
        }

        console.log("✅ Loading fixture list...");
        fetch("/get_fixtures")
            .then(response => response.json())
            .then(data => {
                fixtureList.innerHTML = "";
                let fixtureMap = {};

                data.forEach(fixture => {
                    if (!fixtureMap[fixture.manufacturer]) {
                        fixtureMap[fixture.manufacturer] = [];
                    }
                    fixtureMap[fixture.manufacturer].push(fixture);
                });

                Object.keys(fixtureMap).forEach(manufacturer => {
                    let manufacturerRow = document.createElement("tr");
                    manufacturerRow.className = "manufacturer-header";
                    manufacturerRow.innerHTML = `<td colspan="4" style="cursor: pointer; font-weight: bold; background-color: #f0f0f0;">➕ ${manufacturer}</td>`;
                    manufacturerRow.setAttribute("data-expanded", "false");
                    fixtureList.appendChild(manufacturerRow);

                    manufacturerRow.addEventListener("click", function () {
                        let isExpanded = manufacturerRow.getAttribute("data-expanded") === "true";
                        document.querySelectorAll(`.fixture-row[data-manufacturer="${manufacturer}"]`).forEach(row => {
                            row.style.display = isExpanded ? "none" : "table-row";
                        });

                        manufacturerRow.setAttribute("data-expanded", isExpanded ? "false" : "true");
                        manufacturerRow.innerHTML = `<td colspan="4" style="cursor: pointer; font-weight: bold; background-color: #f0f0f0;">${isExpanded ? "➕" : "➖"} ${manufacturer}</td>`;
                    });

                    fixtureMap[manufacturer].forEach(fixture => {
                        let fixtureRow = document.createElement("tr");
                        fixtureRow.classList.add("fixture-row");
                        fixtureRow.setAttribute("data-manufacturer", manufacturer);
                        fixtureRow.style.display = "none";

                        fixtureRow.innerHTML = `
                            <td>${fixture.name}</td>
                            <td>${fixture.mode || "—"}</td>
                            <td>${fixture.channel_count || "—"}</td>
                            <td><input type="number" min="0" class="form-control fixture-qty" placeholder="0"></td>
                        `;

                        fixtureList.appendChild(fixtureRow);
                    });
                });

                console.log("✅ Fixture list loaded successfully!");
            })
            .catch(error => console.error("❌ Error loading fixtures:", error));
    }
});
