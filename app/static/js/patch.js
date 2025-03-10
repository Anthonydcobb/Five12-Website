document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ patch.js loaded!");

    /*** -------------------- 🔹 VARIABLE SETUP -------------------- ***/

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
    let isDragging = false;
    let selectedCells = new Set();
    let currentColumnIndex = null;

    /*** -------------------- 🔹 INLINE EDIT MODAL SETUP -------------------- ***/
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

    if (!patchId) {
        console.error("❌ Patch ID not found on page!");
        return;
    }

    /*** -------------------- 🔹 FIXTURE MODAL LOGIC -------------------- ***/
    function loadFixtures() {
        if (!fixtureList) {
            console.error("❌ ERROR: Fixture list element not found!");
            return;
        }
    
        console.log("✅ Loading fixture list...");
    
        fetch("/get_fixtures")
            .then(response => response.json())
            .then(data => {
                fixtureList.innerHTML = "";  // ✅ Clear previous entries
                let fixtureMap = {};  // ✅ Group by manufacturer
    
                // ✅ Organize fixtures by manufacturer
                data.forEach(fixture => {
                    if (!fixtureMap[fixture.manufacturer]) {
                        fixtureMap[fixture.manufacturer] = [];
                    }
                    fixtureMap[fixture.manufacturer].push(fixture);
                });
    
                Object.keys(fixtureMap).forEach(manufacturer => {
                    // ✅ Create collapsible manufacturer row
                    let manufacturerRow = document.createElement("tr");
                    manufacturerRow.className = "manufacturer-header";
                    manufacturerRow.innerHTML = `
                        <td colspan="4" style="cursor: pointer; font-weight: bold; background-color: #f0f0f0;">
                            ➕ ${manufacturer}
                        </td>
                    `;
                    manufacturerRow.setAttribute("data-expanded", "false");
                    fixtureList.appendChild(manufacturerRow);
    
                    // ✅ Toggle visibility on click
                    manufacturerRow.addEventListener("click", function () {
                        let isExpanded = manufacturerRow.getAttribute("data-expanded") === "true";
                        document.querySelectorAll(`.fixture-row[data-manufacturer="${manufacturer}"]`).forEach(row => {
                            row.style.display = isExpanded ? "none" : "table-row";
                        });
    
                        manufacturerRow.setAttribute("data-expanded", isExpanded ? "false" : "true");
                        manufacturerRow.innerHTML = `
                            <td colspan="4" style="cursor: pointer; font-weight: bold; background-color: #f0f0f0;">
                                ${isExpanded ? "➕" : "➖"} ${manufacturer}
                            </td>
                        `;
                    });
    
                    // ✅ Add fixture rows under manufacturer
                    fixtureMap[manufacturer].forEach(fixture => {
                        let fixtureRow = document.createElement("tr");
                        fixtureRow.classList.add("fixture-row");
                        fixtureRow.setAttribute("data-manufacturer", manufacturer);
                        fixtureRow.style.display = "none";  // ✅ Initially hidden
    
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
    

















    if (addFixtureBtn) {
        addFixtureBtn.addEventListener("click", function () {
            console.log("✅ 'Add Fixture' button clicked!");  // ✅ Debugging log
            if (fixtureModal) {
                console.log("✅ Fixture modal instance found!");
                fixtureModal.show();
                loadFixtures(); // ✅ Ensure fixtures are loaded when modal opens
            } else {
                console.error("❌ Fixture modal not found!");
            }
        });
    } else {
        console.error("❌ 'Add Fixture' button NOT FOUND!");
    }




    // ✅ "OK" button in the fixture modal
    addFixtureConfirmBtn.addEventListener("click", function () {
        console.log("✅ 'OK' button clicked in fixture modal!");

        let selectedFixtures = [];
        document.querySelectorAll("#fixtureList tr").forEach(row => {
            let countInput = row.querySelector(".fixture-qty");
            if (!countInput) return;

            let quantity = parseInt(countInput.value, 10);
            if (quantity > 0) {
                let fixtureName = row.children[0].textContent.trim();
                let mode = row.children[1].textContent.trim();
                let dmx = row.children[2].textContent.trim();

                for (let i = 0; i < quantity; i++) {
                    selectedFixtures.push({ fixture_name: fixtureName, mode: mode, dmx_footprint: dmx });
                }
            }
        });

        console.log("📥 Fixtures selected:", selectedFixtures);

        if (selectedFixtures.length === 0) {
            console.warn("⚠️ No fixtures selected. Closing modal.");
            fixtureModal.hide();
            return;
        }

        // ✅ Add selected fixtures to the patch table
        selectedFixtures.forEach(fixture => addFixtureToPatch(fixture.fixture_name, fixture.mode, fixture.dmx_footprint));

        fixtureModal.hide();
    });

    /*** -------------------- 🔹 FUNCTION TO ADD FIXTURES TO PATCH TABLE -------------------- ***/
    function addFixtureToPatch(name, mode, dmx) {
        let patchTableBody = document.querySelector("#patchTable tbody");
    
        let tempId = "new-" + Math.random().toString(36).substr(2, 9);
        let row = document.createElement("tr");
        row.setAttribute("data-row-id", tempId);
    
        row.innerHTML = `
            <td contenteditable="true"></td>  <!-- Set -->
            <td contenteditable="true"></td>  <!-- Fix # -->
            <td contenteditable="true"></td>  <!-- Uni -->
            <td contenteditable="true"></td>  <!-- Add -->
            <td>${name}</td>  <!-- Fixture Name -->
            <td>${mode}</td>  <!-- ✅ Mode Column -->
            <td>${dmx}</td>  <!-- DMX Footprint -->
            <td contenteditable="true"></td>  <!-- Location -->
            <td contenteditable="true"></td>  <!-- Notes -->
            <td>—</td>  <!-- Wattage -->
            <td>—</td>  <!-- Weight -->
            <td>—</td>  <!-- Firmware -->
        `;
    
        patchTableBody.appendChild(row);
        console.log(`🆕 Added fixture row for ${name} with mode: ${mode}`);
    
        // ✅ Auto-Save the new fixture
        saveFixtureRow(row);
    }


    function saveFixtureRow(row) {
        let patchTable = document.getElementById("patchTable");
        let patch_id = patchTable ? patchTable.getAttribute("data-patch-id") : null;
        if (!patch_id) {
            console.error("❌ Patch ID not found! Cannot save fixture.");
            return;
        }
    
        let fixtureData = {
            patch_id: patch_id,
            fixture_name: row.children[4].textContent.trim(),
            mode: row.children[5].textContent.trim(),  // ✅ Ensure mode is included
            dmx_footprint: row.children[6].textContent.trim(),
            set_name: row.children[0].textContent.trim(),
            fix_number: row.children[1].textContent.trim(),
            uni: row.children[2].textContent.trim(),
            address: row.children[3].textContent.trim(),
            location: row.children[7].textContent.trim(),
            notes: row.children[8].textContent.trim(),
        };
    
        console.log("📤 Auto-saving fixture:", fixtureData);
    
        fetch("/save_patch_fixtures", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ patch_id, fixtures: [fixtureData] }),
        })
        .then(response => response.json())
        .then(result => {
            if (result.error) {
                console.error("❌ Error saving fixture:", result.error);
            } else {
                console.log("✅ Fixture saved successfully!", result);
            }
        })
        .catch(error => console.error("❌ Fetch error:", error));
    }
    












    

    /*** -------------------- 🔹 LOADING FIXTURES FROM SERVER -------------------- ***/
    if (patchId) {
        fetch(`/get_patch_fixtures/${patchId}`)
            .then(response => response.json())
            .then(data => {
                console.log("✅ Loaded saved fixtures:", data);
                data.forEach(fixture => {
                    addFixtureToPatch(
                        fixture.name, fixture.mode, fixture.dmx,
                        fixture.wattage, fixture.weight, fixture.firmware, fixture.notes
                    );
                });
            })
            .catch(error => console.error("❌ Error loading patch fixtures:", error));
    }

    /*** -------------------- 🔹 INLINE EDITING HANDLING -------------------- ***/
    // ✅ Allow inline editing for specific columns
    patchTable.addEventListener("mousedown", function (event) {
        let cell = event.target.closest("td");
        if (!cell || isEditing) return;

        let columnIndex = cell.cellIndex;
        let header = patchTable.querySelector("thead tr").children[columnIndex].textContent.trim();

        if (!editableColumns.includes(header)) return;

        // ✅ Clear previous selections
        selectedCells.forEach(c => {
            c.classList.remove("focused-cell");
            c.style.border = "";
            c.style.backgroundColor = "";
        });
        selectedCells.clear();

        cell.classList.add("focused-cell");
        cell.style.border = "3px solid blue";
        cell.style.backgroundColor = "rgba(0, 123, 255, 0.3)";
        selectedCells.add(cell);
        isDragging = true;
        currentColumnIndex = columnIndex;
    });

    document.addEventListener("mouseup", function () {
        isDragging = false;
    });

    // ✅ Handle inline edit modal behavior
    document.addEventListener("keydown", function (event) {
        if (event.key.toLowerCase() === "i" && selectedCells.size > 0 && !isEditing) {
            event.preventDefault();

            let firstCell = [...selectedCells][0]; 
            let columnIndex = firstCell.cellIndex;
            let header = patchTable.querySelector("thead tr").children[columnIndex].textContent.trim();

            if (!editableColumns.includes(header)) {
                console.log("❌ Cannot edit this column!");
                return;
            }

            console.log(`✅ Editing ${selectedCells.size} cells in column: ${header}`);

            let rect = firstCell.getBoundingClientRect();
            editModal.style.top = `${rect.top + window.scrollY + 5}px`;
            editModal.style.left = `${rect.left + window.scrollX + 5}px`;
            editModal.style.display = "block";

            editInput.value = firstCell.textContent.trim();
            editInput.focus();
            isEditing = true;
        }
    });

    /*** -------------------- 🔹 SAVE FIXTURES FUNCTION -------------------- ***/
    function saveFixtures() {
        if (!patchId) {
            console.error("❌ Missing patch_id! Aborting save.");
            return;
        }

        let fixtures = [];
        document.querySelectorAll("#patchTable tbody tr").forEach(row => {
            let fixture_name = row.children[4]?.textContent.trim();

            if (!fixture_name) {
                console.warn("⚠️ Skipping row: No fixture name found!", row);
                return;
            }

            fixtures.push({ fixture_name });
        });

        fetch("/save_patch_fixtures", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ patch_id: patchId, fixtures })
        })
        .then(response => response.json())
        .then(result => {
            if (result.error) {
                console.error("❌ Error saving fixtures:", result.error);
            } else {
                console.log("✅ Fixtures saved successfully!", result);
            }
        })
        .catch(error => console.error("❌ Fetch error:", error));
    }
});
