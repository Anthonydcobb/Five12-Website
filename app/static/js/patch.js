document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ patch.js loaded!");

    // 🔹 Define all elements first
    let patchTable = document.getElementById("patchTable");
    let addFixtureBtn = document.getElementById("addFixtureBtn");
    let fixtureList = document.getElementById("fixtureList");
    let fixtureModalElement = document.getElementById("fixtureModal");
    let fixtureSearch = document.getElementById("fixtureSearch");
    let clearSearchBtn = document.getElementById("clearSearch");
    let addFixtureConfirmBtn = document.getElementById("addFixtureConfirm");
    let patchId = patchTable ? patchTable.getAttribute("data-patch-id") : null;
    
    let fixtureModal = fixtureModalElement ? new bootstrap.Modal(fixtureModalElement) : null;

    // ✅ Ensure table exists before adding event listeners
    if (patchTable) {
        console.log("✅ patchTable found!");

        // ✅ Add click event for table cells
        patchTable.addEventListener("click", function (event) {
            let cell = event.target.closest("td"); // Ensure we get a table cell
            if (!cell) return;

            console.log("✅ Cell clicked:", cell.textContent.trim());

            // ✅ If the clicked cell is already focused, remove focus
            if (cell.classList.contains("focused-cell")) {
                cell.classList.remove("focused-cell");
                cell.style.border = ""; // Remove custom border
                cell.style.backgroundColor = ""; // Remove highlight
            } else {
                // ✅ Remove focus from other cells before adding to the new one
                document.querySelectorAll(".focused-cell").forEach(c => {
                    c.classList.remove("focused-cell");
                    c.style.border = ""; // Remove border from previous focused cell
                    c.style.backgroundColor = ""; // Remove highlight from previous focused cell
                });

                // ✅ Apply focus class to clicked cell
                cell.classList.add("focused-cell");
                cell.style.border = "3px solid blue"; // Force highlight with JS
                cell.style.backgroundColor = "rgba(0, 123, 255, 0.3)"; // Force background color
            }
        });

        // ✅ Remove focus when clicking outside the table
        document.addEventListener("click", function (event) {
            if (!patchTable.contains(event.target)) {
                document.querySelectorAll(".focused-cell").forEach(c => {
                    c.classList.remove("focused-cell");
                    c.style.border = ""; // Remove border
                    c.style.backgroundColor = ""; // Remove highlight
                });
            }
        });

    } else {
        console.log("❌ patchTable NOT FOUND! Check if #patchTable exists in HTML.");
    }


    // ✅ Ensure function is declared BEFORE usage
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
            <td>${notes || ''}</td>  <!-- ✅ Notes (Added here, AFTER Location) -->
            <td>${wattage}</td>  <!-- ✅ Wattage -->
            <td>${weight}</td>  <!-- ✅ Weight -->
            <td>${firmware}</td>  <!-- ✅ Firmware -->
        `;

        patchTableBody.appendChild(row);
    }

    // ✅ Load saved fixtures when page loads
    if (patchId) {
        fetch(`/get_patch_fixtures/${patchId}`)
            .then(response => response.json())
            .then(data => {
                data.forEach(fixture => {
                    addFixtureToPatch(
                        fixture.id, fixture.name, fixture.mode, fixture.dmx,
                        fixture.wattage, fixture.weight, fixture.firmware, fixture.notes
                    );
                });
            })
            .catch(error => console.error("❌ Error loading patch fixtures:", error));
    }

    // ✅ Open modal when "Add Fixture" is clicked
    if (addFixtureBtn && fixtureModal) {
        addFixtureBtn.addEventListener("click", function () {
            console.log("✅ 'Add Fixture' button clicked!");
            fixtureModal.show();
            loadFixtures();
        });
    }

    // ✅ Load fixtures with Manufacturer grouping
    function loadFixtures() {
        if (!fixtureList) {
            console.log("❌ ERROR: Fixture list not found! Skipping load.");
            return;
        }

        console.log("✅ Loading fixture list...");
        fetch("/get_fixtures")
            .then(response => response.json())
            .then(data => {
                fixtureList.innerHTML = ""; // Clear previous fixtures
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
                    manufacturerRow.setAttribute("data-manufacturer", manufacturer);
                    manufacturerRow.setAttribute("data-expanded", "false");
                    manufacturerRow.innerHTML = `
                        <td colspan="4" style="cursor: pointer; font-weight: bold; background-color: #f0f0f0;">
                            <span class="toggle-icon" style="color: purple;">➕</span> ${manufacturer}
                        </td>
                    `;

                    fixtureList.appendChild(manufacturerRow);

                    fixtureMap[manufacturer].forEach(fixture => {
                        let fixtureRow = document.createElement("tr");
                        fixtureRow.classList.add("fixture-row");
                        fixtureRow.setAttribute("data-manufacturer", manufacturer);
                        fixtureRow.style.display = "none";

                        fixtureRow.innerHTML = `
                            <td>${fixture.name}</td>
                            <td>${fixture.mode || "—"}</td>
                            <td>${fixture.channel_count ? fixture.channel_count + "ch" : "—"}</td>
                            <td>
                                <input type="number" min="0" class="form-control form-control-sm fixture-qty"
                                       data-id="${fixture.id}" data-name="${fixture.name}" data-mode="${fixture.mode}"
                                       data-dmx="${fixture.channel_count}" placeholder="0">
                            </td>
                        `;

                        fixtureList.appendChild(fixtureRow);
                    });

                    manufacturerRow.addEventListener("click", function () {
                        let isExpanded = manufacturerRow.getAttribute("data-expanded") === "true";

                        document.querySelectorAll(`.fixture-row[data-manufacturer="${manufacturer}"]`).forEach(row => {
                            row.style.display = isExpanded ? "none" : "table-row";
                        });

                        manufacturerRow.setAttribute("data-expanded", isExpanded ? "false" : "true");
                        manufacturerRow.querySelector(".toggle-icon").textContent = isExpanded ? "➕" : "➖";
                    });
                });

                console.log("✅ Fixture list loaded successfully!");

                // ✅ Reattach search event
                attachSearchHandler();
            })
            .catch(error => console.error("❌ Error loading fixtures:", error));
    }

    // ✅ Reattach search handler after loading fixtures
    function attachSearchHandler() {
        if (fixtureSearch) {
            fixtureSearch.addEventListener("input", function () {
                let searchValue = this.value.trim().toLowerCase();

                document.querySelectorAll(".manufacturer-header").forEach(manufacturerRow => {
                    let manufacturer = manufacturerRow.getAttribute("data-manufacturer");
                    let anyMatch = false;

                    document.querySelectorAll(`.fixture-row[data-manufacturer="${manufacturer}"]`).forEach(row => {
                        let fixtureName = row.cells[0]?.textContent.trim().toLowerCase();

                        if (fixtureName.includes(searchValue)) {
                            row.style.display = "table-row";
                            anyMatch = true;
                        } else {
                            row.style.display = "none";
                        }
                    });

                    manufacturerRow.style.display = anyMatch ? "table-row" : "none";
                });
            });
        }
    }

    // ✅ Add selected fixtures to the patch sheet and save to backend
    if (addFixtureConfirmBtn) {
        addFixtureConfirmBtn.addEventListener("click", function () {
            console.log("✅ 'OK' button clicked!");
            let fixturesToAdd = [];

            document.querySelectorAll(".fixture-qty").forEach(input => {
                let count = parseInt(input.value, 10);
                let fixtureId = input.getAttribute("data-id");
                let fixtureName = input.getAttribute("data-name");
                let mode = input.getAttribute("data-mode");
                let dmxFootprint = input.getAttribute("data-dmx");

                if (count > 0) {
                    console.log(`Adding ${count} of ${fixtureName}`);

                    fetch(`/get_fixture_details/${fixtureId}`)
                        .then(response => response.json())
                        .then(details => {
                            let wattage = details.wattage || "—";
                            let weight = details.weight || "—";
                            let firmware = details.firmware || "—";
                            let notes = details.notes || "—";

                            for (let i = 0; i < count; i++) {
                                addFixtureToPatch(fixtureId, fixtureName, mode, dmxFootprint, wattage, weight, firmware, notes);

                                fixturesToAdd.push({
                                    fixture_id: fixtureId,
                                    patch_id: patchId,
                                    name: fixtureName,
                                    mode: mode,
                                    dmx: dmxFootprint,
                                    wattage: wattage,
                                    weight: weight,
                                    firmware: firmware,
                                    notes: notes
                                });
                            }

                            // ✅ Make sure to send fixturesToAdd to the backend AFTER processing all the fixtures
                            fetch("/save_patch_fixtures", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ patch_id: patchId, fixtures: fixturesToAdd })
                            })
                                .then(response => response.json())
                                .then(result => {
                                    console.log("✅ Fixtures saved successfully:", result);
                                })
                                .catch(error => console.error("❌ Error saving fixtures:", error));
                        })
                        .catch(error => console.error("❌ Error fetching fixture details:", error));
                }
            });

            fixtureModal.hide();
        });
    }

});
