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
                fixtureList.innerHTML = "";  
                let fixtureMap = {};  

                // ✅ Organize fixtures by manufacturer
                data.forEach(fixture => {
                    if (!fixtureMap[fixture.manufacturer]) {
                        fixtureMap[fixture.manufacturer] = [];
                    }
                    fixtureMap[fixture.manufacturer].push(fixture);
                });

                Object.keys(fixtureMap).forEach(manufacturer => {
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

    /*** -------------------- 🔹 ADD FIXTURES TO PATCH TABLE -------------------- ***/
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

        saveFixtureRow(row);
    }

    function saveFixtureRow(row) {
        let fixtureData = {
            patch_id: patchId,
            fixture_name: row.children[4].textContent.trim(),
            mode: row.children[5].textContent.trim(),
            dmx_footprint: row.children[6].textContent.trim(),
            location: row.children[7].textContent.trim(),
            notes: row.children[8].textContent.trim(),
        };

        console.log("📤 Auto-saving fixture:", fixtureData);

        fetch("/save_patch_fixtures", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ patch_id: patchId, fixtures: [fixtureData] }),
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

    /*** -------------------- 🔹 LOAD PATCH FIXTURES FROM SERVER -------------------- ***/
    if (patchId) {
        fetch(`/get_patch_fixtures/${patchId}`)
            .then(response => response.json())
            .then(data => {
                console.log("✅ Loaded saved fixtures:", data);
                data.forEach(fixture => {
                    addFixtureToPatch(fixture.name, fixture.mode, fixture.dmx);
                });
            })
            .catch(error => console.error("❌ Error loading patch fixtures:", error));
    }


    /*** -------------------- 🔹 INLINE EDITING HANDLING -------------------- ***/
    document.addEventListener("DOMContentLoaded", function () {
        console.log("✅ patch.js loaded!");
    
        let patchTable = document.getElementById("patchTable");
        let editModal = createEditModal();
        let editInput = editModal.querySelector("#editInput");
        let editableColumns = ["Set", "Fix #", "Uni", "Add", "Location", "Notes"];
        let selectedCells = new Set();
        let isDragging = false;
        let currentColumnIndex = null;
        let isEditing = false;
    
        /** ✅ Create and Attach the Edit Modal to the Page **/
        function createEditModal() {
            let modal = document.createElement("div");
            modal.id = "editModal";
            modal.style.display = "none";
            modal.style.position = "absolute";
            modal.style.padding = "6px";
            modal.style.backgroundColor = "white";
            modal.style.border = "3px solid blue";
            modal.style.boxShadow = "2px 2px 10px rgba(0,0,0,0.3)";
            modal.innerHTML = `<input type="text" id="editInput" style="width: 120px; padding: 4px;">`;
            document.body.appendChild(modal);
            return modal;
        }
    
        if (!patchTable) {
            console.error("❌ Patch table NOT FOUND!");
            return;
        }
    
        console.log("✅ Patch table found!");
    
        /** ✅ Click and Drag to Select Multiple Cells (Excel-like) **/
        patchTable.addEventListener("mousedown", function (event) {
            let cell = event.target.closest("td");
            if (!cell || isEditing) return;
    
            let columnIndex = cell.cellIndex;
            let header = patchTable.querySelector("thead tr").children[columnIndex].textContent.trim();
    
            if (!editableColumns.includes(header)) return; // ❌ Only allow editable columns
    
            clearSelection(); // ✅ Clear previous selection
    
            cell.classList.add("focused-cell");
            cell.style.border = "3px solid blue";
            cell.style.backgroundColor = "rgba(0, 123, 255, 0.3)";
            selectedCells.add(cell);
    
            isDragging = true;
            currentColumnIndex = columnIndex;
        });
    
        patchTable.addEventListener("mouseover", function (event) {
            if (isDragging) {
                let newCell = event.target.closest("td");
                if (!newCell || selectedCells.has(newCell)) return;
    
                let header = patchTable.querySelector("thead tr").children[newCell.cellIndex].textContent.trim();
                if (newCell.cellIndex !== currentColumnIndex || !editableColumns.includes(header)) return;
    
                newCell.classList.add("focused-cell");
                newCell.style.border = "3px solid blue";
                newCell.style.backgroundColor = "rgba(0, 123, 255, 0.3)";
                selectedCells.add(newCell);
            }
        });
    
        document.addEventListener("mouseup", function () {
            isDragging = false;
        });
    
        /** ✅ Listen for "I" Key to Open Edit Modal for Selected Cells **/
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
    
        /** ✅ Save Changes When Pressing "Enter" in Modal **/
        editInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && selectedCells.size > 0) {
                let inputValue = editInput.value.trim();
                let columnHeader = patchTable.querySelector("thead tr").children[currentColumnIndex].textContent.trim();
                let isFixColumn = columnHeader === "Fix #";
    
                if (isFixColumn) {
                    let values = calculateFixNumbers(inputValue, selectedCells.size);
                    let index = 0;
                    selectedCells.forEach(cell => {
                        cell.textContent = values[index++];
                    });
                } else {
                    selectedCells.forEach(cell => {
                        cell.textContent = inputValue;
                    });
                }
    
                editModal.style.display = "none";
                isEditing = false;
                clearSelection();
            }
        });
    
        /** ✅ Hide Selection When Clicking Outside the Table **/
        document.addEventListener("click", function (event) {
            if (!patchTable.contains(event.target) && !editModal.contains(event.target)) {
                editModal.style.display = "none";
                isEditing = false;
                clearSelection();
            }
        });
    
        /** ✅ Function to Clear Selection **/
        function clearSelection() {
            selectedCells.forEach(cell => {
                cell.classList.remove("focused-cell");
                cell.style.border = "";
                cell.style.backgroundColor = "";
            });
            selectedCells.clear();
        }
    
        /** ✅ Function to Calculate Fix # Values with Point Patching **/
        function calculateFixNumbers(startValue, count) {
            let result = [];
            let pointMode = startValue.includes("/");
    
            if (pointMode) {
                let [base, perGroup] = startValue.split("/").map(str => str.trim());
                perGroup = parseInt(perGroup, 10);
                let [baseNum, point] = base.split(".").map(Number);
    
                if (isNaN(baseNum) || isNaN(perGroup)) {
                    console.error("❌ Invalid Fix # input.");
                    return [];
                }
    
                for (let i = 0; i < count; i++) {
                    let wholeNumber = baseNum + Math.floor(i / perGroup);
                    let pointNumber = (i % perGroup) + 1;
                    result.push(`${wholeNumber}.${pointNumber}`);
                }
            } else {
                let startNum = parseInt(startValue, 10);
                if (isNaN(startNum)) {
                    console.error("❌ Invalid Fix # input.");
                    return [];
                }
                for (let i = 0; i < count; i++) {
                    result.push(startNum + i);
                }
            }
            console.log("🔢 Calculated Fix Numbers:", result);
            return result;
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
