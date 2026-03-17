/** @odoo-module **/

import { BomOverviewControlPanel } from "@mrp/components/bom_overview_control_panel/mrp_bom_overview_control_panel";
import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";
import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";
import { BomOverviewComponentsBlock } from "@mrp/components/bom_overview_components_block/mrp_bom_overview_components_block";
import { BomOverviewTable } from "@mrp/components/bom_overview_table/mrp_bom_overview_table";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

console.log("BOM Resizer: Script Loaded v2 (Global Logic)");

// ── Default to unfolded on load ──────────────────────────────────────────────
patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        this.state.allFolded = false;
    },
});

patch(BomOverviewComponentsBlock, {
    defaultProps: {
        ...BomOverviewComponentsBlock.defaultProps,
        unfoldAll: true,
    },
});

patch(BomOverviewLine, {
    defaultProps: {
        ...BomOverviewLine.defaultProps,
        isFolded: false,
    },
});

// ── Run Purchase Flow button ──────────────────────────────────────────────────
patch(BomOverviewControlPanel.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
    },
    async runPurchaseFlow() {
        const bomId = this.props.data && this.props.data.bom_id;
        if (!bomId) {
            this.notification.add("No BOM found for this overview.", { type: "warning" });
            return;
        }
        try {
            await this.orm.call("mrp.bom", "action_run_purchase_flow_now", [[bomId]]);
            this.notification.add("Purchase flow started successfully.", { type: "success" });
        } catch (e) {
            this.notification.add("Failed to run purchase flow: " + (e.message || ""), { type: "danger" });
        }
    },
});

// ── UNIVERSAL DYNAMIC RESIZING (Document Level to avoid lifecycle issues) ─────
// This logic works for ANY BOM Table/Line on the screen automatically.

const startColumnResize = (ev, th) => {
    ev.stopPropagation();
    ev.preventDefault();
    const startX = ev.clientX;
    const startWidth = th.getBoundingClientRect().width;

    // Ensure table layout is fixed for resizing
    const table = th.closest("table");
    if (table) {
        table.style.tableLayout = "fixed";
        table.style.width = "auto";
        table.style.minWidth = "100%";
    }

    const onMouseMove = (moveEv) => {
        const deltaX = moveEv.clientX - startX;
        const newWidth = Math.max(startWidth + deltaX, 40);
        th.style.width = `${newWidth}px`;
        th.style.minWidth = `${newWidth}px`;
    };

    const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.classList.remove("o_resizing_col");
        console.log("BOM Resizer: Column resize finished");
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.classList.add("o_resizing_col");
    console.log("BOM Resizer: Column resize dragging started");
};

const startRowResize = (ev, tr) => {
    ev.stopPropagation();
    ev.preventDefault();
    const startY = ev.clientY;
    const startHeight = tr.getBoundingClientRect().height;

    const onMouseMove = (moveEv) => {
        const deltaY = moveEv.clientY - startY;
        const newHeight = Math.max(startHeight + deltaY, 20);
        tr.style.height = `${newHeight}px`;
        const tds = tr.querySelectorAll("td");
        tds.forEach(td => {
            td.style.height = `${newHeight}px`;
            td.style.maxHeight = `${newHeight}px`;
        });
    };

    const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.classList.remove("o_resizing_row");
        console.log("BOM Resizer: Row resize finished");
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.classList.add("o_resizing_row");
    console.log("BOM Resizer: Row resize dragging started");
};

// GLOBAL EVENT DELEGATION
document.addEventListener("mousemove", (ev) => {
    // Only care if we are inside a BOM Overview table
    const target = ev.target.closest(".o_mrp_bom_report_page th, .o_mrp_bom_report_page td");
    if (!target) return;

    const rect = target.getBoundingClientRect();
    const isTh = target.tagName === "TH";
    const nearRight = isTh && (rect.right - ev.clientX < 20);
    const nearBottom = (rect.bottom - ev.clientY < 10);

    if (nearRight) {
        target.style.cursor = "col-resize";
        if (!target.dataset.resizer_logged) {
            console.log("BOM Resizer: Near right edge of column", target.innerText);
            target.dataset.resizer_logged = "true";
        }
    } else if (nearBottom) {
        target.style.cursor = "row-resize";
        if (!target.dataset.resizer_logged_row) {
            console.log("BOM Resizer: Near bottom edge of row cell");
            target.dataset.resizer_logged_row = "true";
        }
    } else {
        target.style.cursor = "";
        delete target.dataset.resizer_logged;
        delete target.dataset.resizer_logged_row;
    }
});

document.addEventListener("mousedown", (ev) => {
    const target = ev.target.closest(".o_mrp_bom_report_page th, .o_mrp_bom_report_page td");
    if (!target) return;

    const rect = target.getBoundingClientRect();
    const isTh = target.tagName === "TH";
    const nearRight = isTh && (rect.right - ev.clientX < 20);
    const nearBottom = (rect.bottom - ev.clientY < 10);

    if (nearRight) {
        startColumnResize(ev, target);
    } else if (nearBottom) {
        const tr = target.closest("tr");
        if (tr) startRowResize(ev, tr);
    }
});
