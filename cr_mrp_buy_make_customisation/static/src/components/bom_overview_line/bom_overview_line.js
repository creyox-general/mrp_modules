/** @odoo-module **/

import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(BomOverviewLine, {
    props: {
        ...BomOverviewLine.props,
        showOptions: {
            ...BomOverviewLine.props.showOptions,
            buyMakeSelection: Boolean,
        },
    },
});

patch(BomOverviewLine.prototype, {
    setup() {
        super.setup();
        this.ormService = useService("orm");
        this.notification = useService("notification");
    },

    // async onBuyMakeChange(event) {
    //     const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
    //     const newValue = event.target.value;
    //     const rootBomId = this.props.data.root_bom_id;
    //
    //     if (!bomLineId || !newValue) return;
    //
    //     try {
    //         await this.ormService.write("mrp.bom.line", [bomLineId], {
    //             buy_make_selection: newValue
    //         });
    //
    //         this.props.data.buy_make_selection = newValue;
    //
    //         // Update type based on selection
    //         if (newValue === 'buy') {
    //             this.props.data.type = 'component';
    //             this.notification.add(
    //                 "Product marked as BUY - Draft MOs will be cancelled",
    //                 { type: "success" }
    //             );
    //         } else if (newValue === 'make') {
    //             this.props.data.type = 'bom';
    //             this.notification.add(
    //                 "Product marked as MAKE - Will be treated as Sub-BOM",
    //                 { type: "success" }
    //             );
    //         }
    //
    //         // Trigger re-render
    //         this.render();
    //
    //     } catch (err) {
    //         const msg = (err && err.data && err.data.message) || "Failed to update BUY/MAKE selection";
    //         this.notification.add(msg, { type: "danger" });
    //         event.target.value = this.props.data.buy_make_selection || '';
    //     }
    // },
    async onBuyMakeChange(event) {
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const componentIdStr = event.target.getAttribute('data-component-id');
        const branchIdStr = event.target.getAttribute('data-branch-id');
        
        // Parse IDs safely (NaN if empty)
        const componentId = componentIdStr ? parseInt(componentIdStr) : null;
        const branchId = branchIdStr ? parseInt(branchIdStr) : null;
        
        const newValue = event.target.value;
        const rootBomId = this.props.data.root_bom_id;

        if (!newValue) return;

        try {
            // Priority: If it has a component ID, it IS a component. 
            // Components also have branch_ids (their parent), so we MUST check componentId first.
            const recordId = componentId || branchId;
            const model = componentId ? "mrp.bom.line.branch.components" : "mrp.bom.line.branch";
            
            // Call the ATOMIC PROXY on the ROOT BOM model for stability
            const results = await this.ormService.call(
                "mrp.bom",
                "action_transition_bom_line",
                [rootBomId, bomLineId, model, recordId, newValue]
            );

            if (!results || !results.success) {
                this.notification.add("Failed to update selection", { type: "danger" });
                return;
            }

        // Update local data
        this.props.data.buy_make_selection = newValue;

        if (newValue === 'buy') {
            this.props.data.type = 'component';
        } else if (newValue === 'make') {
            this.props.data.type = 'bom';
        }

        // Build comprehensive notification message
        let message = `${results.product_name}: ${results.old_value || 'None'} → ${newValue.toUpperCase()}\n\n`;

        // MOs deleted
        if (results.mos_deleted && results.mos_deleted.length > 0) {
            message += `✗ Deleted ${results.mos_deleted.length} Manufacturing Order(s):\n`;
            results.mos_deleted.slice(0, 5).forEach(mo => {
                message += `  • ${mo.name} (${mo.product})\n`;
            });
            if (results.mos_deleted.length > 5) {
                message += `  ... and ${results.mos_deleted.length - 5} more\n`;
            }
            message += '\n';
        }

        // POs deleted
        if (results.pos_deleted && results.pos_deleted.length > 0) {
            message += `✗ Deleted ${results.pos_deleted.length} Purchase Order Line(s):\n`;
            results.pos_deleted.slice(0, 5).forEach(po => {
                message += `  • ${po.po_name} (${po.product})\n`;
            });
            if (results.pos_deleted.length > 5) {
                message += `  ... and ${results.pos_deleted.length - 5} more\n`;
            }
            message += '\n';
        }

        // Transfers cancelled
        if (results.transfers_cancelled && results.transfers_cancelled.length > 0) {
            message += `✗ Cancelled ${results.transfers_cancelled.length} Internal Transfer(s):\n`;
            results.transfers_cancelled.slice(0, 5).forEach(transfer => {
                message += `  • ${transfer.transfer_name} (${transfer.product})\n`;
            });
            if (results.transfers_cancelled.length > 5) {
                message += `  ... and ${results.transfers_cancelled.length - 5} more\n`;
            }
            message += '\n';
        }

        // Add after transfers_cancelled section
        if (results.transfers_reversed && results.transfers_reversed.length > 0) {
            message += `↩ Reversed ${results.transfers_reversed.length} Transfer(s) to FREE Location:\n`;
            results.transfers_reversed.slice(0, 5).forEach(transfer => {
                message += `  • ${transfer.transfer_name} (${transfer.product}: ${transfer.qty})\n`;
            });
            if (results.transfers_reversed.length > 5) {
                message += `  ... and ${results.transfers_reversed.length - 5} more\n`;
            }
            message += '\n';
        }

        // Branches/components
        if (results.branches_deleted > 0 || results.components_deleted > 0) {
            message += `✗ Reassigned branches: ${results.branches_deleted} branch(es), ${results.components_deleted} component(s)\n\n`;
        }

        // MOs created
        if (results.mos_created && results.mos_created.length > 0) {
            message += `✓ Created ${results.mos_created.length} New Manufacturing Order(s):\n`;
            results.mos_created.slice(0, 5).forEach(mo => {
                message += `  • ${mo.name}: ${mo.product} (Qty: ${mo.qty})\n`;
            });
            if (results.mos_created.length > 5) {
                message += `  ... and ${results.mos_created.length - 5} more\n`;
            }
        }

        // Show notification
        this.notification.add(message, {
            type: "success",
            sticky: true,
            title: "BUY/MAKE Selection Updated"
        });

        // Trigger re-render
        this.render();

    } catch (err) {
        const msg = (err && err.data && err.data.message) || "Failed to update BUY/MAKE selection";
        this.notification.add(msg, { type: "danger" });
        event.target.value = this.props.data.buy_make_selection || '';
    }
},

        async onCriticalChange(event) {
        const componentId = parseInt(event.target.getAttribute('data-component-id')) || null;
        const branchId = parseInt(event.target.getAttribute('data-branch-id')) || null;
        const newValue = event.target.checked;
        const oldValue = this.props.data.critical;

        // Priority: component rows have both IDs — always prefer componentId
        const recordId = componentId || branchId;
        const model = componentId
            ? "mrp.bom.line.branch.components"
            : "mrp.bom.line.branch";

        if (!recordId) {
            this.notification.add(
                "Cannot update: no branch or component record found for this row.",
                { type: "danger", title: "Update Failed" }
            );
            event.target.checked = oldValue;
            return;
        }

        try {
            const result = await this.ormService.call(
                model,
                "write",
                [[recordId], { critical: newValue }]
            );

            if (result) {
                this.props.data.critical = newValue;
                this.notification.add(
                    newValue
                        ? `${this.props.data.display_name} marked as Critical`
                        : `${this.props.data.display_name} unmarked as Critical`,
                    { type: "success", title: "Critical Status Updated" }
                );
            } else {
                throw new Error("Write operation returned false");
            }

        } catch (error) {
            event.target.checked = oldValue;
            this.props.data.critical = oldValue;
            this.notification.add(
                "Failed to update critical status. Please try again.",
                { type: "danger", title: "Update Failed" }
            );
            console.error("Error updating critical status:", error);
        }
    },


    /**
     * Check if critical checkbox should be disabled
     */
    isCriticalDisabled(data) {
        return data.approve_to_manufacture || false;
    },
});