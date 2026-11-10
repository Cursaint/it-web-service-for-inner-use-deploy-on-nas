document.addEventListener("DOMContentLoaded", () => {
    const nameInput = document.getElementById("requester_name");
    const idInput = document.getElementById("requester_id");
    const departmentInput = document.getElementById("department");
    const suggestions = document.getElementById("search-results");

    // ป้องกัน Error หากหน้า HTML นี้ไม่มีช่อง Requester
    if (!nameInput || !idInput || !suggestions || !departmentInput) return;

    let searchTimer;
    let searchVersion = 0;

    nameInput.addEventListener("input", () => {
        // หากเคยเลือกผู้ใช้จากรายการ (มี idInput) แล้วแก้ไขชื่อ ให้รีเซ็ต idInput
        if (idInput.value) {
            idInput.value = "";
            departmentInput.value = "";
        }
        clearTimeout(searchTimer);

        const q = nameInput.value.trim();
        const version = ++searchVersion;

        suggestions.replaceChildren();
        suggestions.hidden = true;

        if (q.length < 2) return;

        searchTimer = setTimeout(async () => {
            try {
                const response = await fetch(
                    `/api/users?q=${encodeURIComponent(q)}`
                );

                if (!response.ok) {
                    throw new Error("Search failed");
                }

                const users = await response.json();

                // ทิ้งผลลัพธ์เก่าหากมีการค้นหาใหม่
                if (
                    version !== searchVersion ||
                    nameInput.value.trim() !== q ||
                    idInput.value
                ) return;

                suggestions.replaceChildren();

                if (users.length === 0) {
                    const item = document.createElement("div");
                    item.className = "autocomplete-item";
                    item.textContent =
                        "ไม่พบชื่อในระบบ — สามารถกรอกชื่อและแผนกใหม่ได้ทันที (ระบบจะบันทึกให้อัตโนมัติ)";
                    suggestions.appendChild(item);
                } else {
                    users.forEach(user => {
                        const item = document.createElement("button");
                        item.type = "button";
                        item.className = "autocomplete-item";

                        let displayText = user.personal_name;
                        if (user.user_name && user.user_name !== user.personal_name) {
                            displayText += ` (@${user.user_name})`;
                        }
                        if (user.department) {
                            displayText += ` — แผนก: ${user.department}`;
                        }
                        item.textContent = displayText;

                        item.addEventListener("click", () => {
                            nameInput.value = user.personal_name;
                            idInput.value = user.id;
                            departmentInput.value = user.department || "";

                            suggestions.replaceChildren();
                            suggestions.hidden = true;
                        });

                        suggestions.appendChild(item);
                    });
                }

                suggestions.hidden = false;
            } catch (error) {
                if (version !== searchVersion) return;

                suggestions.replaceChildren();
                const item = document.createElement("div");
                item.className = "autocomplete-item";
                item.textContent =
                    "ค้นหารายชื่อไม่สำเร็จ กรุณาลองใหม่";
                suggestions.appendChild(item);
                suggestions.hidden = false;
            }
        }, 250);
    });

    document.addEventListener("click", event => {
        if (
            !nameInput.contains(event.target) &&
            !suggestions.contains(event.target)
        ) {
            suggestions.hidden = true;
        }
    });
});
