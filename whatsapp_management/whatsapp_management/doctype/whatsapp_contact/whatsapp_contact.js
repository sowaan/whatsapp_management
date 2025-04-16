// Copyright (c) 2024, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("WhatsApp Contact", {
	refresh: function (frm) {
		frm.add_custom_button(__("Sync Contacts"), function () {
			frappe.call({
				method: "whatsapp_management.whatsapp_management.apis.api.sync_contacts",
				callback: function (r) {
					if (r.message) {
						frappe.msgprint(__("Contacts Synced Successfully!"));
						frm.reload_doc(); // Reload the document
					}
				},
			});
		}).addClass("btn-primary");
	},
});
