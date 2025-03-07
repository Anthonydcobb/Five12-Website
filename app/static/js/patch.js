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

    if (!patchTable) console.log("❌ ERROR: Patch table not found!");
    if (!addFixtureBtn) console.log("❌ ERROR: 'Add Fixture' button not found!");
    if (!fixtureList) console.log("❌ ERROR: Fixture list not found!");
    if (!fixtureModalElement) console.log("❌ ERROR: Fixture modal not found!");
    if (!addFixtureConfirmBtn) console.log("❌ ERROR: 'Confirm Add Fixture' button not found!");

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
                    manufacturerRow.setAttribute("data-expanded", "false"); // ✅ Ensure it starts collapsed
                    manufacturerRow.innerHTML = `
                        <td colspan="4" style="cursor: pointer; font-weight: bold; background-color: #f0f0f0;">
                            <span class="toggle-icon" style="color: purple;">➕</span> ${manufacturer}
                        </td>
                    `;

                    fixtureList.appendChild(manufacturerRow);

                    // ✅ Create and append fixture rows, ensuring they are hidden initially
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
                                       data-id="${fixture.id}" style="width: 60px;" placeholder="">
                            </td>
                        `;

                        fixtureList.appendChild(fixtureRow);
                    });

                    // ✅ Click handler for toggling visibility
                    manufacturerRow.addEventListener("click", function () {
                        let isExpanded = manufacturerRow.getAttribute("data-expanded") === "true";

                        // ✅ Toggle fixture visibility properly
                        document.querySelectorAll(`.fixture-row[data-manufacturer="${manufacturer}"]`).forEach(row => {
                            row.style.display = isExpanded ? "none" : "table-row";
                        });

                        // ✅ Update the toggle icon and expanded state
                        manufacturerRow.setAttribute("data-expanded", isExpanded ? "false" : "true");
                        manufacturerRow.querySelector(".toggle-icon").textContent = isExpanded ? "➕" : "➖";
                    });

                });

                // ✅ Live search functionality for the fixture modal
                // ✅ Live search functionality for the fixture modal
                if (fixtureSearch) {
                    fixtureSearch.addEventListener("input", function () {
                        let searchValue = this.value.trim().toLowerCase();

                        document.querySelectorAll(".manufacturer-header").forEach(manufacturerRow => {
                            let manufacturer = manufacturerRow.getAttribute("data-manufacturer");
                            let anyMatch = false;

                            // ✅ First, show all fixture rows temporarily to check matches
                            document.querySelectorAll(`.fixture-row[data-manufacturer="${manufacturer}"]`).forEach(row => {
                                let fixtureName = row.cells[0]?.textContent.trim().toLowerCase(); // Fixture Name

                                if (fixtureName.includes(searchValue)) {
                                    row.style.display = "table-row"; // ✅ Show matching row
                                    anyMatch = true;
                                } else {
                                    row.style.display = "none"; // ❌ Hide non-matching row
                                }
                            });

                            // ✅ Show or hide manufacturer headers based on matching fixtures
                            manufacturerRow.style.display = anyMatch ? "table-row" : "none";
                        });
                    });
                }

                // ✅ Clear Search Functionality
                if (clearSearchBtn) {
                    clearSearchBtn.addEventListener("click", function () {
                        fixtureSearch.value = "";
                        loadFixtures(); // ✅ Reload the full fixture list
                    });
                }



                console.log("✅ Fixture list loaded successfully!");
            })
            .catch(error => console.error("❌ Error loading fixtures:", error));
    }





});