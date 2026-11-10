(() => {
    if (document.getElementById("ticket-notification-bell")) return;

    const style = document.createElement("style");
    style.textContent = `
        #ticket-notification-bell { position: fixed; top: 18px; right: 24px; z-index: 9999; font-family: Arial, sans-serif; }
        #ticket-notification-bell button { cursor: pointer; }
        #ticket-notification-toggle { position: relative; display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; padding: 0; border: 1px solid #dbe3ee; border-radius: 50%; background: #fff; color: #1e293b; box-shadow: 0 3px 12px #0f172a1a; font-size: 21px; line-height: 1; text-align: center; }
        #ticket-notification-toggle > span:first-child { display: block; line-height: 1; font-family: "Segoe UI Emoji", "Apple Color Emoji", sans-serif; }
        #ticket-notification-count { position: absolute; top: -5px; right: -5px; min-width: 19px; height: 19px; padding: 0 5px; border-radius: 12px; background: #dc2626; color: #fff; font-size: 11px; font-weight: 700; line-height: 19px; }
        #ticket-notification-count[hidden] { display: none; }
        #ticket-notification-menu { display: none; position: absolute; top: 52px; right: 0; width: min(340px, calc(100vw - 32px)); max-height: 390px; overflow-y: auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 12px 32px #0f172a24; }
        #ticket-notification-menu.open { display: block; }
        #ticket-notification-menu h3 { margin: 0; padding: 14px 16px; border-bottom: 1px solid #e2e8f0; font-size: 15px; color: #172033; }
        #ticket-notification-items a, #ticket-notification-empty { display: block; padding: 12px 16px; color: #334155; text-decoration: none; border-bottom: 1px solid #f1f5f9; font-size: 13px; }
        #ticket-notification-items a:hover { background: #f8fafc; }
        #ticket-notification-items strong { display: block; color: #0f172a; margin-bottom: 3px; }
    `;
    document.head.appendChild(style);

    const root = document.createElement("div");
    root.id = "ticket-notification-bell";
    root.innerHTML = `
        <button id="ticket-notification-toggle" type="button" aria-label="แจ้งเตือนคำร้อง" aria-expanded="false" title="แจ้งเตือนคำร้อง">
            <span aria-hidden="true">🔔</span><span id="ticket-notification-count" hidden></span>
        </button>
        <section id="ticket-notification-menu" aria-label="แจ้งเตือนคำร้อง">
            <h3>คำร้องใหม่</h3><div id="ticket-notification-items"></div>
        </section>`;
    document.body.appendChild(root);

    const toggle = root.querySelector("#ticket-notification-toggle");
    const count = root.querySelector("#ticket-notification-count");
    const menu = root.querySelector("#ticket-notification-menu");
    const items = root.querySelector("#ticket-notification-items");

    toggle.addEventListener("click", () => {
        const open = menu.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (event) => {
        if (!root.contains(event.target)) {
            menu.classList.remove("open");
            toggle.setAttribute("aria-expanded", "false");
        }
    });

    async function refreshNotifications() {
        try {
            const response = await fetch("/api/notifications", { headers: { Accept: "application/json" } });
            if (!response.ok) return;
            const data = await response.json();
            const unread = data.tickets || [];
            count.textContent = data.count > 99 ? "99+" : String(data.count || "");
            count.hidden = !data.count;
            items.replaceChildren();
            if (!unread.length) {
                const empty = document.createElement("div");
                empty.id = "ticket-notification-empty";
                empty.textContent = "ไม่มีคำร้องใหม่";
                items.appendChild(empty);
                return;
            }
            unread.forEach((ticket) => {
                const link = document.createElement("a");
                link.href = `/ticket/${encodeURIComponent(ticket.id)}`;
                const number = document.createElement("strong");
                number.textContent = ticket.request_number || `คำร้อง #${ticket.id}`;
                const subject = document.createElement("span");
                subject.textContent = ticket.subject || "คำร้องใหม่";
                link.append(number, subject);
                items.appendChild(link);
            });
        } catch (error) {
            // Keep the bell available if notifications cannot be reached temporarily.
        }
    }

    refreshNotifications();
    window.setInterval(refreshNotifications, 5000);
})();
