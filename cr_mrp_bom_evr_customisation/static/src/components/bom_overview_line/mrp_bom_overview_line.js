/** @odoo-module **/

import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(BomOverviewLine, {
    props: {
        ...BomOverviewLine.props,
        showOptions: {
            ...BomOverviewLine.props.showOptions,
            approveToManufacture: Boolean,
            purchaseGroup: Boolean,
            freeToUse: Boolean,
            displayCost: Boolean,
            customerRef: Boolean,
            poLineId: Boolean,
        },
    },
});

patch(BomOverviewLine.prototype, {
    setup() {
        super.setup();
        this.ormService = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");  // Add this line

    },

    get availabilityColorClass() {
        if (!this.props.data.hasOwnProperty('availability_state')) {
            return '';
        }
        const state = this.props.data.availability_state;
        if (state === 'available') {
            return 'text-success';
        } else if (state === 'expected') {
            return 'text-warning';
        }
        return 'text-danger';
    },
    async onApproveToManufactureChange(event) {
        const rootBomId = this.props.data.root_bom_id;
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const isChecked = event.target.checked;

        if (!bomLineId) return;

        try {
            const result = await this.ormService.call(
                "mrp.bom.line",
                "action_toggle_approve_to_manufacture",
                [[bomLineId], isChecked],
                { context: { root_bom_id: rootBomId } }
            );

            if (result.success) {
                // ✅ set to what user selected
                this.props.data.approve_to_manufacture = isChecked;
                this.notification.add(result.message, { type: "success" });
            } else {
                // ❌ revert state
                this.props.data.approve_to_manufacture = !isChecked;
                event.target.checked = !isChecked;
                this.notification.add(result.message, { type: "warning" });
            }

        } catch (err) {
            const msg = (err && err.message) || "Approval failed";
            this.notification.add(msg, { type: "danger" });
            this.props.data.approve_to_manufacture = !isChecked;
            event.target.checked = !isChecked;
        }
    },

    async onCustomerRefChange(event) {
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const newValue = event.target.value;

        if (bomLineId) {
            try {
                await this.ormService.write("mrp.bom.line", [bomLineId], {
                    customer_ref: newValue
                });
                this.props.data.customer_ref = newValue;
            } catch (err) {
                const msg = (err && err.data && err.data.message) || "Failed to update customer ref";
                this.notification.add(msg, { type: "danger" });
            }
        }
    },

    _tryToggle: async function (bomLineId, field, newValue, event) {
        const rootBomId = this.props.data.root_bom_id;
        const productId = this.props.data.product_id;

        const lli = this.props.data.lli;
        const approval_1 = this.props.data.approval_1;
        const approval_2 = this.props.data.approval_2;

        await this.ormService.write("mrp.bom.line", [bomLineId], {
            [field]: newValue
        });
        this.props.data[field] = newValue;

        try {
            if (lli && approval_1 && approval_2) {

                const componentId = this.props.data.componentId || false;
                console.log('componentId : ',componentId)

                const result = await this.ormService.call(
                    "mrp.bom.line", "validate_third_boolean",
                    [[bomLineId]],
                    { context: { root_bom_id: rootBomId, qty: this.cr_qty ,componentId: componentId} }
                );

                const results = Array.isArray(result) ? result : [result];


                for (const res of results) {
                    // ✅ show all backend messages one by one
                    if (res.messages && res.messages.length) {
                        for (const msg of res.messages) {
                            // decide type based on keywords in message
                            let type = "info";
                            if (msg.toLowerCase().includes("created")) {
                                type = "success";
                            } else if (msg.toLowerCase().includes("not created") || msg.toLowerCase().includes("no vendor")) {
                                type = "warning";
                            } else if (msg.toLowerCase().includes("error") || msg.toLowerCase().includes("failed")) {
                                type = "danger";
                            }
                            this.notification.add(msg, { type });
                        }
                    } else {
                        // fallback if backend returns no messages
                        this.notification.add("No PO operation message received.", { type: "info" });
                    }
                }



                }
            } catch (err) {
                const msg = (err && err.data && err.data.message) || (err && err.message) || "Validation failed";
                this.notification.add(msg, { type: "danger" });

                await this.ormService.write("mrp.bom.line", [bomLineId], {
                    [field]: !newValue
                });
                this.props.data[field] = !newValue;
                if (event && event.target) {
                    event.target.checked = !newValue;
                }
            }
    },

onPoClick(poId) {
    if (!poId) return;

    this.actionService.doAction({
        type: 'ir.actions.act_window',
        res_model: 'purchase.order',
        res_id: poId,
        views: [[false, 'form']],
        target: 'current',
    });
}

});