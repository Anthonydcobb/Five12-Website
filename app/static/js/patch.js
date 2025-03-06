document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ patch.js loaded!");

    let patchTable = document.getElementById("patchTable");
    let addFixtureBtn = document.getElementById("addFixtureBtn");
    let fixtureList = document.getElementById("fixtureList");
    let fixtureModalElement = document.getElementById("fixtureModal");
    let addFixtureConfirmBtn = document.getElementById("addFixtureConfirm"); // ✅ Added this
    let patchId = patchTable.getAttribute("data-patch-id"); // ✅ Get Patch ID from table

    // ✅ Debugging: Check if elements exist
    if (!patchTable) console.log("❌ ERROR: Patch table not found!");
    if (!addFixtureBtn) console.log("❌ ERROR: 'Add Fixture' button not found!");
    if (!fixtureList) console.log("❌ ERROR: Fixture list not found!");
    if (!fixtureModalElement) console.log("❌ ERROR: Fixture modal not found!");
    if (!addFixtureConfirmBtn) console.log("❌ ERROR: 'Confirm Add Fixture' button not found!");

    let fixtureModal = null;
    if (fixtureModalElement) {
        fixtureModal = new bootstrap.Modal(fixtureModalElement);
    }

    // ✅ Open modal when "Add Fixture" is clicked
    if (addFixtureBtn && fixtureModal) {
        addFixtureBtn.addEventListener("click", function () {
            console.log("✅ 'Add Fixture' button clicked!");
            fixtureModal.show();
            loadFixtures();
        });
    }

    // ✅ Load fixture list from Flask
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

                data.forEach(fixture => {
                    let li = document.createElement("li");
                    li.className = "list-group-item d-flex justify-content-between align-items-center";
                    li.innerHTML = `
                        <span>${fixture.manufacturer} - ${fixture.name}</span>
                        <input type="number" min="1" value="1" class="form-control form-control-sm fixture-qty" data-id="${fixture.id}" style="width: 60px;">
                    `;
                    fixtureList.appendChild(li);
                });

                console.log("✅ Fixture list loaded successfully!");
            })
            .catch(error => console.error("❌ Error loading fixtures:", error));
    }

    // ✅ Handle "Add Fixture" confirmation button
    if (addFixtureConfirmBtn) {
        addFixtureConfirmBtn.addEventListener("click", function () {
            console.log("✅ 'Confirm Add Fixture' button clicked!");

            let selectedFixtures = [];
            document.querySelectorAll(".fixture-qty").forEach(input => {
                let quantity = parseInt(input.value, 10);
                if (quantity > 0) {
                    selectedFixtures.push({ id: input.dataset.id, qty: quantity });
                }
            });

            if (selectedFixtures.length === 0) {
                alert("❌ Please select at least one fixture.");
                return;
            }

            console.log("✅ Selected Fixtures:", selectedFixtures);

            fetch(`/add_fixture_to_patch/${patchId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ fixtures: selectedFixtures })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert(`❌ Error adding fixtures: ${data.error}`);
                }
            })
            .catch(error => console.error("❌ Error adding fixtures:", error));
        });
    }
});
