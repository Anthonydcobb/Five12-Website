document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ patch.js loaded!");

    let patchTable = document.getElementById("patchTable");
    let addFixtureBtn = document.getElementById("addFixtureBtn");
    let fixtureList = document.getElementById("fixtureList");
    let fixtureModalElement = document.getElementById("fixtureModal");
    let fixtureSearch = document.getElementById("fixtureSearch"); // ✅ Search bar
    let clearSearchBtn = document.getElementById("clearSearch"); // ✅ Clear search button
    let addFixtureConfirmBtn = document.getElementById("addFixtureConfirm");
    let patchId = patchTable ? patchTable.getAttribute("data-patch-id") : null;

    let fixtureModal = fixtureModalElement ? new bootstrap.Modal(fixtureModalElement) : null;

    // ✅ Open modal when "Add Fixture" is clicked
    if (addFixtureBtn && fixtureModal) {
        addFixtureBtn.addEventListener("click", function () {
            console.log("✅ 'Add Fixture' button clicked!");
            fixtureModal.show();
            loadFixtures();
        });
    }

    // ✅ Load fixtures with Manufacturer grouping
    function loadFixtures(query = "") {
        if (!fixtureList) {
            console.log("❌ ERROR: Fixture list not found! Skipping load.");
            return;
        }

        console.log("✅ Loading fixture list...");
        fetch("/get_fixtures")
            .then(response => response.json())
            .then(data => {
                fixtureList.innerHTML = ""; // Clear previous fixtures
                let fixtureMap = {}; // Group fixtures by manufacturer

                // ✅ Group fixtures by manufacturer
                data.forEach(fixture => {
                    if (!fixtureMap[fixture.manufacturer]) {
                        fixtureMap[fixture.manufacturer] = [];
                    }
                    fixtureMap[fixture.manufacturer].push(fixture);
                });

                // ✅ Populate manufacturers first
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

                    // ✅ Create and append fixture rows
                    fixtureMap[manufacturer].forEach(fixture => {
                        let fixtureRow = document.createElement("tr");
                        fixtureRow.classList.add("fixture-row");
                        fixtureRow.setAttribute("data-manufacturer", manufacturer);
                        fixtureRow.style.display = "none"; // ✅ Hide on load

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

                    // ✅ Click handler for toggling visibility
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
            })
            .catch(error => console.error("❌ Error loading fixtures:", error));
    }

    // ✅ Add selected fixtures to the patch sheet when "OK" is clicked
    if (addFixtureConfirmBtn) {
        addFixtureConfirmBtn.addEventListener("click", function () {
            console.log("✅ 'OK' button clicked!");

            // ✅ Loop through all count inputs
            document.querySelectorAll(".fixture-qty").forEach(input => {
                let count = parseInt(input.value, 10);
                let fixtureId = input.getAttribute("data-id");
                let fixtureName = input.getAttribute("data-name");
                let mode = input.getAttribute("data-mode");
                let dmxFootprint = input.getAttribute("data-dmx");

                if (count > 0) {
                    console.log(`Adding ${count} of ${fixtureName}`);

                    // ✅ Fetch wattage, weight, firmware, and notes from the database
                    fetch(`/get_fixture_details/${fixtureId}`)
                        .then(response => response.json())
                        .then(details => {
                            let wattage = details.wattage || "—";
                            let weight = details.weight || "—";
                            let firmware = details.firmware || "—";
                            let notes = details.notes || "—"; // ✅ Added Notes field

                            // ✅ Add this many rows to the patch table
                            for (let i = 0; i < count; i++) {
                                addFixtureToPatch(fixtureId, fixtureName, mode, dmxFootprint, wattage, weight, firmware, notes);
                            }
                        })
                        .catch(error => console.error("❌ Error fetching fixture details:", error));
                }
            });

            // ✅ Close the modal after adding fixtures
            fixtureModal.hide();
        });
    }

    // ✅ Function to add fixture to the patch table
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

});
