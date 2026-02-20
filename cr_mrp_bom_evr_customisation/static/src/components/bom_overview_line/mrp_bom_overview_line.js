/** @odoo-module **/

import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(BomOverviewLine, {
    props: {
        ...BomOverviewLine.props,
        showOptions: {
            ...BomOverviewLine.props.showOptions,
            cfeQuantity: Boolean,
            moInternalRef: Boolean,
            lli: Boolean,
            approval1: Boolean,
            approval2: Boolean,
            defaultCode: Boolean,
            oldEverestPn: Boolean,
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
        this.cr_qty = this.data.quantity;
        this.canEditApproval2 = this.props.data.can_edit_approval_2 || false;
        this.actionService = useService("action");  // Add this line

    },

    async onCfeQuantityChange(event) {
        const componentId = this.props.data.componentId || false;
        console.log('componentId : ',componentId)
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const newValue = parseFloat(event.target.value);
        const crQty = parseFloat(this.cr_qty || 0);
        console.log('newValue : ',newValue)
        console.log('crQty : ',crQty)

        // ✅ Validation: CFE must be SMALLER than CR
        if (newValue > crQty) {
                this.env.services.notification.add(
                "CFE Quantity must be smaller than Quantity.",
                { type: "danger" }
        );

        event.target.value = this.props.data.cfe_quantity || '';
        return;
        }


         if (componentId) {
            await this.ormService.write("mrp.bom.line.branch.components", [componentId], {
                cfe_quantity: newValue,quantity: crQty,
            });

            // Update UI instantly
            this.props.data.cfe_quantity = newValue;
            this.props.data.has_cfe_quantity = true;
        }
    },


    async onApproval1Change(event) {
        const componentId = this.props.data.componentId || false;
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const isChecked = event.target.checked;
        const crQty = parseFloat(this.cr_qty || 0);

        if (componentId) {
            await this.ormService.write("mrp.bom.line.branch.components", [componentId], {
                approval_1: isChecked,quantity: crQty,
            });

            // Update UI instantly
//            this.props.data.isChecked = newValue;
        }
    },

    async onApproval2Change(event) {
    // Check permission first
        if (!this.canEditApproval2) {
            this.notification.add(
                "You don't have permission to edit Approval 2. Only Manufacturing/Admin or Purchase/Admin can edit this field.",
                { type: "warning" }
            );
            event.target.checked = !event.target.checked;
            event.preventDefault();
            return;
        }
        const componentId = this.props.data.componentId || false;
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        const isChecked = event.target.checked;
        const crQty = parseFloat(this.cr_qty || 0);
        if (componentId) {
            await this.ormService.write("mrp.bom.line.branch.components", [componentId], {
                approval_2: isChecked,quantity: crQty,
            });

            // Update UI instantly
//            this.props.data.isChecked = newValue;
        }
    },


    async onProductManufacturerChange(event) {
        const componentId = this.props.data.componentId || false;
        const bomLineId = parseInt(event.target.getAttribute("data-bom-line-id"));
        const selectedManufacturerId = parseInt(event.target.value);

        if (componentId && selectedManufacturerId) {
            try {
                // Directly write product_manufacturer_id on bom.line
                await this.ormService.write('mrp.bom.line.branch.components', [componentId], {
                    product_manufacturer_id: selectedManufacturerId,
                });

                // Optional: also call your helper method if you want extra logic
                await this.ormService.call(
                    'mrp.bom.line.branch.components',
                    "set_product_manufacturer_id",
                    [[componentId], selectedManufacturerId]
                );

            }catch (err) {
                const msg = (err?.data?.message) || (err?.message) || "Failed to save Vendor";
                this.notification.add(msg, { type: "danger" });
            }
        }
    },

async goToAction(id, model) {
        if (model === "product.product" || model === "product.template") {
            const mainBomIds = await this.ormService.call(
                "mrp.bom",
                "search",
                [[
                    ["product_tmpl_id", "=", model === "product.template" ? id : false],
                ]],
            );

            if (mainBomIds && mainBomIds.length > 0) {
            return this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "mrp.bom",
                res_id: mainBomIds[0],
                views: [[false, "form"]],
                target: "current",
                context: {
                    active_id: mainBomIds[0],
                },
            });
        }

        }

        return super.goToAction(id, model);
    },

openImageModal(productId, productName) {
    const safeProductName = productName || 'Product Image';
    const modalHtml = `
        <div class="modal fade" id="productImageModal" tabindex="-1" role="dialog">
            <div class="modal-dialog modal-lg modal-dialog-centered" role="document">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${safeProductName}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body text-center p-4">
                        <img src="/web/image/product.product/${productId}/image_1920"
                             class="img-fluid"
                             style="max-height: 70vh; max-width: 100%; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);"
                             alt="${safeProductName}"
                             onerror="this.src='/web/static/img/placeholder.png'"/>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary btn-sm close-modal-btn">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    const existingModal = document.getElementById('productImageModal');
    if (existingModal) {
        existingModal.remove();
    }

    const existingBackdrop = document.getElementById('productImageBackdrop');
    if (existingBackdrop) {
        existingBackdrop.remove();
    }

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modalElement = document.getElementById('productImageModal');
    modalElement.classList.add('show');
    modalElement.style.display = 'block';
    document.body.classList.add('modal-open');

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop fade show';
    backdrop.id = 'productImageBackdrop';
    document.body.appendChild(backdrop);

    const closeModal = () => {
        modalElement.classList.remove('show');
        modalElement.style.display = 'none';
        document.body.classList.remove('modal-open');
        backdrop.remove();
        modalElement.remove();
    };

    modalElement.querySelector('.btn-close').addEventListener('click', closeModal);
    modalElement.querySelector('.close-modal-btn').addEventListener('click', closeModal);
    backdrop.addEventListener('click', closeModal);
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
        console.log('rootBomId : ',rootBomId)
        console.log('this.props.data.branch_id : ',this.props.data.branch_id)
        const branch = this.props.data.branch_id;
        console.log('branch : ',branch)
        const bomLineId = parseInt(event.target.getAttribute('data-bom-line-id'));
        console.log('bomLineId : ',bomLineId)
        const isChecked = event.target.checked;
        console.log('isChecked : ',isChecked)

        if (!branch) return;

        try {
            const result = await this.ormService.call(
                "mrp.bom.line.branch",
                "action_toggle_approve_to_manufacture",
                [[branch], isChecked],
                { context: { root_bom_id: rootBomId ,line: bomLineId} }
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