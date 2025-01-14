// Copyright (c) 2024, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("WhatsApp Group", {
	refresh(frm) {
        frm.add_custom_button('Sync Messages', function () {
            if (!frm.doc.group_id) {
                frappe.throw(__('Group ID is missing. Please check the field.'));
            }
            frappe.call({
                method: "whatsapp_management.whatsapp_management.apis.api.sync_grp",
                args:{
                    group_id: frm.doc.group_id,
                    name: frm.doc.name
                },
                callback: function(r) {
                    console.log(r);
                },
                freeze: true,	
                freeze_message: __('Syncing messages...')
            });
        });
	},
});
