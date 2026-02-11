/** @odoo-module **/

import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, useState } from "@odoo/owl";

class SpecialPODialog extends Component {
    static template = "cr_purchase_po_enhancement.SpecialPODialog";
    static components = { Dialog };
    static props = {
        close: Function,
        confirm: Function,
        defaultQuantity: Number,
    };

    setup() {
        this.state = useState({
            actionType: '',
            quantity: this.props.defaultQuantity,
        });
    }

    onActionTypeChange(ev) {
        this.state.actionType = ev.target.value;
    }

    onQuantityChange(ev) {
        this.state.quantity = parseFloat(ev.target.value) || this.props.defaultQuantity;
    }

    onConfirm() {
        if (!this.state.actionType) {
            alert("Please select an option");
            return;
        }
        this.props.confirm(this.state.actionType, this.state.quantity);
        this.props.close();
    }
}

patch(BomOverviewLine.prototype, {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    },

    async onCreateSpecialPO(bomLineId) {
        if (!bomLineId) return;

        const componentId = this.props.data.componentId || false;
        const rootBomId = this.props.data.root_bom_id || false;
        const defaultQuantity = this.cr_qty || this.props.data.quantity || 1.0;

        this.dialog.add(SpecialPODialog, {
            defaultQuantity: defaultQuantity,
            confirm: async (actionType, quantity) => {
                await this._createApprovalRequest(actionType, quantity, bomLineId, componentId, rootBomId);
            },
        });
    },

//    async _createApprovalRequest(actionType, quantity, bomLineId, componentId, rootBomId) {
//        try {
//            const result = await this.ormService.call(
//                "mrp.bom.line",
//                "create_special_po_approval",
//                [bomLineId, actionType, quantity, componentId, rootBomId]
//            );
//
//            if (result && result.approval_id) {
//                this.notification.add("Approval request created successfully", {
//                    type: "success",
//                });
//
//                // Open approval request
//                this.actionService.doAction({
//                    type: 'ir.actions.act_window',
//                    name: 'Approval Request',
//                    res_model: 'approval.request',
//                    res_id: result.approval_id,
//                    view_mode: 'form',
//                    views: [[false, 'form']],
//                    target: 'current',
//                });
//            }
//        } catch (error) {
//            console.error("Error creating approval request:", error);
//            this.notification.add(
//                error.message || "Failed to create approval request",
//                { type: "danger" }
//            );
//        }
//    }

// JavaScript side - update the method
async _createApprovalRequest(actionType, quantity, bomLineId, componentId, rootBomId) {
    try {
        const result = await this.ormService.call(
            "mrp.bom.line",
            "create_special_po_approval",
            [bomLineId, actionType, quantity, componentId, rootBomId]
        );

        if (result && result.error) {
            this.notification.add(result.message, {
                type: "danger",
            });
            return;
        }

        if (result && result.approval_id) {
            this.notification.add("Approval request created successfully", {
                type: "success",
            });

            this.actionService.doAction({
                type: 'ir.actions.act_window',
                name: 'Approval Request',
                res_model: 'approval.request',
                res_id: result.approval_id,
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'current',
            });
        }
    } catch (error) {
        console.error("Error creating approval request:", error);
        this.notification.add(
            error.message || "Failed to create approval request",
            { type: "danger" }
        );
    }
}
});